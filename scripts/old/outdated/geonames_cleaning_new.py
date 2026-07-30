from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import country_converter as coco
import pandas as pd

from terror_and_fdi.config import INTERIM, RAW


# =============================================================================
# CONFIGURATION
# =============================================================================

GTD_PATH = RAW / "gtd" / "gtd_1993.csv"

GEONAMES_DIR = RAW / "geonames"
GEONAMES_ALL_COUNTRIES = GEONAMES_DIR / "allCountries.txt"
GEONAMES_ALTERNATE_NAMES = GEONAMES_DIR / "alternateNamesV2.txt"

OUTPUT_DIR = INTERIM / "geonames"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Eine Zeile je Referenzstadt: nationale Hauptstadt und/oder Top-3-Stadt.
REFERENCE_CITIES_PATH = (
    OUTPUT_DIR / "geonames_capital_top3_reference_cities.csv"
)

# Alle verwendbaren Schreibweisen der Referenzstädte.
REFERENCE_NAMES_PATH = (
    OUTPUT_DIR / "geonames_capital_top3_reference_names.csv"
)

# Mehrdeutige Schreibweisen werden nicht automatisch gematcht.
AMBIGUOUS_NAMES_PATH = (
    OUTPUT_DIR / "geonames_ambiguous_reference_names.csv"
)

# Vollständiger GTD-Datensatz mit räumlichen Dummies.
MATCHED_GTD_PATH = OUTPUT_DIR / "gtd_with_city_groups.csv"

GTD_CHUNKSIZE = 250_000
GEONAMES_CHUNKSIZE = 500_000
ALTERNATE_NAMES_CHUNKSIZE = 1_000_000

# PPLX (Stadtteil) ist bewusst ausgeschlossen. Damit können Stadtteile nicht
# separat in die landesweite Top-3-Rangfolge gelangen.
TOP3_FEATURE_CODES = {
    "PPL",
    "PPLA",
    "PPLA2",
    "PPLA3",
    "PPLA4",
    "PPLA5",
    "PPLC",
    "PPLG",
}

INVALID_CITY_NAMES = {
    "",
    "unknown",
    "unkown",  # häufiger Tippfehler
    "not applicable",
    "n a",
    "na",
    "none",
    "unspecified",
    "multiple",
    "various",
}

# alternateNamesV2 enthält neben echten Namen auch technische Kennungen und
# Links. Diese Namensräume werden nicht als Städtenamen verwendet.
EXCLUDED_ALIAS_LANGUAGES = {
    "faac",
    "iata",
    "icao",
    "link",
    "post",
    "unlc",
    "wkdt",
}

# Manuelle Ergänzungen für GTD-Schreibweisen, die trotz Normalisierung und
# GeoNames-Aliasen nicht zuverlässig erfasst werden. Der Schlüssel besteht aus
# (ISO3, GTD-Schreibweise), der Wert ist der offizielle oder ASCII-Name der
# gewünschten Referenzstadt. Alle Namen werden innerhalb des Skripts
# normalisiert.
CITY_NAME_OVERRIDES = {
    ("MEX", "Mexico D.F."): "Mexico City",
    ("USA", "New York"): "New York City",
    ("DEU", "München"): "Munich",
}

COUNTRY_OVERRIDES_ISO3 = {
    "United States": "USA",
    "United States of America": "USA",
    "South Korea": "KOR",
    "North Korea": "PRK",
    "Russia": "RUS",
    "Vietnam": "VNM",
    "Venezuela": "VEN",
    "Bolivia": "BOL",
    "Iran": "IRN",
    "Syria": "SYR",
    "Laos": "LAO",
    "Moldova": "MDA",
    "Tanzania": "TZA",
    "Czech Republic": "CZE",
    "Democratic Republic of the Congo": "COD",
    "Republic of the Congo": "COG",
    "West Bank and Gaza Strip": "PSE",
    "Palestine": "PSE",
    "Ivory Coast": "CIV",
    "Cote d'Ivoire": "CIV",
    "Bosnia-Herzegovina": "BIH",
    "East Timor": "TLS",
    "Swaziland": "SWZ",
    "Burma": "MMR",
    "Turkey": "TUR",
    "Brunei": "BRN",
    "Vatican City": "VAT",
    "Slovak Republic": "SVK",
    "Macedonia": "MKD",
    "Wallis and Futuna": "WLF",
    "St. Kitts and Nevis": "KNA",
    "St. Lucia": "LCA",
}

ISO2_OVERRIDES_ISO3 = {
    "XK": "XKX",
}

cc = coco.CountryConverter()


# =============================================================================
# GEONAMES COLUMN DEFINITIONS
# =============================================================================

GEONAMES_COLUMNS = [
    "geonameid",
    "name",
    "asciiname",
    "alternatenames",
    "latitude",
    "longitude",
    "feature_class",
    "feature_code",
    "country_code",
    "cc2",
    "admin1_code",
    "admin2_code",
    "admin3_code",
    "admin4_code",
    "population",
    "elevation",
    "dem",
    "timezone",
    "modification_date",
]

ALTERNATE_NAME_COLUMNS = [
    "alternate_name_id",
    "geonameid",
    "isolanguage",
    "alternate_name",
    "is_preferred_name",
    "is_short_name",
    "is_colloquial",
    "is_historic",
    "from_date",
    "to_date",
]


# =============================================================================
# GENERAL HELPERS
# =============================================================================

def normalize_city_name(value: object) -> str | pd.NA:
    """Normalisiert einen Städtenamen für einen exakten Vergleich."""
    if pd.isna(value):
        return pd.NA

    text = str(value).strip().casefold()
    if not text:
        return pd.NA

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text or text in INVALID_CITY_NAMES:
        return pd.NA

    return text


def convert_country_to_iso3(country: object) -> str | pd.NA:
    """Konvertiert einen GTD-Ländernamen zu ISO3."""
    if pd.isna(country):
        return pd.NA

    country = str(country).strip()
    if country in COUNTRY_OVERRIDES_ISO3:
        return COUNTRY_OVERRIDES_ISO3[country]

    converted = cc.convert(
        names=country,
        src="name_short",
        to="ISO3",
        not_found=None,
    )

    if converted is None:
        return pd.NA

    converted = str(converted)
    if converted in {"", "None", "not found"}:
        return pd.NA

    return converted


def build_country_mapping(country_names: set[str]) -> dict[str, str]:
    """
    Erstellt einmalig eine Zuordnung der GTD-Ländernamen zu ISO3.

    Nicht konvertierbare Länder lösen bewusst einen Fehler aus. Andernfalls
    würden alle ihre Ereignisse still als außerhalb der Referenzstädte gelten.
    """
    mapping = {
        country: convert_country_to_iso3(country)
        for country in sorted(country_names)
    }

    missing = sorted(
        country
        for country, iso3 in mapping.items()
        if pd.isna(iso3)
    )

    if missing:
        raise ValueError(
            "Für folgende GTD-Länder konnte kein ISO3-Code erzeugt werden:\n"
            + "\n".join(f"  - {country}" for country in missing)
            + "\nErgänze sie in COUNTRY_OVERRIDES_ISO3."
        )

    return {
        country: str(iso3)
        for country, iso3 in mapping.items()
    }


def add_iso3_from_iso2(
    df: pd.DataFrame,
    iso2_column: str = "country_code",
) -> pd.DataFrame:
    """Konvertiert die GeoNames-ISO2-Codes gebatcht zu ISO3."""
    unique_codes = df[iso2_column].dropna().astype(str).unique()

    iso_mapping: dict[str, str | pd.NA] = {}

    for iso2 in unique_codes:
        if iso2 in ISO2_OVERRIDES_ISO3:
            iso_mapping[iso2] = ISO2_OVERRIDES_ISO3[iso2]
            continue

        converted = cc.convert(
            names=iso2,
            src="ISO2",
            to="ISO3",
            not_found=None,
        )

        if converted is None or str(converted) in {
            "",
            "None",
            "not found",
        }:
            iso_mapping[iso2] = pd.NA
        else:
            iso_mapping[iso2] = str(converted)

    df["ISO3"] = df[iso2_column].map(iso_mapping)
    return df


def check_required_files() -> None:
    required_files = [
        GTD_PATH,
        GEONAMES_ALL_COUNTRIES,
        GEONAMES_ALTERNATE_NAMES,
    ]

    missing_files = [
        str(path)
        for path in required_files
        if not path.exists()
    ]

    if missing_files:
        raise FileNotFoundError(
            "Folgende benötigte Dateien wurden nicht gefunden:\n"
            + "\n".join(f"  - {path}" for path in missing_files)
        )


# =============================================================================
# STEP 1: DETERMINE GTD COUNTRIES
# =============================================================================

def read_gtd_country_mapping() -> dict[str, str]:
    """
    Liest aus GTD nur die Ländernamen und erstellt die ISO3-Zuordnung.

    Städtenamen und Koordinaten werden hier nicht benötigt, weil keine
    vollständige GTD-Städteliste mehr aufgebaut wird.
    """
    print("1/6: Bestimme die im GTD vorkommenden Länder ...")

    country_names: set[str] = set()

    for chunk in pd.read_csv(
        GTD_PATH,
        usecols=["country_txt"],
        chunksize=GTD_CHUNKSIZE,
        dtype={"country_txt": "string"},
        low_memory=False,
    ):
        country_names.update(
            chunk["country_txt"]
            .dropna()
            .str.strip()
            .loc[lambda series: series.ne("")]
            .astype(str)
            .tolist()
        )

    if not country_names:
        raise ValueError("Im GTD-Datensatz wurden keine Länder gefunden.")

    country_mapping = build_country_mapping(country_names)

    print(
        f"    {len(country_mapping):,} GTD-Länder erfolgreich "
        "zu ISO3 konvertiert."
    )

    return country_mapping


# =============================================================================
# STEP 2: BUILD THE CAPITAL/TOP-3 REFERENCE
# =============================================================================

def read_reference_cities(
    target_iso3_codes: set[str],
) -> pd.DataFrame:
    """
    Liest allCountries.txt einmal chunkweise.

    Gesammelt werden nur:
      - nationale Hauptstädte (feature_code == PPLC),
      - und je Dateichunk die drei größten geeigneten Städte eines Landes.

    Aus den Chunk-Kandidaten werden anschließend landesweit die drei größten
    unterschiedlichen Städte je Land bestimmt. Eine Hauptstadt bleibt auch
    dann in der Referenz, wenn sie nicht zu den drei größten Städten gehört.
    """
    print(
        "2/6: Bestimme nationale Hauptstädte und landesweite "
        "Top-3-Städte ..."
    )

    capital_chunks: list[pd.DataFrame] = []
    top3_candidate_chunks: list[pd.DataFrame] = []

    needed_columns = [
        "geonameid",
        "name",
        "asciiname",
        "latitude",
        "longitude",
        "feature_class",
        "feature_code",
        "country_code",
        "population",
    ]

    for chunk_number, chunk in enumerate(
        pd.read_csv(
            GEONAMES_ALL_COUNTRIES,
            sep="\t",
            header=None,
            names=GEONAMES_COLUMNS,
            usecols=needed_columns,
            chunksize=GEONAMES_CHUNKSIZE,
            dtype={
                "geonameid": "Int64",
                "name": "string",
                "asciiname": "string",
                "feature_class": "string",
                "feature_code": "string",
                "country_code": "string",
            },
            quoting=3,
            on_bad_lines="skip",
            low_memory=False,
        ),
        start=1,
    ):
        chunk = chunk.loc[chunk["feature_class"].eq("P")].copy()
        chunk = add_iso3_from_iso2(chunk)
        chunk = chunk.loc[chunk["ISO3"].isin(target_iso3_codes)].copy()

        if chunk.empty:
            print(f"    GeoNames-Chunk {chunk_number:,}: 0 Kandidaten")
            continue

        chunk["population"] = pd.to_numeric(
            chunk["population"],
            errors="coerce",
        ).fillna(0)

        chunk["latitude"] = pd.to_numeric(
            chunk["latitude"],
            errors="coerce",
        )

        chunk["longitude"] = pd.to_numeric(
            chunk["longitude"],
            errors="coerce",
        )

        chunk["name_normalized"] = chunk["name"].map(
            normalize_city_name
        )

        chunk["asciiname_normalized"] = chunk["asciiname"].map(
            normalize_city_name
        )

        capitals = chunk.loc[
            chunk["feature_code"].eq("PPLC")
            & chunk["name_normalized"].notna()
        ].copy()

        if not capitals.empty:
            capital_chunks.append(capitals)

        top3_candidates = chunk.loc[
            chunk["feature_code"].isin(TOP3_FEATURE_CODES)
            & chunk["name_normalized"].notna()
        ].copy()

        if not top3_candidates.empty:
            top3_candidates = (
                top3_candidates.sort_values(
                    ["ISO3", "population", "geonameid"],
                    ascending=[True, False, True],
                )
                .drop_duplicates(
                    subset=["ISO3", "name_normalized"],
                    keep="first",
                )
                .groupby("ISO3", group_keys=False)
                .head(3)
            )

            top3_candidate_chunks.append(top3_candidates)

        print(
            f"    GeoNames-Chunk {chunk_number:,}: "
            f"{len(capitals):,} Hauptstädte, "
            f"{len(top3_candidates):,} lokale Top-3-Kandidaten"
        )

    if not top3_candidate_chunks:
        raise ValueError("Es wurden keine Top-3-Kandidaten gefunden.")

    top3_cities = pd.concat(
        top3_candidate_chunks,
        ignore_index=True,
    )

    top3_cities = (
        top3_cities.sort_values(
            ["ISO3", "population", "geonameid"],
            ascending=[True, False, True],
        )
        .drop_duplicates(
            subset=["ISO3", "name_normalized"],
            keep="first",
        )
        .groupby("ISO3", group_keys=False)
        .head(3)
        .copy()
    )

    top3_cities["top3_rank"] = (
        top3_cities.groupby("ISO3").cumcount() + 1
    ).astype("Int64")

    if capital_chunks:
        capitals = pd.concat(capital_chunks, ignore_index=True)
        capitals = capitals.drop_duplicates(subset=["geonameid"])
    else:
        capitals = top3_cities.iloc[0:0].copy()

    reference_cities = pd.concat(
        [top3_cities, capitals],
        ignore_index=True,
    )

    reference_cities = reference_cities.drop_duplicates(
        subset=["geonameid"],
        keep="first",
    )

    capital_ids = set(
        capitals["geonameid"].dropna().astype("int64")
    )

    top3_rank = (
        top3_cities.set_index("geonameid")["top3_rank"]
        .to_dict()
    )

    reference_cities["is_capital"] = (
        reference_cities["geonameid"].isin(capital_ids)
    )

    reference_cities["top3_rank"] = (
        reference_cities["geonameid"]
        .map(top3_rank)
        .astype("Int64")
    )

    reference_cities["is_top3"] = (
        reference_cities["top3_rank"].notna()
    )

    reference_cities = (
        reference_cities[
            [
                "ISO3",
                "geonameid",
                "name",
                "asciiname",
                "name_normalized",
                "asciiname_normalized",
                "latitude",
                "longitude",
                "population",
                "feature_code",
                "is_capital",
                "is_top3",
                "top3_rank",
            ]
        ]
        .sort_values(
            ["ISO3", "is_top3", "top3_rank", "is_capital", "name"],
            ascending=[True, False, True, False, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )

    reference_cities.to_csv(
        REFERENCE_CITIES_PATH,
        index=False,
        encoding="utf-8",
    )

    print(
        f"    {len(reference_cities):,} Referenzstädte für "
        f"{reference_cities['ISO3'].nunique():,} Länder gespeichert."
    )

    return reference_cities


# =============================================================================
# STEP 3: READ ALIASES ONLY FOR REFERENCE CITIES
# =============================================================================

def read_reference_aliases(
    reference_geonameids: set[int],
) -> pd.DataFrame:
    """
    Liest alternateNamesV2.txt chunkweise und behält ausschließlich Aliase
    der bereits bestimmten Hauptstadt-/Top-3-Referenzstädte.
    """
    print("3/6: Lade Aliasnamen der Referenzstädte ...")

    relevant_chunks: list[pd.DataFrame] = []

    usecols = [
        "geonameid",
        "isolanguage",
        "alternate_name",
        "is_historic",
    ]

    for chunk_number, chunk in enumerate(
        pd.read_csv(
            GEONAMES_ALTERNATE_NAMES,
            sep="\t",
            header=None,
            names=ALTERNATE_NAME_COLUMNS,
            usecols=usecols,
            chunksize=ALTERNATE_NAMES_CHUNKSIZE,
            dtype={
                "geonameid": "Int64",
                "isolanguage": "string",
                "alternate_name": "string",
                "is_historic": "string",
            },
            quoting=3,
            on_bad_lines="skip",
            low_memory=False,
        ),
        start=1,
    ):
        chunk = chunk.loc[
            chunk["geonameid"].isin(reference_geonameids)
        ].copy()

        chunk = chunk.loc[
            ~chunk["isolanguage"]
            .str.casefold()
            .isin(EXCLUDED_ALIAS_LANGUAGES)
            .fillna(False)
        ].copy()

        chunk["city_normalized"] = chunk["alternate_name"].map(
            normalize_city_name
        )

        chunk = chunk.dropna(
            subset=["geonameid", "city_normalized"]
        )

        if not chunk.empty:
            relevant_chunks.append(chunk)

        print(
            f"    Alias-Chunk {chunk_number:,}: "
            f"{len(chunk):,} Referenzaliase"
        )

    if not relevant_chunks:
        return pd.DataFrame(
            columns=[
                "geonameid",
                "isolanguage",
                "alternate_name",
                "is_historic",
                "city_normalized",
            ]
        )

    aliases = pd.concat(relevant_chunks, ignore_index=True)
    aliases = aliases.drop_duplicates(
        subset=["geonameid", "city_normalized"]
    )

    print(f"    Insgesamt {len(aliases):,} Aliaszeilen geladen.")
    return aliases


# =============================================================================
# STEP 4: BUILD A UNIQUE REFERENCE-NAME LOOKUP
# =============================================================================

def _reference_columns() -> list[str]:
    return [
        "ISO3",
        "geonameid",
        "name",
        "population",
        "feature_code",
        "is_capital",
        "is_top3",
        "top3_rank",
    ]


def build_reference_name_lookup(
    reference_cities: pd.DataFrame,
    aliases: pd.DataFrame,
) -> pd.DataFrame:
    """
    Erzeugt eine kleine Namenstabelle für die Referenzstädte.

    Mehrdeutige Namen, die innerhalb desselben Landes zu mehreren
    Referenzstädten gehören, werden nicht automatisch verwendet. Manuelle
    Overrides können solche Fälle gezielt und transparent auflösen.
    """
    print("4/6: Erzeuge eindeutige Referenz-Namenstabelle ...")

    common = _reference_columns()

    official = reference_cities[common].copy()
    official["city_normalized"] = reference_cities["name_normalized"]
    official["matched_reference_name"] = reference_cities["name"]
    official["name_source"] = "official"

    ascii_names = reference_cities[common].copy()
    ascii_names["city_normalized"] = (
        reference_cities["asciiname_normalized"]
    )
    ascii_names["matched_reference_name"] = reference_cities["asciiname"]
    ascii_names["name_source"] = "ascii"

    alias_lookup = aliases.merge(
        reference_cities[common],
        on="geonameid",
        how="inner",
        validate="many_to_one",
    )

    alias_lookup["matched_reference_name"] = alias_lookup[
        "alternate_name"
    ]

    alias_lookup["name_source"] = "alternate"
    historic_alias = (
        alias_lookup["is_historic"]
        .astype("string")
        .eq("1")
        .fillna(False)
    )
    alias_lookup.loc[historic_alias, "name_source"] = "historic_alias"

    alias_lookup = alias_lookup[
        common
        + [
            "city_normalized",
            "matched_reference_name",
            "name_source",
        ]
    ]

    name_lookup = pd.concat(
        [official, ascii_names, alias_lookup],
        ignore_index=True,
    )

    name_lookup = name_lookup.dropna(
        subset=["ISO3", "geonameid", "city_normalized"]
    )

    source_priority = {
        "official": 0,
        "ascii": 1,
        "alternate": 2,
        "historic_alias": 3,
    }

    name_lookup["_source_priority"] = (
        name_lookup["name_source"].map(source_priority)
    )

    name_lookup = (
        name_lookup.sort_values(
            [
                "ISO3",
                "city_normalized",
                "geonameid",
                "_source_priority",
            ]
        )
        .drop_duplicates(
            subset=["ISO3", "city_normalized", "geonameid"],
            keep="first",
        )
    )

    # Ein Name ist nur dann problematisch, wenn er im selben Land zu mehreren
    # unterschiedlichen Referenzstädten führt.
    candidate_count = (
        name_lookup.groupby(["ISO3", "city_normalized"])["geonameid"]
        .transform("nunique")
    )

    ambiguous = name_lookup.loc[candidate_count.gt(1)].copy()
    name_lookup = name_lookup.loc[candidate_count.eq(1)].copy()

    ambiguous.drop(columns=["_source_priority"]).to_csv(
        AMBIGUOUS_NAMES_PATH,
        index=False,
        encoding="utf-8",
    )

    # Manuelle Overrides werden zuletzt angewendet und haben Vorrang.
    manual_rows: list[pd.Series] = []

    for (iso3, gtd_name), target_name in CITY_NAME_OVERRIDES.items():
        # Overrides für Länder außerhalb des aktuellen GTD-Samples sind
        # irrelevant und werden übersprungen.
        if iso3 not in set(reference_cities["ISO3"]):
            continue

        source_normalized = normalize_city_name(gtd_name)
        target_normalized = normalize_city_name(target_name)

        targets = reference_cities.loc[
            reference_cities["ISO3"].eq(iso3)
            & (
                reference_cities["name_normalized"].eq(target_normalized)
                | reference_cities["asciiname_normalized"].eq(
                    target_normalized
                )
            )
        ]

        if len(targets) != 1:
            raise ValueError(
                "CITY_NAME_OVERRIDES muss genau eine Referenzstadt treffen: "
                f"({iso3!r}, {gtd_name!r}) -> {target_name!r}; "
                f"gefunden: {len(targets)}"
            )

        row = targets.iloc[0][common].copy()
        row["city_normalized"] = source_normalized
        row["matched_reference_name"] = target_name
        row["name_source"] = "manual_override"
        manual_rows.append(row)

        # Der Override ersetzt ein eventuell vorhandenes automatisches Match.
        name_lookup = name_lookup.loc[
            ~(
                name_lookup["ISO3"].eq(iso3)
                & name_lookup["city_normalized"].eq(source_normalized)
            )
        ]

    name_lookup = name_lookup.drop(columns=["_source_priority"])

    if manual_rows:
        manual_lookup = pd.DataFrame(manual_rows)
        name_lookup = pd.concat(
            [name_lookup, manual_lookup],
            ignore_index=True,
        )

    name_lookup = name_lookup.drop_duplicates(
        subset=["ISO3", "city_normalized"],
        keep="last",
    )

    if name_lookup.duplicated(
        subset=["ISO3", "city_normalized"]
    ).any():
        raise ValueError(
            "Die Referenz-Namenstabelle enthält weiterhin doppelte Schlüssel."
        )

    name_lookup = name_lookup.sort_values(
        ["ISO3", "city_normalized"]
    ).reset_index(drop=True)

    name_lookup.to_csv(
        REFERENCE_NAMES_PATH,
        index=False,
        encoding="utf-8",
    )

    print(
        f"    {len(name_lookup):,} eindeutige Referenznamen gespeichert.\n"
        f"    {len(ambiguous):,} mehrdeutige Aliaszeilen ausgeschlossen."
    )

    return name_lookup


# =============================================================================
# STEP 5: ADD THE REFERENCE FLAGS TO GTD
# =============================================================================

def write_classified_gtd(
    country_mapping: dict[str, str],
    name_lookup: pd.DataFrame,
) -> dict[str, int]:
    """
    Liest GTD chunkweise und mergt ausschließlich die kleine Referenztabelle.

    Normale Städte außerhalb der Referenz sind nicht unbekannt. Daher werden
    `city_invalid` und `reference_city_match` getrennt ausgewiesen.
    """
    print("5/6: Klassifiziere die GTD-Ereignisse ...")

    lookup_columns = [
        "ISO3",
        "city_normalized",
        "geonameid",
        "name",
        "matched_reference_name",
        "name_source",
        "population",
        "feature_code",
        "is_capital",
        "is_top3",
        "top3_rank",
    ]

    city_lookup = name_lookup[lookup_columns].rename(
        columns={
            "name": "reference_city_name",
            "population": "reference_city_population",
        }
    )

    if city_lookup.duplicated(
        subset=["ISO3", "city_normalized"]
    ).any():
        raise ValueError(
            "Der Merge-Lookup ist nicht eindeutig auf "
            "ISO3 × city_normalized."
        )

    if MATCHED_GTD_PATH.exists():
        MATCHED_GTD_PATH.unlink()

    totals = {
        "input_rows": 0,
        "output_rows": 0,
        "invalid_city": 0,
        "reference_matches": 0,
        "capital_events": 0,
        "top3_events": 0,
    }

    first_chunk = True

    for chunk_number, chunk in enumerate(
        pd.read_csv(
            GTD_PATH,
            chunksize=GTD_CHUNKSIZE,
            low_memory=False,
        ),
        start=1,
    ):
        input_rows = len(chunk)
        totals["input_rows"] += input_rows

        chunk["ISO3"] = chunk["country_txt"].map(country_mapping)

        if chunk["ISO3"].isna().any():
            missing = sorted(
                chunk.loc[chunk["ISO3"].isna(), "country_txt"]
                .dropna()
                .astype(str)
                .unique()
            )
            raise ValueError(
                "Beim GTD-Merge fehlen ISO3-Codes für: "
                + ", ".join(missing)
            )

        chunk["city_normalized"] = chunk["city"].map(
            normalize_city_name
        )

        chunk["city_invalid"] = chunk["city_normalized"].isna()

        chunk = chunk.merge(
            city_lookup,
            on=["ISO3", "city_normalized"],
            how="left",
            validate="many_to_one",
        )

        if len(chunk) != input_rows:
            raise RuntimeError(
                "Der Referenz-Merge hat die Zahl der GTD-Zeilen verändert."
            )

        chunk["reference_city_match"] = chunk["geonameid"].notna()

        chunk["match_status"] = "not_in_reference"
        chunk.loc[
            chunk["city_invalid"],
            "match_status",
        ] = "invalid_or_missing_city"

        matched = chunk["reference_city_match"]
        chunk.loc[
            matched,
            "match_status",
        ] = (
            "matched_"
            + chunk.loc[matched, "name_source"].astype(str)
        )

        for flag_column in ["is_capital", "is_top3"]:
            chunk[flag_column] = (
                chunk[flag_column]
                .astype("boolean")
                .fillna(False)
                .astype(bool)
            )

        # Unknown/ungültig und alle übrigen Nichttreffer werden damit
        # ausdrücklich als außerhalb von Hauptstadt und Top 3 behandelt.
        month = pd.to_numeric(chunk["imonth"], errors="coerce")
        valid_month = month.between(1, 12)

        chunk["quarter"] = pd.Series(
            pd.NA,
            index=chunk.index,
            dtype="Int64",
        )

        chunk.loc[valid_month, "quarter"] = (
            ((month.loc[valid_month] - 1) // 3) + 1
        ).astype("Int64")

        chunk.to_csv(
            MATCHED_GTD_PATH,
            mode="w" if first_chunk else "a",
            header=first_chunk,
            index=False,
            encoding="utf-8",
        )

        first_chunk = False

        totals["output_rows"] += len(chunk)
        totals["invalid_city"] += int(chunk["city_invalid"].sum())
        totals["reference_matches"] += int(
            chunk["reference_city_match"].sum()
        )
        totals["capital_events"] += int(chunk["is_capital"].sum())
        totals["top3_events"] += int(chunk["is_top3"].sum())

        print(
            f"    GTD-Chunk {chunk_number:,}: "
            f"{len(chunk):,} Zeilen geschrieben"
        )

    if totals["input_rows"] != totals["output_rows"]:
        raise RuntimeError(
            "Die Gesamtzahl der GTD-Zeilen hat sich beim Merge verändert."
        )

    print(f"    Ergebnis gespeichert: {MATCHED_GTD_PATH}")
    return totals


# =============================================================================
# STEP 6: VALIDATE AND PRINT DIAGNOSTICS
# =============================================================================

def print_diagnostics(
    reference_cities: pd.DataFrame,
    name_lookup: pd.DataFrame,
    target_iso3_codes: set[str],
    totals: dict[str, int],
) -> None:
    print("6/6: Diagnose")

    top3_counts = (
        reference_cities.loc[reference_cities["is_top3"]]
        .groupby("ISO3")
        .size()
    )

    if top3_counts.gt(3).any():
        raise ValueError(
            "Für mindestens ein Land wurden mehr als drei "
            "Top-3-Städte erzeugt."
        )

    duplicated_ranks = (
        reference_cities.loc[reference_cities["is_top3"]]
        .duplicated(subset=["ISO3", "top3_rank"], keep=False)
    )

    if duplicated_ranks.any():
        raise ValueError(
            "Innerhalb eines Landes wurde ein Top-3-Rang mehrfach vergeben."
        )

    countries_with_three = int(top3_counts.eq(3).sum())
    countries_with_fewer = sorted(
        target_iso3_codes
        - set(top3_counts.loc[top3_counts.eq(3)].index)
    )

    countries_with_capital = set(
        reference_cities.loc[
            reference_cities["is_capital"],
            "ISO3",
        ]
    )

    countries_without_capital = sorted(
        target_iso3_codes - countries_with_capital
    )

    input_rows = totals["input_rows"]

    def share(value: int) -> str:
        return f"{value / input_rows:.2%}" if input_rows else "n/a"

    print(
        "\nGTD-Zeilenkontrolle:\n"
        f"    Eingelesen:             {totals['input_rows']:,}\n"
        f"    Geschrieben:            {totals['output_rows']:,}\n"
        f"    Ungültiger Stadtname:   {totals['invalid_city']:,} "
        f"({share(totals['invalid_city'])})\n"
        f"    Referenzstadt-Matches:  {totals['reference_matches']:,} "
        f"({share(totals['reference_matches'])})\n"
        f"    Hauptstadt-Ereignisse:  {totals['capital_events']:,} "
        f"({share(totals['capital_events'])})\n"
        f"    Top-3-Ereignisse:       {totals['top3_events']:,} "
        f"({share(totals['top3_events'])})"
    )

    print(
        "\nReferenzkontrolle:\n"
        f"    Referenzstädte:                  "
        f"{len(reference_cities):,}\n"
        f"    Eindeutige Referenznamen:        "
        f"{len(name_lookup):,}\n"
        f"    Länder mit genau drei Städten:   "
        f"{countries_with_three:,}\n"
        f"    Länder mit weniger als drei:     "
        f"{len(countries_with_fewer):,}\n"
        f"    Länder ohne nationale Hauptstadt:"
        f" {len(countries_without_capital):,}"
    )

    if countries_with_fewer:
        print(
            "    Weniger als drei: "
            + ", ".join(countries_with_fewer)
        )

    if countries_without_capital:
        print(
            "    Ohne PPLC-Hauptstadt: "
            + ", ".join(countries_without_capital)
        )

    validation_names = {
        "DEU": "berlin",
        "MEX": "mexico city",
        "USA": "new york city",
    }

    print("\nPlausibilitätsfälle:")

    for iso3, city_name in validation_names.items():
        if iso3 not in target_iso3_codes:
            continue

        case = reference_cities.loc[
            reference_cities["ISO3"].eq(iso3)
            & (
                reference_cities["name_normalized"].eq(city_name)
                | reference_cities["asciiname_normalized"].eq(city_name)
            )
        ]

        if case.empty:
            print(f"    {iso3} / {city_name}: nicht gefunden")
            continue

        row = case.iloc[0]
        rank = (
            int(row["top3_rank"])
            if pd.notna(row["top3_rank"])
            else "-"
        )

        print(
            f"    {iso3} / {city_name}: "
            f"capital={bool(row['is_capital'])}, "
            f"top3={bool(row['is_top3'])}, Rang={rank}"
        )


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def main() -> None:
    check_required_files()

    country_mapping = read_gtd_country_mapping()
    target_iso3_codes = set(country_mapping.values())

    reference_cities = read_reference_cities(
        target_iso3_codes=target_iso3_codes,
    )

    reference_geonameids = set(
        reference_cities["geonameid"]
        .dropna()
        .astype("int64")
    )

    aliases = read_reference_aliases(
        reference_geonameids=reference_geonameids,
    )

    name_lookup = build_reference_name_lookup(
        reference_cities=reference_cities,
        aliases=aliases,
    )

    totals = write_classified_gtd(
        country_mapping=country_mapping,
        name_lookup=name_lookup,
    )

    print_diagnostics(
        reference_cities=reference_cities,
        name_lookup=name_lookup,
        target_iso3_codes=target_iso3_codes,
        totals=totals,
    )


if __name__ == "__main__":
    main()
