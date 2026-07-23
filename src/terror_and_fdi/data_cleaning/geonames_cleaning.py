from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import country_converter as coco
import numpy as np
import pandas as pd

from terror_and_fdi.config import RAW, INTERIM

# =============================================================================
# CONFIGURATION
# =============================================================================

# Passe diese Pfade an deine Projektstruktur an.
GTD_PATH = RAW / "gtd" / "gtd_1993.csv"

GEONAMES_DIR = RAW / "geonames"
GEONAMES_ALL_COUNTRIES = GEONAMES_DIR / "allCountries.txt"
GEONAMES_ALTERNATE_NAMES = GEONAMES_DIR / "alternateNamesV2.txt"

OUTPUT_DIR = INTERIM / "geonames"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Kompakte Tabelle mit einer Zeile pro GTD-Land-Stadt-Kombination.
GTD_CITY_LIST_PATH = OUTPUT_DIR / "gtd_unique_cities.csv"

# Diagnosetabelle mit den GeoNames-Matches.
CITY_MATCHES_PATH = OUTPUT_DIR / "gtd_geonames_city_matches.csv"

# Landesweite Referenztabelle der drei größten GeoNames-Städte.
TOP3_CITIES_PATH = OUTPUT_DIR / "geonames_top3_cities_by_country.csv"

# Vollständiger GTD-Datensatz mit angehängten GeoNames-Variablen.
MATCHED_GTD_PATH = OUTPUT_DIR / "gtd_with_geonames.csv"

# Chunkgrößen. Bei wenig RAM können diese Werte reduziert werden.
GTD_CHUNKSIZE = 250_000
GEONAMES_CHUNKSIZE = 500_000
ALTERNATE_NAMES_CHUNKSIZE = 1_000_000

# Ein großer Abstand ist nicht automatisch ein Fehlmatch, wird aber markiert.
DISTANCE_WARNING_KM = 100.0

# Nur echte Städte bzw. Verwaltungssitze werden für die Top-3-Rangfolge
# berücksichtigt. Insbesondere PPLX (Stadtteil) würde die Rangfolge sonst
# verfälschen. Für das allgemeine GTD-Matching bleiben weiterhin alle
# bewohnten Orte der Feature-Klasse P zulässig.
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

# Unbekannte bzw. nicht sinnvoll matchbare GTD-Städte.
INVALID_CITY_NAMES = {
    "",
    "unknown",
    "not applicable",
    "n a",
    "na",
    "none",
    "unspecified",
    "multiple",
    "various",
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
# COUNTRY NAME OVERRIDES
# =============================================================================

# country_converter löst die meisten GTD-Ländernamen selbstständig auf.
# Für problematische oder historische Bezeichnungen können Overrides ergänzt
# werden. Die Werte rechts sind ISO3-Codes.
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

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def normalize_city_name(value: object) -> str | pd.NA:
    """
    Normalisiert Städtenamen für exakte Vergleiche.

    Beispiele:
        Ciudad de México -> ciudad de mexico
        México D.F.      -> mexico d f
        New-York City    -> new york city
    """
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

    # Apostrophe entfernen, damit z. B. N'Djamena und Ndjamena gleich werden.
    text = text.replace("'", "")
    text = text.replace("’", "")

    # Alle übrigen Sonderzeichen durch Leerzeichen ersetzen.
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text or text in INVALID_CITY_NAMES:
        return pd.NA

    return text


def convert_country_to_iso3(country: object) -> str | pd.NA:
    """
    Konvertiert einen einzelnen GTD-Ländernamen zu ISO3.

    Wird nur noch auf eindeutige Ländernamen angewendet (siehe
    `add_iso3_from_country_txt`), nicht mehr pro Zeile.
    """
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

    if converted in {"not found", "None", ""}:
        return pd.NA

    return converted


def add_iso3_from_country_txt(
    df: pd.DataFrame,
    country_txt_column: str = "country_txt",
) -> pd.DataFrame:
    """
    Fügt eine ISO3-Spalte basierend auf `country_txt_column` hinzu.

    Wichtig für die Performance: `cc.convert()` wird nur einmal pro
    eindeutigem Ländernamen aufgerufen, nicht pro Zeile. Bei GTD mit
    mehreren hunderttausend Zeilen aber nur ein paar hundert eindeutigen
    Ländernamen spart das sehr viele redundante Aufrufe.
    """
    unique_countries = df[country_txt_column].dropna().unique()

    iso3_mapping = {
        country: convert_country_to_iso3(country)
        for country in unique_countries
    }

    df["ISO3"] = df[country_txt_column].map(iso3_mapping)

    return df


def add_iso3_from_iso2(
    df: pd.DataFrame,
    iso2_column: str = "country_code",
) -> pd.DataFrame:
    unique_codes = df[iso2_column].dropna().astype(str).unique()

    iso_mapping = {
        iso2: cc.convert(
            names=iso2,
            src="ISO2",
            to="ISO3",
            not_found=None,
        )
        for iso2 in unique_codes
    }

    df["ISO3"] = df[iso2_column].map(iso_mapping)

    df["ISO3"] = df["ISO3"].replace(
        {
            "not found": pd.NA,
            "None": pd.NA,
            "": pd.NA,
        }
    )

    return df


def haversine_distance_km(
    latitude_1: pd.Series,
    longitude_1: pd.Series,
    latitude_2: pd.Series,
    longitude_2: pd.Series,
) -> pd.Series:
    """
    Berechnet die Großkreisentfernung zwischen zwei Koordinatenpaaren.
    Die Berechnung erfolgt vollständig vektorisiert.
    """
    earth_radius_km = 6371.0088

    lat1 = np.radians(pd.to_numeric(latitude_1, errors="coerce"))
    lon1 = np.radians(pd.to_numeric(longitude_1, errors="coerce"))
    lat2 = np.radians(pd.to_numeric(latitude_2, errors="coerce"))
    lon2 = np.radians(pd.to_numeric(longitude_2, errors="coerce"))

    delta_latitude = lat2 - lat1
    delta_longitude = lon2 - lon1

    a = (
        np.sin(delta_latitude / 2) ** 2
        + np.cos(lat1)
        * np.cos(lat2)
        * np.sin(delta_longitude / 2) ** 2
    )

    return 2 * earth_radius_km * np.arcsin(np.sqrt(a))


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
        missing_text = "\n".join(f"  - {path}" for path in missing_files)
        raise FileNotFoundError(
            "Folgende benötigte Dateien wurden nicht gefunden:\n"
            f"{missing_text}"
        )


# =============================================================================
# STEP 1: BUILD A COMPACT GTD CITY LIST
# =============================================================================

def build_gtd_city_list() -> pd.DataFrame:
    """
    Liest GTD chunkweise und erstellt eine kompakte Tabelle mit einer Zeile
    pro Land-Stadt-Kombination.

    Falls mehrere GTD-Ereignisse für dieselbe Stadt unterschiedliche
    Koordinaten besitzen, wird der Median verwendet.

    WICHTIG: Der Ländercode wird konsequent "ISO3" genannt (nicht
    "country_code"), um ihn klar von den ISO2-Codes aus GeoNames zu
    unterscheiden. Eine frühere Version verwendete denselben Spaltennamen
    für beide, was beim späteren Merge zu stillen Fehlmatches führte.
    """
    print("1/7: Erstelle Liste eindeutiger GTD-Städte ...")

    required_columns = [
        "country_txt",
        "city",
        "latitude",
        "longitude",
    ]

    city_chunks: list[pd.DataFrame] = []

    for chunk_number, chunk in enumerate(
        pd.read_csv(
            GTD_PATH,
            usecols=required_columns,
            chunksize=GTD_CHUNKSIZE,
            low_memory=False,
        ),
        start=1,
    ):
        chunk["city_normalized"] = chunk["city"].map(
            normalize_city_name
        )

        # Gebatchte Konvertierung: einmal pro eindeutigem Ländernamen
        # im Chunk statt einmal pro Zeile.
        chunk = add_iso3_from_country_txt(chunk, "country_txt")

        chunk["latitude"] = pd.to_numeric(
            chunk["latitude"],
            errors="coerce",
        )

        chunk["longitude"] = pd.to_numeric(
            chunk["longitude"],
            errors="coerce",
        )

        # Nicht matchbare Orte frühzeitig verwerfen.
        chunk = chunk.dropna(
            subset=[
                "country_txt",
                "ISO3",
                "city_normalized",
            ]
        )

        # Bereits innerhalb des Chunks aggregieren. Dadurch wird deutlich
        # weniger Material im Speicher gesammelt.
        chunk_summary = (
            chunk.groupby(
                [
                    "country_txt",
                    "ISO3",
                    "city_normalized",
                ],
                as_index=False,
                dropna=False,
            )
            .agg(
                gtd_city_name=("city", "first"),
                gtd_latitude=("latitude", "median"),
                gtd_longitude=("longitude", "median"),
                gtd_event_count=("city", "size"),
            )
        )

        city_chunks.append(chunk_summary)

        print(
            f"    GTD-Chunk {chunk_number:,}: "
            f"{len(chunk_summary):,} Stadt-Land-Kombinationen"
        )

    if not city_chunks:
        raise ValueError("Im GTD-Datensatz wurden keine Städte gefunden.")

    # Die Ergebnisse der einzelnen Chunks erneut zusammenfassen.
    gtd_cities = pd.concat(city_chunks, ignore_index=True)

    gtd_cities = (
        gtd_cities.groupby(
            [
                "country_txt",
                "ISO3",
                "city_normalized",
            ],
            as_index=False,
            dropna=False,
        )
        .agg(
            gtd_city_name=("gtd_city_name", "first"),
            gtd_latitude=("gtd_latitude", "median"),
            gtd_longitude=("gtd_longitude", "median"),
            gtd_event_count=("gtd_event_count", "sum"),
        )
    )

    # Stabile ID für spätere Joins und Diagnosen.
    gtd_cities.insert(
        0,
        "gtd_place_id",
        np.arange(len(gtd_cities), dtype=np.int64),
    )

    gtd_cities.to_csv(
        GTD_CITY_LIST_PATH,
        index=False,
        encoding="utf-8",
    )

    print(
        f"    {len(gtd_cities):,} eindeutige GTD-Orte gespeichert: "
        f"{GTD_CITY_LIST_PATH}"
    )

    return gtd_cities


# =============================================================================
# STEP 2: READ ONLY RELEVANT GEONAMES ALTERNATE NAMES
# =============================================================================

def read_relevant_alternate_names(
    target_city_names: set[str],
) -> pd.DataFrame:
    """
    Liest alternateNamesV2.txt chunkweise und behält nur Namen, die tatsächlich
    in der GTD-Städteliste vorkommen.

    Die Datei enthält keinen Ländercode. Der Länderfilter wird später über
    allCountries.txt angewendet.
    """
    print("2/7: Suche relevante GeoNames-Aliasnamen ...")

    relevant_chunks: list[pd.DataFrame] = []

    usecols = [
        "geonameid",
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
                "alternate_name": "string",
                "is_historic": "string",
            },
            quoting=3,
            on_bad_lines="skip",
            low_memory=False,
        ),
        start=1,
    ):
        chunk["city_normalized"] = chunk["alternate_name"].map(
            normalize_city_name
        )

        chunk = chunk.loc[
            chunk["city_normalized"].isin(target_city_names)
        ].copy()

        if not chunk.empty:
            # Historische Namen bleiben erhalten. Sie können für ältere
            # GTD-Einträge wichtig sein. Die Information wird separat
            # mitgeführt.
            relevant_chunks.append(chunk)

        print(
            f"    Alias-Chunk {chunk_number:,}: "
            f"{len(chunk):,} relevante Namen"
        )

    if not relevant_chunks:
        return pd.DataFrame(
            columns=[
                "geonameid",
                "alternate_name",
                "city_normalized",
                "is_historic",
            ]
        )

    alternate_names = pd.concat(
        relevant_chunks,
        ignore_index=True,
    )

    alternate_names = alternate_names.dropna(
        subset=["geonameid", "city_normalized"]
    )

    alternate_names = alternate_names.drop_duplicates(
        subset=["geonameid", "city_normalized"]
    )

    print(
        f"    Insgesamt {len(alternate_names):,} relevante "
        "GeoNames-Aliaszeilen gefunden."
    )

    return alternate_names


# =============================================================================
# STEP 3: READ ONLY RELEVANT POPULATED PLACES FROM ALLCOUNTRIES
# =============================================================================

def read_relevant_geonames_places_and_top3(
    target_city_names: set[str],
    target_iso3_codes: set[str],
    alternate_names: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Liest allCountries.txt genau einmal chunkweise.

    Für das GTD-Matching wird ein Ort nur behalten, wenn:
      - er ein bewohnter Ort ist (feature_class == P),
      - er in einem GTD-Land liegt,
      - und entweder sein offizieller/ASCII-Name in GTD vorkommt
        oder einer seiner Aliasnamen in GTD vorkommt.

    Parallel werden aus allen geeigneten Städten in jedem relevanten Land
    die drei bevölkerungsreichsten unterschiedlichen Städte bestimmt. Die
    Top-3-Rangfolge wird somit ausdrücklich nicht nur unter den im GTD
    vorkommenden Städten gebildet.

    GeoNames liefert Ländercodes nur als ISO2 ("country_code"). Diese
    werden hier direkt zu ISO3 konvertiert und die ISO2-Spalte danach
    verworfen, damit im weiteren Verlauf nur noch ISO3 verwendet wird
    (identisch zum Schema der GTD-Seite).
    """
    print(
        "3/7: Lade relevante GeoNames-Orte und bestimme "
        "landesweite Top-3-Städte ..."
    )

    alias_geonameids = set(
        alternate_names["geonameid"]
        .dropna()
        .astype("int64")
        .tolist()
    )

    relevant_chunks: list[pd.DataFrame] = []
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
        "admin1_code",
        "admin2_code",
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
                "admin1_code": "string",
                "admin2_code": "string",
            },
            quoting=3,
            on_bad_lines="skip",
            low_memory=False,
        ),
        start=1,
    ):
        # Zuerst stark reduzieren: nur bewohnte Orte in relevanten Ländern.
        chunk = chunk.loc[
            chunk["feature_class"].eq("P")
        ].copy()

        chunk = add_iso3_from_iso2(chunk, iso2_column="country_code")

        chunk = chunk.loc[
            chunk["ISO3"].isin(target_iso3_codes)
        ].copy()

        if chunk.empty:
            print(
                f"    GeoNames-Chunk {chunk_number:,}: "
                "0 relevante Orte"
            )
            continue

        # Die ISO2-Spalte wird nicht mehr gebraucht; ab hier zählt nur ISO3.
        chunk = chunk.drop(columns=["country_code"])

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

        # Die globalen Top 3 eines Landes müssen in jedem Fall unter den
        # lokalen Top 3 desjenigen Dateichunks liegen, in dem sie vorkommen.
        # Deshalb reichen höchstens drei Kandidaten je Land und Chunk aus.
        top3_chunk = chunk.loc[
            chunk["feature_code"].isin(TOP3_FEATURE_CODES)
            & chunk["name_normalized"].notna()
        ].copy()

        if not top3_chunk.empty:
            top3_chunk = (
                top3_chunk.sort_values(
                    ["ISO3", "population", "geonameid"],
                    ascending=[True, False, True],
                )
                # Gleichnamige GeoNames-Einträge innerhalb eines Landes
                # gelten für die Rangfolge als dieselbe Stadt.
                .drop_duplicates(
                    subset=["ISO3", "name_normalized"],
                    keep="first",
                )
                .groupby("ISO3", group_keys=False)
                .head(3)
            )

            top3_candidate_chunks.append(
                top3_chunk[
                    [
                        "ISO3",
                        "geonameid",
                        "name",
                        "asciiname",
                        "name_normalized",
                        "latitude",
                        "longitude",
                        "feature_code",
                        "population",
                    ]
                ]
            )

        direct_name_match = (
            chunk["name_normalized"].isin(target_city_names)
            | chunk["asciiname_normalized"].isin(target_city_names)
        )

        alias_match = chunk["geonameid"].isin(alias_geonameids)

        chunk = chunk.loc[
            direct_name_match | alias_match
        ].copy()

        if not chunk.empty:
            relevant_chunks.append(chunk)

        print(
            f"    GeoNames-Chunk {chunk_number:,}: "
            f"{len(chunk):,} relevante Orte"
        )

    if not relevant_chunks:
        raise ValueError(
            "Es wurden keine passenden GeoNames-Orte gefunden."
        )

    if not top3_candidate_chunks:
        raise ValueError(
            "Es konnten keine Kandidaten für die Top-3-Städte bestimmt werden."
        )

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
    )

    top3_cities = top3_cities.sort_values(
        ["ISO3", "top3_rank"]
    ).reset_index(drop=True)

    top3_cities.to_csv(
        TOP3_CITIES_PATH,
        index=False,
        encoding="utf-8",
    )

    places = pd.concat(relevant_chunks, ignore_index=True)

    # Nur nationale Hauptstädte.
    places["is_capital"] = places["feature_code"].eq("PPLC")

    places = places.drop_duplicates(subset=["geonameid"])

    top3_rank_by_geonameid = (
        top3_cities.set_index("geonameid")["top3_rank"]
    )

    places["top3_rank"] = places["geonameid"].map(
        top3_rank_by_geonameid
    ).astype("Int64")

    places["is_top3"] = places["top3_rank"].notna()

    print(
        f"    Insgesamt {len(places):,} relevante GeoNames-Orte geladen.\n"
        f"    Top-3-Referenztabelle für "
        f"{top3_cities['ISO3'].nunique():,} Länder gespeichert: "
        f"{TOP3_CITIES_PATH}"
    )

    return places, top3_cities


# =============================================================================
# STEP 4: CREATE A COMPACT NAME LOOKUP TABLE
# =============================================================================

def build_name_lookup(
    places: pd.DataFrame,
    alternate_names: pd.DataFrame,
) -> pd.DataFrame:
    """
    Erzeugt eine Long-Format-Tabelle:

        geonameid | ISO3 | city_normalized | name_source

    Jeder offizielle Name, ASCII-Name und relevante Alias wird zu einer
    möglichen Matchzeile. Der Join-Key auf der Länderseite ist durchgehend
    ISO3, passend zu `gtd_cities`.
    """
    print("4/7: Erzeuge kompakte GeoNames-Namenstabelle ...")

    common_columns = [
        "geonameid",
        "ISO3",
        "latitude",
        "longitude",
        "name",
        "feature_code",
        "population",
        "is_capital",
        "is_top3",
        "top3_rank",
        "admin1_code",
        "admin2_code",
    ]

    official_names = places[common_columns].copy()
    official_names["city_normalized"] = places["name_normalized"]
    official_names["matched_geonames_name"] = places["name"]
    official_names["name_source"] = "official"

    ascii_names = places[common_columns].copy()
    ascii_names["city_normalized"] = places["asciiname_normalized"]
    ascii_names["matched_geonames_name"] = places["asciiname"]
    ascii_names["name_source"] = "ascii"

    # Nur Aliase behalten, deren geonameid tatsächlich als relevanter,
    # bewohnter Ort in allCountries identifiziert wurde.
    alias_lookup = alternate_names.merge(
        places[common_columns],
        on="geonameid",
        how="inner",
        validate="many_to_one",
    )

    alias_lookup["matched_geonames_name"] = alias_lookup[
        "alternate_name"
    ]

    alias_lookup["name_source"] = np.where(
        alias_lookup["is_historic"].astype("string").eq("1").fillna(False),
        "historic_alias",
        "alternate",
    )

    alias_lookup = alias_lookup[
        common_columns
        + [
            "city_normalized",
            "matched_geonames_name",
            "name_source",
        ]
    ]

    name_lookup = pd.concat(
        [
            official_names,
            ascii_names,
            alias_lookup,
        ],
        ignore_index=True,
    )

    name_lookup = name_lookup.dropna(
        subset=[
            "ISO3",
            "city_normalized",
            "geonameid",
        ]
    )

    name_lookup = name_lookup.drop_duplicates(
        subset=[
            "ISO3",
            "city_normalized",
            "geonameid",
        ]
    )

    print(
        f"    Namenstabelle enthält {len(name_lookup):,} mögliche Matches."
    )

    return name_lookup


# =============================================================================
# STEP 5: MATCH GTD CITIES TO GEONAMES
# =============================================================================

def match_gtd_cities(
    gtd_cities: pd.DataFrame,
    name_lookup: pd.DataFrame,
) -> pd.DataFrame:
    """
    Matched GTD-Orte über:

        ISO3 + normalisierter Stadtname

    Mehrfachtreffer werden bevorzugt über Koordinatendistanz gelöst.
    Falls keine GTD-Koordinaten verfügbar sind, wird der bevölkerungsreichste
    Kandidat gewählt.
    """
    print("5/7: Matche GTD-Städte mit GeoNames ...")

    candidates = gtd_cities.merge(
        name_lookup,
        on=[
            "ISO3",
            "city_normalized",
        ],
        how="left",
        validate="one_to_many",
    )

    candidates["distance_km"] = haversine_distance_km(
        candidates["gtd_latitude"],
        candidates["gtd_longitude"],
        candidates["latitude"],
        candidates["longitude"],
    )

    candidates["has_distance"] = (
        candidates["distance_km"].notna()
    )

    # Anzahl unterschiedlicher GeoNames-Kandidaten pro GTD-Ort.
    candidates["candidate_count"] = (
        candidates.groupby("gtd_place_id")["geonameid"]
        .transform("nunique")
        .fillna(0)
        .astype(int)
    )

    # Sortierprinzip:
    #
    # 1. Gematchte Kandidaten vor ungematchten Zeilen.
    # 2. Kandidaten mit berechenbarer Distanz vor Kandidaten ohne Distanz.
    # 3. Kleinste Distanz.
    # 4. Größte Bevölkerung als Fallback.
    candidates["is_matched"] = candidates["geonameid"].notna()

    candidates = candidates.sort_values(
        by=[
            "gtd_place_id",
            "is_matched",
            "has_distance",
            "distance_km",
            "population",
            "geonameid",
        ],
        ascending=[
            True,
            False,
            False,
            True,
            False,
            True,
        ],
        na_position="last",
    )

    best_matches = (
        candidates.drop_duplicates(
            subset=["gtd_place_id"],
            keep="first",
        )
        .copy()
    )

    best_matches["match_status"] = "unmatched"

    unique_match = (
        best_matches["geonameid"].notna()
        & best_matches["candidate_count"].eq(1)
    )

    distance_match = (
        best_matches["geonameid"].notna()
        & best_matches["candidate_count"].gt(1)
        & best_matches["distance_km"].notna()
    )

    population_fallback = (
        best_matches["geonameid"].notna()
        & best_matches["candidate_count"].gt(1)
        & best_matches["distance_km"].isna()
    )

    best_matches.loc[
        unique_match,
        "match_status",
    ] = "matched_unique_name"

    best_matches.loc[
        distance_match,
        "match_status",
    ] = "matched_by_distance"

    best_matches.loc[
        population_fallback,
        "match_status",
    ] = "matched_by_population_fallback"

    best_matches["distance_warning"] = (
        best_matches["distance_km"].gt(DISTANCE_WARNING_KM)
    ).fillna(False)

    output_columns = [
        "gtd_place_id",
        "country_txt",
        "ISO3",
        "gtd_city_name",
        "city_normalized",
        "gtd_latitude",
        "gtd_longitude",
        "gtd_event_count",
        "geonameid",
        "name",
        "matched_geonames_name",
        "name_source",
        "latitude",
        "longitude",
        "distance_km",
        "distance_warning",
        "feature_code",
        "is_capital",
        "is_top3",
        "top3_rank",
        "population",
        "admin1_code",
        "admin2_code",
        "candidate_count",
        "match_status",
    ]

    best_matches = best_matches[output_columns].rename(
        columns={
            "name": "geonames_name",
            "latitude": "geonames_latitude",
            "longitude": "geonames_longitude",
            "population": "geonames_population",
        }
    )

    best_matches.to_csv(
        CITY_MATCHES_PATH,
        index=False,
        encoding="utf-8",
    )

    matched_count = best_matches["geonameid"].notna().sum()
    unmatched_count = best_matches["geonameid"].isna().sum()

    print(
        f"    Gematcht:   {matched_count:,}\n"
        f"    Ungematcht: {unmatched_count:,}\n"
        f"    Diagnosetabelle: {CITY_MATCHES_PATH}"
    )

    return best_matches


# =============================================================================
# STEP 6: WRITE FULL GTD DATASET WITH GEONAMES VARIABLES
# =============================================================================

def write_matched_gtd(
    city_matches: pd.DataFrame,
) -> None:
    """
    Liest den vollständigen GTD-Datensatz erneut chunkweise, fügt die
    GeoNames-Informationen an und schreibt das Ergebnis inkrementell als CSV.

    Dadurch muss der vollständige GTD-Datensatz nie gleichzeitig im Speicher
    liegen.
    """
    print("6/7: Schreibe vollständigen gematchten GTD-Datensatz ...")

    lookup_columns = [
        "ISO3",
        "city_normalized",
        "geonameid",
        "geonames_name",
        "matched_geonames_name",
        "name_source",
        "geonames_latitude",
        "geonames_longitude",
        "distance_km",
        "distance_warning",
        "feature_code",
        "is_capital",
        "is_top3",
        "top3_rank",
        "geonames_population",
        "admin1_code",
        "admin2_code",
        "candidate_count",
        "match_status",
    ]

    city_lookup = city_matches[lookup_columns].copy()

    # Sicherheit: genau ein Lookup-Ergebnis je Land und normalisiertem Ort.
    duplicated_keys = city_lookup.duplicated(
        subset=["ISO3", "city_normalized"],
        keep=False,
    )

    if duplicated_keys.any():
        examples = city_lookup.loc[
            duplicated_keys,
            ["ISO3", "city_normalized"],
        ].head()

        raise ValueError(
            "Die finale Lookup-Tabelle enthält doppelte Schlüssel.\n"
            f"Beispiele:\n{examples}"
        )

    # Alte Outputdatei entfernen, damit keine Ergebnisse angehängt werden.
    if MATCHED_GTD_PATH.exists():
        MATCHED_GTD_PATH.unlink()

    first_chunk = True

    for chunk_number, chunk in enumerate(
        pd.read_csv(
            GTD_PATH,
            chunksize=GTD_CHUNKSIZE,
            low_memory=False,
        ),
        start=1,
    ):
        chunk["city_normalized"] = chunk["city"].map(
            normalize_city_name
        )

        # Gebatchte Konvertierung, identisch zu Schritt 1.
        chunk = add_iso3_from_country_txt(chunk, "country_txt")

        chunk = chunk.merge(
            city_lookup,
            on=[
                "ISO3",
                "city_normalized",
            ],
            how="left",
            validate="many_to_one",
        )

        # Nicht matchbare und nicht gematchte Orte bleiben separat
        # identifizierbar, werden für die spätere räumliche Aggregation aber
        # ausdrücklich als außerhalb von Hauptstadt und Top 3 behandelt.
        chunk["city_unknown"] = chunk["geonameid"].isna()

        invalid_city = chunk["city_normalized"].isna()

        chunk.loc[
            invalid_city & chunk["match_status"].isna(),
            "match_status",
        ] = "invalid_or_missing_city"

        chunk.loc[
            ~invalid_city & chunk["match_status"].isna(),
            "match_status",
        ] = "unmatched"

        for flag_column in ["is_capital", "is_top3"]:
            chunk[flag_column] = (
                chunk[flag_column]
                .astype("boolean")
                .fillna(False)
                .astype(bool)
            )

        # GTD verwendet imonth == 0 für einen unbekannten Monat.
        # Solche Beobachtungen erhalten kein künstliches Quartal.
        if "imonth" in chunk.columns:
            month = pd.to_numeric(
                chunk["imonth"],
                errors="coerce",
            )

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

        print(
            f"    GTD-Chunk {chunk_number:,}: "
            f"{len(chunk):,} Zeilen geschrieben"
        )

    print(f"    Ergebnis gespeichert: {MATCHED_GTD_PATH}")


# =============================================================================
# STEP 7: PRINT DIAGNOSTICS
# =============================================================================

def print_match_diagnostics(
    city_matches: pd.DataFrame,
    top3_cities: pd.DataFrame,
    target_iso3_codes: set[str],
) -> None:
    print("7/7: Match-Diagnose")

    print("\nMatchstatus:")
    print(
        city_matches["match_status"]
        .value_counts(dropna=False)
        .to_string()
    )

    total_events = city_matches["gtd_event_count"].sum()

    matched_events = city_matches.loc[
        city_matches["geonameid"].notna(),
        "gtd_event_count",
    ].sum()

    event_match_rate = (
        matched_events / total_events
        if total_events
        else np.nan
    )

    print(
        "\nNach Zahl der GTD-Ereignisse gewichtete Matchquote: "
        f"{event_match_rate:.2%}"
    )

    warning_matches = city_matches.loc[
        city_matches["distance_warning"]
    ].sort_values(
        "distance_km",
        ascending=False,
    )

    print(
        f"\nMatches mit mehr als {DISTANCE_WARNING_KM:.0f} km Abstand: "
        f"{len(warning_matches):,}"
    )

    if not warning_matches.empty:
        print(
            warning_matches[
                [
                    "country_txt",
                    "gtd_city_name",
                    "geonames_name",
                    "distance_km",
                    "candidate_count",
                ]
            ]
            .head(20)
            .to_string(index=False)
        )

    unmatched = city_matches.loc[
        city_matches["geonameid"].isna()
    ].sort_values(
        "gtd_event_count",
        ascending=False,
    )

    print(f"\nNicht gematchte GTD-Orte: {len(unmatched):,}")

    if not unmatched.empty:
        print(
            unmatched[
                [
                    "country_txt",
                    "gtd_city_name",
                    "gtd_event_count",
                ]
            ]
            .head(30)
            .to_string(index=False)
        )

    top3_counts = top3_cities.groupby("ISO3").size()

    if top3_counts.gt(3).any():
        invalid_counts = top3_counts.loc[top3_counts.gt(3)]
        raise ValueError(
            "Für mindestens ein Land wurden mehr als drei Top-3-Städte "
            f"erzeugt:\n{invalid_counts.to_string()}"
        )

    duplicated_top3_names = top3_cities.duplicated(
        subset=["ISO3", "name_normalized"],
        keep=False,
    )

    if duplicated_top3_names.any():
        examples = top3_cities.loc[
            duplicated_top3_names,
            ["ISO3", "name", "name_normalized", "top3_rank"],
        ].head(20)

        raise ValueError(
            "Die Top-3-Referenztabelle enthält doppelte Städtenamen "
            f"innerhalb eines Landes:\n{examples}"
        )

    countries_with_three = int(top3_counts.eq(3).sum())
    countries_with_fewer = sorted(
        target_iso3_codes - set(top3_counts.loc[top3_counts.eq(3)].index)
    )

    print(
        "\nTop-3-Diagnose:\n"
        f"    Länder mit genau drei Referenzstädten: "
        f"{countries_with_three:,}\n"
        f"    Länder mit weniger als drei Referenzstädten: "
        f"{len(countries_with_fewer):,}"
    )

    if countries_with_fewer:
        print(
            "    Betroffene ISO3-Codes: "
            + ", ".join(countries_with_fewer)
        )

    validation_names = {
        "DEU": "berlin",
        "MEX": "mexico city",
        "USA": "new york city",
    }

    print("\nPlausibilitätsfälle in der Top-3-Referenz:")

    for iso3, city_name in validation_names.items():
        if iso3 not in target_iso3_codes:
            continue

        case = top3_cities.loc[
            top3_cities["ISO3"].eq(iso3)
            & top3_cities["name_normalized"].eq(city_name)
        ]

        status = (
            f"ja, Rang {int(case.iloc[0]['top3_rank'])}"
            if not case.empty
            else "nein"
        )

        print(f"    {iso3} / {city_name}: {status}")


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def main() -> None:
    check_required_files()

    gtd_cities = build_gtd_city_list()

    target_city_names = set(
        gtd_cities["city_normalized"]
        .dropna()
        .astype(str)
        .unique()
    )

    target_iso3_codes = set(
        gtd_cities["ISO3"]
        .dropna()
        .astype(str)
        .unique()
    )

    print(
        f"\nSuche nach {len(target_city_names):,} unterschiedlichen "
        f"normalisierten Namen in {len(target_iso3_codes):,} Ländern.\n"
    )

    alternate_names = read_relevant_alternate_names(
        target_city_names=target_city_names,
    )

    places, top3_cities = read_relevant_geonames_places_and_top3(
        target_city_names=target_city_names,
        target_iso3_codes=target_iso3_codes,
        alternate_names=alternate_names,
    )

    name_lookup = build_name_lookup(
        places=places,
        alternate_names=alternate_names,
    )

    city_matches = match_gtd_cities(
        gtd_cities=gtd_cities,
        name_lookup=name_lookup,
    )

    write_matched_gtd(
        city_matches=city_matches,
    )

    print_match_diagnostics(
        city_matches=city_matches,
        top3_cities=top3_cities,
        target_iso3_codes=target_iso3_codes,
    )


if __name__ == "__main__":
    main()
