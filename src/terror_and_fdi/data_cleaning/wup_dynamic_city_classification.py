from __future__ import annotations

"""
Historische Hauptstadt- und Top-3-Klassifikation für GTD 1993–2020.

Voraussetzung
-------------
Zuerst `geonames_cleaning.py` ausführen. Dessen Output enthält bereits:
ISO3, normalisierte/zugeordnete Städtenamen sowie die statischen GeoNames-
Variablen `is_capital` und `is_top3`.

Dieses Skript:
1. lädt die UN-WUP-2025-Städtedaten automatisch herunter (oder nutzt eine
   bereits vorhandene lokale Datei);
2. bildet für jedes Land und Jahr 1993–2020 eine WUP-Rangfolge;
3. klassifiziert GTD-Ereignisse dynamisch und erzeugt Robustheitsvarianten;
4. korrigiert eindeutig datierbare Hauptstadtwechsel;
5. schreibt Diagnose-, Wechsel-, Grenzfall- und Match-Review-Dateien.

Die UN-WUP-Daten werden nicht in den GTD-Output kopiert. Der Output enthält nur
die für die Klassifikation und Replikation nötigen Variablen.
"""

import argparse
import gzip
import hashlib
import math
import re
import shutil
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from terror_and_fdi.config import INTERIM, RAW


# =============================================================================
# CONFIGURATION
# =============================================================================

START_YEAR = 1993
END_YEAR = 2020
FIXED_REFERENCE_YEAR = 2000
CURRENT_REFERENCE_YEAR = 2020

# Rang 4 gilt als Grenzfall, wenn seine Bevölkerung mindestens 95 % der
# Bevölkerung von Rang 3 beträgt. Zusätzlich werden 1-%- und 10-%-Marker
# gespeichert, damit die Schwelle in Robustheitsanalysen geändert werden kann.
BORDERLINE_GAP_PCT = 5.0
TINY_GAP_PCT = 1.0
CLOSE_GAP_PCT = 10.0

# Koordinaten-Matching ist nur eine Robustheitsvariante, nie die Hauptvariante.
COORD_MAX_DISTANCE_KM = 25.0
COORD_MIN_MARGIN_KM = 5.0

GTD_CHUNKSIZE = 200_000
WUP_READ_CHUNKSIZE = 250_000
DOWNLOAD_TIMEOUT_SECONDS = 120

GEONAMES_OUTPUT_DIR = INTERIM / "geonames"
GTD_INPUT_PATH = GEONAMES_OUTPUT_DIR / "gtd_with_city_groups.csv"
GEONAMES_REFERENCE_PATH = (
    GEONAMES_OUTPUT_DIR / "geonames_capital_top3_reference_cities.csv"
)

WUP_DIR = RAW / "un_wup"
WUP_FILENAME = (
    "WUP2025-DB-DEGURBA-Cities-Population-Surface-Data.csv.gz"
)
WUP_PATH = WUP_DIR / WUP_FILENAME
WUP_URL = (
    "https://population.un.org/wup/assets/Download/Cities/"
    + WUP_FILENAME
)

OUTPUT_DIR = INTERIM / "wup_city_classification"
CLASSIFIED_GTD_PATH = OUTPUT_DIR / "gtd_with_dynamic_city_groups.csv"
YEARLY_REFERENCE_PATH = OUTPUT_DIR / "wup_top4_country_year.csv"
COUNTRY_YEAR_DIAGNOSTICS_PATH = (
    OUTPUT_DIR / "wup_top3_country_year_diagnostics.csv"
)
CITY_HISTORY_PATH = OUTPUT_DIR / "wup_top3_city_history.csv"
CHANGE_YEARS_PATH = OUTPUT_DIR / "wup_top3_change_years.csv"
BORDERLINE_YEARS_PATH = OUTPUT_DIR / "wup_top3_borderline_years.csv"
AMBIGUOUS_ALIASES_PATH = OUTPUT_DIR / "wup_ambiguous_city_aliases.csv"
UNMATCHED_GTD_PATH = OUTPUT_DIR / "gtd_unmatched_city_review.csv"
CAPITAL_HISTORY_PATH = OUTPUT_DIR / "historical_capital_overrides.csv"
CODEBOOK_PATH = OUTPUT_DIR / "classification_codebook.csv"
SUMMARY_PATH = OUTPUT_DIR / "classification_summary.md"

INVALID_CITY_NAMES = {
    "",
    "unknown",
    "unkown",
    "not applicable",
    "n a",
    "na",
    "none",
    "unspecified",
    "multiple",
    "various",
}

# Zusätzliche Schreibweisen, die weder aus dem WUP-Namen noch aus Klammer-/
# Trennzeichenvarianten zuverlässig entstehen. Schlüssel und Werte werden
# normalisiert. Der Zielwert muss eine Schreibweise eines WUP-Zentrums sein.
WUP_CITY_NAME_OVERRIDES = {
    ("COD", "Kinshasa (Leopoldville)"): "Kinshasa",
    ("IND", "New Delhi"): "New Delhi",
    ("MEX", "Mexico D.F."): "Mexico City",
    ("MMR", "Rangoon"): "Yangon",
    ("RUS", "Moscow"): "Moskva",
    ("UKR", "Kiev"): "Kyiv",
    ("USA", "New York"): "New York City",
    ("VNM", "Saigon"): "Ho Chi Minh City",
}


# =============================================================================
# HISTORICAL CAPITAL RULES
# =============================================================================

@dataclass(frozen=True)
class CapitalInterval:
    iso3: str
    city: str
    aliases: tuple[str, ...]
    valid_from: date
    valid_to: date
    role: str
    source_note: str
    source_url: str


# Nur Länder, bei denen die statische heutige Klassifikation im Zeitraum
# 1993–2020 eindeutig zeitlich falsch wäre, werden vollständig überschrieben.
# Für alle anderen Länder bleibt der geprüfte GeoNames-Status bestehen.
CAPITAL_HISTORY: tuple[CapitalInterval, ...] = (
    CapitalInterval(
        "KAZ",
        "Almaty",
        ("Almaty", "Alma-Ata", "Alma Ata"),
        date(1993, 1, 1),
        date(1997, 12, 9),
        "national_capital",
        "Capital before transfer to Astana",
        "https://qazinform.com/news/19-years-ago-astana-became-capital-city-of-kazakhstan_a2960886",
    ),
    CapitalInterval(
        "KAZ",
        "Astana",
        ("Astana", "Akmola", "Nur-Sultan", "Nur Sultan"),
        date(1997, 12, 10),
        date(END_YEAR, 12, 31),
        "national_capital",
        "Capital from 10 December 1997; later names retained as aliases",
        "https://qazinform.com/news/19-years-ago-astana-became-capital-city-of-kazakhstan_a2960886",
    ),
    CapitalInterval(
        "MMR",
        "Yangon",
        ("Yangon", "Rangoon"),
        date(1993, 1, 1),
        date(2005, 11, 5),
        "national_capital",
        "Capital before administrative transfer to Naypyidaw",
        "https://unterm.un.org/unterm2/en/view/97753e65-3597-4af3-accd-ac29446db9d3",
    ),
    CapitalInterval(
        "MMR",
        "Naypyidaw",
        ("Naypyidaw", "Nay Pyi Taw", "Naypyitaw"),
        date(2005, 11, 6),
        date(END_YEAR, 12, 31),
        "national_capital",
        "Capital from administrative transfer in November 2005",
        "https://unterm.un.org/unterm2/en/view/97753e65-3597-4af3-accd-ac29446db9d3",
    ),
    CapitalInterval(
        "BDI",
        "Bujumbura",
        ("Bujumbura",),
        date(1993, 1, 1),
        date(2019, 1, 15),
        "national_capital",
        "Capital until parliamentary approval of the transfer to Gitega",
        "https://www.theeastafrican.co.ke/tea/news/east-africa/burundi-names-gitega-as-new-capital-1409084",
    ),
    CapitalInterval(
        "BDI",
        "Gitega",
        ("Gitega",),
        date(2019, 1, 16),
        date(END_YEAR, 12, 31),
        "national_capital",
        "Political capital from parliamentary approval on 16 January 2019",
        "https://www.theeastafrican.co.ke/tea/news/east-africa/burundi-names-gitega-as-new-capital-1409084",
    ),
    CapitalInterval(
        "PLW",
        "Koror",
        ("Koror",),
        date(1993, 1, 1),
        date(2006, 10, 6),
        "national_capital",
        "Capital before transfer to Ngerulmud",
        "https://www.palaugov.pw/wp-content/uploads/2016/03/2012-ROP-Statistical-Yearbook.pdf",
    ),
    CapitalInterval(
        "PLW",
        "Ngerulmud",
        ("Ngerulmud", "Melekeok"),
        date(2006, 10, 7),
        date(END_YEAR, 12, 31),
        "national_capital",
        "Capital from 7 October 2006",
        "https://www.palaugov.pw/wp-content/uploads/2016/03/2012-ROP-Statistical-Yearbook.pdf",
    ),
    CapitalInterval(
        "GNQ",
        "Malabo",
        ("Malabo",),
        date(1993, 1, 1),
        date(END_YEAR, 12, 31),
        "national_capital",
        "Malabo throughout the GTD analysis period",
        "https://population.un.org/wup/downloads",
    ),
)

CAPITAL_OVERRIDE_COUNTRIES = frozenset(
    interval.iso3 for interval in CAPITAL_HISTORY
)


# =============================================================================
# GENERAL HELPERS
# =============================================================================

def normalize_city_name(value: object) -> str | pd.NA:
    """Normalize a city name for conservative exact matching."""
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


def atomic_to_csv(df: pd.DataFrame, path: Path) -> None:
    """Write a CSV atomically so an old valid result survives failures."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}.tmp{path.suffix}")
    df.to_csv(temporary, index=False, encoding="utf-8")
    temporary.replace(path)


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def validate_gzip_csv(path: Path) -> None:
    """Fail early on HTML error pages or truncated downloads."""
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(path)

    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            header = handle.readline()
    except (OSError, EOFError) as exc:
        raise ValueError(f"Ungültige oder beschädigte GZIP-Datei: {path}") from exc

    required = {"ISO3_Code", "City_Code", "City_Name", "Year", "Pop"}
    columns = set(header.rstrip("\n").split(","))
    missing = required - columns
    if missing:
        raise ValueError(
            f"UN-WUP-Datei hat nicht das erwartete Schema. Fehlend: {missing}"
        )


def download_wup_data(force: bool = False) -> Path:
    """
    Download the official UN WUP bulk city CSV.

    Existing valid files are reused. A partial download never replaces a
    previous valid file.
    """
    WUP_DIR.mkdir(parents=True, exist_ok=True)

    if WUP_PATH.exists() and not force:
        validate_gzip_csv(WUP_PATH)
        print(f"UN-WUP-Datei bereits vorhanden: {WUP_PATH}")
        return WUP_PATH

    temporary = WUP_PATH.with_suffix(WUP_PATH.suffix + ".part")
    if temporary.exists():
        temporary.unlink()

    request = urllib.request.Request(
        WUP_URL,
        headers={"User-Agent": "Mozilla/5.0 (academic-research-script)"},
    )

    print(f"Lade UN-WUP-2025-Städtedaten herunter:\n    {WUP_URL}")
    try:
        with urllib.request.urlopen(
            request,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        ) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if temporary.exists():
            temporary.unlink()
        raise RuntimeError(
            "Automatischer UN-WUP-Download fehlgeschlagen. Lade die Datei "
            f"manuell von {WUP_URL} herunter und speichere sie als "
            f"{WUP_PATH}."
        ) from exc

    validate_gzip_csv(temporary)
    temporary.replace(WUP_PATH)
    print(
        f"Download abgeschlossen: {WUP_PATH} "
        f"({WUP_PATH.stat().st_size / 1024**2:.1f} MiB)"
    )
    return WUP_PATH


# =============================================================================
# READ AND RANK UN WUP
# =============================================================================

WUP_USECOLS = [
    "ISO3_Code",
    "City_Code",
    "City_Name",
    "Capital",
    "Year",
    "PWCent_Latitude",
    "PWCent_Longitude",
    "Pop_plausibility",
    "Pop",
]


def read_wup_period(path: Path) -> pd.DataFrame:
    print(f"Lese UN-WUP-Daten für {START_YEAR}–{END_YEAR} ...")
    pieces: list[pd.DataFrame] = []

    for chunk_number, chunk in enumerate(
        pd.read_csv(
            path,
            usecols=WUP_USECOLS,
            chunksize=WUP_READ_CHUNKSIZE,
            low_memory=False,
        ),
        start=1,
    ):
        year = pd.to_numeric(chunk["Year"], errors="coerce")
        selected = chunk.loc[year.between(START_YEAR, END_YEAR)].copy()
        if not selected.empty:
            pieces.append(selected)
        print(
            f"    WUP-Chunk {chunk_number}: "
            f"{len(selected):,} relevante Zeilen"
        )

    if not pieces:
        raise ValueError("Keine WUP-Zeilen im Analysezeitraum gefunden.")

    wup = pd.concat(pieces, ignore_index=True)
    wup["ISO3_Code"] = wup["ISO3_Code"].astype("string").str.upper()
    wup["City_Code"] = pd.to_numeric(
        wup["City_Code"], errors="raise"
    ).astype("int64")
    wup["Year"] = pd.to_numeric(wup["Year"], errors="raise").astype("int16")
    wup["Pop"] = pd.to_numeric(wup["Pop"], errors="coerce")
    wup["PWCent_Latitude"] = pd.to_numeric(
        wup["PWCent_Latitude"], errors="coerce"
    )
    wup["PWCent_Longitude"] = pd.to_numeric(
        wup["PWCent_Longitude"], errors="coerce"
    )

    if wup.duplicated(["ISO3_Code", "Year", "City_Code"]).any():
        duplicate = wup.loc[
            wup.duplicated(
                ["ISO3_Code", "Year", "City_Code"], keep=False
            ),
            ["ISO3_Code", "Year", "City_Code", "City_Name"],
        ]
        raise ValueError(
            "Doppelte WUP-Stadtjahre gefunden:\n"
            + duplicate.head(20).to_string(index=False)
        )

    return wup


def build_yearly_rankings(
    wup: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return top-4 rows and one country-year diagnostic row."""
    ranked = wup.sort_values(
        ["ISO3_Code", "Year", "Pop", "City_Code"],
        ascending=[True, True, False, True],
        na_position="last",
    ).copy()
    ranked["population_rank"] = (
        ranked.groupby(["ISO3_Code", "Year"]).cumcount() + 1
    ).astype("int16")

    counts = (
        ranked.groupby(["ISO3_Code", "Year"])["City_Code"]
        .nunique()
        .rename("wup_city_count")
    )

    top4 = ranked.loc[ranked["population_rank"].le(4)].copy()
    population_wide = top4.pivot(
        index=["ISO3_Code", "Year"],
        columns="population_rank",
        values="Pop",
    ).rename(
        columns={
            1: "population_rank1_thousands",
            2: "population_rank2_thousands",
            3: "population_rank3_thousands",
            4: "population_rank4_thousands",
        }
    )
    name_wide = top4.pivot(
        index=["ISO3_Code", "Year"],
        columns="population_rank",
        values="City_Name",
    ).rename(
        columns={
            1: "city_rank1",
            2: "city_rank2",
            3: "city_rank3",
            4: "city_rank4",
        }
    )
    code_wide = top4.pivot(
        index=["ISO3_Code", "Year"],
        columns="population_rank",
        values="City_Code",
    ).rename(
        columns={
            1: "city_code_rank1",
            2: "city_code_rank2",
            3: "city_code_rank3",
            4: "city_code_rank4",
        }
    )
    plausibility_wide = top4.pivot(
        index=["ISO3_Code", "Year"],
        columns="population_rank",
        values="Pop_plausibility",
    ).rename(
        columns={
            1: "plausibility_rank1",
            2: "plausibility_rank2",
            3: "plausibility_rank3",
            4: "plausibility_rank4",
        }
    )

    diagnostics = (
        counts.to_frame()
        .join(population_wide)
        .join(name_wide)
        .join(code_wide)
        .join(plausibility_wide)
        .reset_index()
    )
    diagnostics["top3_coverage_complete"] = diagnostics[
        "wup_city_count"
    ].ge(3)
    diagnostics["rank4_available"] = diagnostics["city_code_rank4"].notna()
    diagnostics["population_gap_3_4_thousands"] = (
        diagnostics["population_rank3_thousands"]
        - diagnostics["population_rank4_thousands"]
    )
    diagnostics["population_gap_3_4_pct_of_rank3"] = (
        100
        * diagnostics["population_gap_3_4_thousands"]
        / diagnostics["population_rank3_thousands"]
    )

    gap = diagnostics["population_gap_3_4_pct_of_rank3"]
    diagnostics["top3_gap_tiny_1pct"] = gap.le(TINY_GAP_PCT).fillna(False)
    diagnostics["top3_borderline_5pct"] = gap.le(
        BORDERLINE_GAP_PCT
    ).fillna(False)
    diagnostics["top3_gap_close_10pct"] = gap.le(
        CLOSE_GAP_PCT
    ).fillna(False)
    top3_plausibility_columns = [
        "plausibility_rank1",
        "plausibility_rank2",
        "plausibility_rank3",
    ]
    diagnostics["top3_any_low_plausibility"] = diagnostics[
        top3_plausibility_columns
    ].eq("Low").any(axis=1)
    diagnostics["top3_any_below_high_plausibility"] = ~diagnostics[
        top3_plausibility_columns
    ].eq("High").all(axis=1)

    top4 = top4.merge(
        diagnostics[
            [
                "ISO3_Code",
                "Year",
                "wup_city_count",
                "top3_coverage_complete",
                "population_gap_3_4_thousands",
                "population_gap_3_4_pct_of_rank3",
                "top3_gap_tiny_1pct",
                "top3_borderline_5pct",
                "top3_gap_close_10pct",
                "top3_any_low_plausibility",
                "top3_any_below_high_plausibility",
            ]
        ],
        on=["ISO3_Code", "Year"],
        how="left",
        validate="many_to_one",
    )
    return top4, diagnostics


def add_change_diagnostics(
    top4: pd.DataFrame,
    diagnostics: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Add annual membership changes and city-level membership histories."""
    top3 = top4.loc[top4["population_rank"].le(3)].copy()

    membership = (
        top3.sort_values(["ISO3_Code", "Year", "population_rank"])
        .groupby(["ISO3_Code", "Year"])["City_Code"]
        .agg(lambda values: tuple(map(int, values)))
        .rename("top3_ordered_city_codes")
        .reset_index()
        .sort_values(["ISO3_Code", "Year"])
    )
    membership["top3_city_codes"] = membership[
        "top3_ordered_city_codes"
    ].map(lambda values: tuple(sorted(values)))
    membership["previous_top3_city_codes"] = membership.groupby(
        "ISO3_Code"
    )["top3_city_codes"].shift()
    membership["previous_top3_ordered_city_codes"] = membership.groupby(
        "ISO3_Code"
    )["top3_ordered_city_codes"].shift()

    def entered(row: pd.Series) -> tuple[int, ...]:
        previous = row["previous_top3_city_codes"]
        if not isinstance(previous, tuple):
            return tuple()
        return tuple(sorted(set(row["top3_city_codes"]) - set(previous)))

    def exited(row: pd.Series) -> tuple[int, ...]:
        previous = row["previous_top3_city_codes"]
        if not isinstance(previous, tuple):
            return tuple()
        return tuple(sorted(set(previous) - set(row["top3_city_codes"])))

    membership["entered_city_codes"] = membership.apply(entered, axis=1)
    membership["exited_city_codes"] = membership.apply(exited, axis=1)
    membership["top3_membership_changed"] = (
        membership["entered_city_codes"].map(len).gt(0)
        | membership["exited_city_codes"].map(len).gt(0)
    )
    membership.loc[
        membership["previous_top3_city_codes"].isna(),
        "top3_membership_changed",
    ] = False
    membership["top3_order_changed"] = membership[
        "top3_ordered_city_codes"
    ].ne(membership["previous_top3_ordered_city_codes"])
    membership.loc[
        membership["previous_top3_ordered_city_codes"].isna(),
        "top3_order_changed",
    ] = False

    diagnostics = diagnostics.merge(
        membership[
            [
                "ISO3_Code",
                "Year",
                "top3_city_codes",
                "top3_ordered_city_codes",
                "entered_city_codes",
                "exited_city_codes",
                "top3_membership_changed",
                "top3_order_changed",
            ]
        ],
        on=["ISO3_Code", "Year"],
        how="left",
        validate="one_to_one",
    )

    country_change_count = (
        diagnostics.groupby("ISO3_Code")["top3_membership_changed"]
        .sum()
        .astype(int)
        .rename("country_top3_change_years_count")
    )
    diagnostics = diagnostics.merge(
        country_change_count,
        on="ISO3_Code",
        how="left",
        validate="many_to_one",
    )
    diagnostics["country_frequent_top3_changes"] = diagnostics[
        "country_top3_change_years_count"
    ].ge(3)
    country_order_change_count = (
        diagnostics.groupby("ISO3_Code")["top3_order_changed"]
        .sum()
        .astype(int)
        .rename("country_top3_order_change_years_count")
    )
    diagnostics = diagnostics.merge(
        country_order_change_count,
        on="ISO3_Code",
        how="left",
        validate="many_to_one",
    )
    diagnostics["country_frequent_top3_order_changes"] = diagnostics[
        "country_top3_order_change_years_count"
    ].ge(3)

    city_base = (
        top4.groupby(
            ["ISO3_Code", "City_Code", "City_Name"],
            as_index=False,
        )
        .agg(
            first_year_observed=("Year", "min"),
            last_year_observed=("Year", "max"),
            best_rank=("population_rank", "min"),
            worst_top4_rank=("population_rank", "max"),
        )
    )
    membership_by_country_year = {
        (row.ISO3_Code, int(row.Year)): set(row.top3_city_codes)
        for row in membership.itertuples(index=False)
    }
    country_years = (
        membership.groupby("ISO3_Code")["Year"]
        .agg(lambda values: sorted(map(int, values)))
        .to_dict()
    )

    history_rows: list[dict[str, object]] = []
    for city in city_base.itertuples(index=False):
        years = country_years.get(city.ISO3_Code, [])
        sequence = [
            int(city.City_Code)
            in membership_by_country_year.get((city.ISO3_Code, year), set())
            for year in years
        ]
        transitions = sum(
            current != previous
            for previous, current in zip(sequence, sequence[1:])
        )
        history_rows.append(
            {
                **city._asdict(),
                "years_in_top3": int(sum(sequence)),
                "top3_membership_transitions": int(transitions),
            }
        )

    city_history = pd.DataFrame(history_rows)
    city_history["ever_top3_1993_2020"] = city_history[
        "years_in_top3"
    ].gt(0)
    city_history["frequent_top3_switches"] = city_history[
        "top3_membership_transitions"
    ].ge(3)

    change_years = diagnostics.loc[
        diagnostics["top3_membership_changed"]
        | diagnostics["top3_borderline_5pct"],
        :,
    ].copy()
    return diagnostics, city_history, change_years


# =============================================================================
# CITY NAME LOOKUP
# =============================================================================

def city_name_aliases(city_name: str) -> set[str]:
    """Derive conservative aliases from UN-WUP labels."""
    aliases = {city_name}

    # Parenthetical translations: "Kābul (Kabul)" -> both parts.
    for content in re.findall(r"\(([^()]*)\)", city_name):
        aliases.add(content)
    without_parentheses = re.sub(r"\s*\([^()]*\)", "", city_name).strip()
    if without_parentheses:
        aliases.add(without_parentheses)

    # WUP explicitly uses these separators for bilingual names or merged
    # urban centres. Each component is a valid GTD spelling for the centre.
    for separator in (" / ", "/", " - ", " – "):
        if separator in city_name:
            aliases.update(part.strip() for part in city_name.split(separator))

    return {
        normalized
        for alias in aliases
        if pd.notna(normalized := normalize_city_name(alias))
    }


def build_wup_alias_lookup(
    top4: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build one time-invariant alias lookup for all cities ever reaching top 4.

    Aliases pointing to multiple WUP centres within one country are excluded
    and fully documented.
    """
    cities = (
        top4[
            [
                "ISO3_Code",
                "City_Code",
                "City_Name",
                "PWCent_Latitude",
                "PWCent_Longitude",
            ]
        ]
        .drop_duplicates(["ISO3_Code", "City_Code"])
        .copy()
    )

    rows: list[dict[str, object]] = []
    for city in cities.itertuples(index=False):
        for alias in city_name_aliases(city.City_Name):
            rows.append(
                {
                    "ISO3": city.ISO3_Code,
                    "city_alias_normalized": alias,
                    "wup_city_code": city.City_Code,
                    "wup_city_name": city.City_Name,
                    "wup_city_latitude": city.PWCent_Latitude,
                    "wup_city_longitude": city.PWCent_Longitude,
                    "wup_alias_source": "derived_from_wup_name",
                }
            )

    lookup = pd.DataFrame(rows).drop_duplicates()

    for (iso3, source_alias), target_name in WUP_CITY_NAME_OVERRIDES.items():
        source = normalize_city_name(source_alias)
        target = normalize_city_name(target_name)
        target_rows = lookup.loc[
            lookup["ISO3"].eq(iso3)
            & lookup["city_alias_normalized"].eq(target)
        ].drop_duplicates("wup_city_code")

        if len(target_rows) == 1 and pd.notna(source):
            row = target_rows.iloc[0].to_dict()
            row["city_alias_normalized"] = source
            row["wup_alias_source"] = "manual_override"
            lookup = pd.concat(
                [lookup, pd.DataFrame([row])],
                ignore_index=True,
            )

    ambiguous_keys = (
        lookup.groupby(["ISO3", "city_alias_normalized"])["wup_city_code"]
        .nunique()
        .loc[lambda values: values.gt(1)]
        .reset_index()
        .drop(columns="wup_city_code")
    )
    ambiguous = lookup.merge(
        ambiguous_keys,
        on=["ISO3", "city_alias_normalized"],
        how="inner",
    ).sort_values(["ISO3", "city_alias_normalized", "wup_city_code"])

    if not ambiguous_keys.empty:
        lookup = lookup.merge(
            ambiguous_keys.assign(_ambiguous=True),
            on=["ISO3", "city_alias_normalized"],
            how="left",
        )
        lookup = lookup.loc[lookup["_ambiguous"].isna()].drop(
            columns="_ambiguous"
        )

    lookup = (
        lookup.sort_values(
            ["ISO3", "city_alias_normalized", "wup_alias_source"],
            key=lambda series: series.map(
                {"manual_override": 0, "derived_from_wup_name": 1}
            )
            if series.name == "wup_alias_source"
            else series,
        )
        .drop_duplicates(["ISO3", "city_alias_normalized"])
        .reset_index(drop=True)
    )

    if lookup.duplicated(["ISO3", "city_alias_normalized"]).any():
        raise RuntimeError("WUP-Alias-Lookup ist nicht eindeutig.")
    return lookup, ambiguous


# =============================================================================
# CAPITAL CLASSIFICATION
# =============================================================================

def capital_history_frame() -> pd.DataFrame:
    rows = []
    for interval in CAPITAL_HISTORY:
        rows.append(
            {
                "ISO3": interval.iso3,
                "capital_city": interval.city,
                "aliases": " | ".join(interval.aliases),
                "valid_from": interval.valid_from.isoformat(),
                "valid_to": interval.valid_to.isoformat(),
                "role": interval.role,
                "source_note": interval.source_note,
                "source_url": interval.source_url,
            }
        )
    return pd.DataFrame(rows)


def build_event_dates(chunk: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Construct the best available date and flag incomplete dates.

    Unknown month/day values (0) are imputed to 1 July / 15th solely for
    classifying transition years and remain explicitly flagged.
    """
    year = pd.to_numeric(chunk["iyear"], errors="coerce")
    month = pd.to_numeric(chunk.get("imonth"), errors="coerce")
    day = pd.to_numeric(chunk.get("iday"), errors="coerce")

    month_valid = month.between(1, 12)
    month_filled = month.where(month_valid, 7)

    day_valid = day.between(1, 31)
    day_filled = day.where(day_valid & month_valid, 15)

    dates = pd.to_datetime(
        {
            "year": year,
            "month": month_filled,
            "day": day_filled,
        },
        errors="coerce",
    )
    precision = pd.Series("day", index=chunk.index, dtype="string")
    precision.loc[~day_valid & month_valid] = "month"
    precision.loc[~month_valid] = "year"
    precision.loc[year.isna()] = "missing"

    # Fange kalendarisch unmögliche, aber numerisch plausible GTD-Tage ab
    # (z. B. 31. Februar), ohne den Hauptstadtstatus des ganzen Ereignisses
    # auf fehlend zu setzen.
    invalid_calendar_day = (
        dates.isna() & year.notna() & month_valid
    )
    if invalid_calendar_day.any():
        fallback = pd.to_datetime(
            {
                "year": year.loc[invalid_calendar_day],
                "month": month_filled.loc[invalid_calendar_day],
                "day": 15,
            },
            errors="coerce",
        )
        dates.loc[invalid_calendar_day] = fallback
        precision.loc[invalid_calendar_day] = "month"

    return dates, precision


def apply_historical_capitals(chunk: pd.DataFrame) -> pd.DataFrame:
    if "is_capital" not in chunk.columns:
        raise ValueError(
            "Im GTD-Input fehlt `is_capital`. Zuerst geonames_cleaning.py "
            "ausführen."
        )

    chunk["is_capital_geonames_current"] = (
        chunk["is_capital"].astype("boolean").fillna(False).astype(bool)
    )
    chunk["is_capital_dynamic"] = chunk["is_capital_geonames_current"]
    chunk["capital_dynamic_source"] = "geonames_current_no_known_change"

    event_dates, date_precision = build_event_dates(chunk)
    chunk["event_date_for_capital"] = event_dates
    chunk["capital_date_precision"] = date_precision
    chunk["capital_transition_year_ambiguous"] = False

    raw_normalized = chunk["city"].map(normalize_city_name)
    reference_normalized = (
        chunk["reference_city_name"].map(normalize_city_name)
        if "reference_city_name" in chunk.columns
        else pd.Series(pd.NA, index=chunk.index, dtype="string")
    )

    for iso3 in CAPITAL_OVERRIDE_COUNTRIES:
        country_mask = chunk["ISO3"].eq(iso3)
        chunk.loc[country_mask, "is_capital_dynamic"] = False
        chunk.loc[
            country_mask, "capital_dynamic_source"
        ] = "historical_interval_no_match"

    for interval in CAPITAL_HISTORY:
        alias_set = {
            alias
            for value in interval.aliases
            if pd.notna(alias := normalize_city_name(value))
        }
        name_matches = raw_normalized.isin(alias_set) | reference_normalized.isin(
            alias_set
        )
        interval_mask = (
            chunk["ISO3"].eq(interval.iso3)
            & name_matches
            & event_dates.between(
                pd.Timestamp(interval.valid_from),
                pd.Timestamp(interval.valid_to),
                inclusive="both",
            )
        )
        chunk.loc[interval_mask, "is_capital_dynamic"] = True
        chunk.loc[
            interval_mask, "capital_dynamic_source"
        ] = "historical_interval_match"

        transition_years = {interval.valid_from.year, interval.valid_to.year}
        ambiguity_mask = (
            chunk["ISO3"].eq(interval.iso3)
            & name_matches
            & chunk["iyear"].isin(transition_years)
            & date_precision.ne("day")
        )
        chunk.loc[
            ambiguity_mask, "capital_transition_year_ambiguous"
        ] = True

    return chunk


# =============================================================================
# EVENT MATCHING AND CLASSIFICATION
# =============================================================================

def haversine_vectorized(
    lat1: pd.Series,
    lon1: pd.Series,
    lat2: pd.Series,
    lon2: pd.Series,
) -> pd.Series:
    lat1r = np.radians(pd.to_numeric(lat1, errors="coerce"))
    lon1r = np.radians(pd.to_numeric(lon1, errors="coerce"))
    lat2r = np.radians(pd.to_numeric(lat2, errors="coerce"))
    lon2r = np.radians(pd.to_numeric(lon2, errors="coerce"))
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    )
    return pd.Series(
        2 * 6371.0088 * np.arcsin(np.sqrt(a)),
        index=lat1.index,
    )


def match_wup_city_names(
    chunk: pd.DataFrame,
    alias_lookup: pd.DataFrame,
) -> pd.DataFrame:
    """Match GTD names first, then the prior GeoNames reference name."""
    chunk["gtd_city_normalized"] = chunk["city"].map(normalize_city_name)
    chunk["wup_match_name"] = chunk["gtd_city_normalized"]
    chunk["wup_match_input_source"] = "gtd_city"

    if "reference_city_name" in chunk.columns:
        reference_normalized = chunk["reference_city_name"].map(
            normalize_city_name
        )
    else:
        reference_normalized = pd.Series(
            pd.NA, index=chunk.index, dtype="string"
        )

    first = chunk.merge(
        alias_lookup,
        left_on=["ISO3", "wup_match_name"],
        right_on=["ISO3", "city_alias_normalized"],
        how="left",
        validate="many_to_one",
    )

    needs_second = first["wup_city_code"].isna() & reference_normalized.notna()
    if needs_second.any():
        second_input = chunk.loc[
            needs_second,
            ["ISO3"],
        ].copy()
        second_input["wup_match_name"] = reference_normalized.loc[needs_second]
        second_input["_original_index"] = second_input.index
        second = second_input.merge(
            alias_lookup,
            left_on=["ISO3", "wup_match_name"],
            right_on=["ISO3", "city_alias_normalized"],
            how="left",
            validate="many_to_one",
        ).set_index("_original_index")

        matched_second = second["wup_city_code"].notna()
        target_index = second.index[matched_second]
        for column in [
            "wup_city_code",
            "wup_city_name",
            "wup_city_latitude",
            "wup_city_longitude",
            "wup_alias_source",
            "city_alias_normalized",
        ]:
            first.loc[target_index, column] = second.loc[
                target_index, column
            ].to_numpy()
        first.loc[
            target_index, "wup_match_input_source"
        ] = "geonames_reference_city"
        first.loc[target_index, "wup_match_name"] = second.loc[
            target_index, "wup_match_name"
        ].to_numpy()

    first["wup_name_match"] = first["wup_city_code"].notna()
    first["wup_match_method"] = "unmatched"
    first.loc[first["wup_name_match"], "wup_match_method"] = (
        "name_"
        + first.loc[first["wup_name_match"], "wup_match_input_source"]
        + "_"
        + first.loc[first["wup_name_match"], "wup_alias_source"].astype(str)
    )
    return first


def add_coordinate_robustness_match(
    chunk: pd.DataFrame,
    top4: pd.DataFrame,
) -> pd.DataFrame:
    """
    Find the nearest annual top-4 centre for unmatched events.

    The result is separate from the primary name-based match. A match is
    considered confident only inside the distance threshold and with a clear
    margin to the second-nearest candidate.
    """
    chunk["wup_coord_city_code"] = pd.Series(
        pd.NA, index=chunk.index, dtype="Int64"
    )
    chunk["wup_coord_city_name"] = pd.Series(
        pd.NA, index=chunk.index, dtype="string"
    )
    chunk["wup_coord_distance_km"] = pd.Series(
        pd.NA, index=chunk.index, dtype="Float64"
    )
    chunk["wup_coord_second_distance_km"] = pd.Series(
        pd.NA, index=chunk.index, dtype="Float64"
    )
    chunk["wup_coord_match_confident"] = False

    if not {"latitude", "longitude"}.issubset(chunk.columns):
        return chunk

    eligible = (
        ~chunk["wup_name_match"]
        & pd.to_numeric(chunk["latitude"], errors="coerce").notna()
        & pd.to_numeric(chunk["longitude"], errors="coerce").notna()
    )
    if not eligible.any():
        return chunk

    candidates = top4[
        [
            "ISO3_Code",
            "Year",
            "City_Code",
            "City_Name",
            "PWCent_Latitude",
            "PWCent_Longitude",
        ]
    ].rename(columns={"ISO3_Code": "ISO3", "Year": "iyear"})

    events = chunk.loc[
        eligible,
        ["ISO3", "iyear", "latitude", "longitude"],
    ].copy()
    events["_event_index"] = events.index
    pairs = events.merge(
        candidates,
        on=["ISO3", "iyear"],
        how="left",
        validate="many_to_many",
    )
    pairs["_distance_km"] = haversine_vectorized(
        pairs["latitude"],
        pairs["longitude"],
        pairs["PWCent_Latitude"],
        pairs["PWCent_Longitude"],
    )
    pairs = pairs.sort_values(["_event_index", "_distance_km"])
    pairs["_distance_order"] = pairs.groupby("_event_index").cumcount() + 1

    nearest = pairs.loc[pairs["_distance_order"].eq(1)].set_index(
        "_event_index"
    )
    second = (
        pairs.loc[pairs["_distance_order"].eq(2)]
        .set_index("_event_index")["_distance_km"]
        .rename("_second_distance_km")
    )
    nearest = nearest.join(second)

    target_index = nearest.index
    chunk.loc[target_index, "wup_coord_city_code"] = pd.array(
        nearest["City_Code"], dtype="Int64"
    )
    chunk.loc[target_index, "wup_coord_city_name"] = nearest[
        "City_Name"
    ].astype("string").to_numpy()
    chunk.loc[target_index, "wup_coord_distance_km"] = pd.array(
        nearest["_distance_km"], dtype="Float64"
    )
    chunk.loc[target_index, "wup_coord_second_distance_km"] = pd.array(
        nearest["_second_distance_km"], dtype="Float64"
    )

    margin = nearest["_second_distance_km"] - nearest["_distance_km"]
    confident = (
        nearest["_distance_km"].le(COORD_MAX_DISTANCE_KM)
        & (margin.ge(COORD_MIN_MARGIN_KM) | margin.isna())
    )
    chunk.loc[
        nearest.index[confident], "wup_coord_match_confident"
    ] = True
    return chunk


def classification_lookup(top4: pd.DataFrame) -> pd.DataFrame:
    return top4[
        [
            "ISO3_Code",
            "Year",
            "City_Code",
            "City_Name",
            "population_rank",
            "Pop",
            "Pop_plausibility",
            "top3_coverage_complete",
            "population_gap_3_4_thousands",
            "population_gap_3_4_pct_of_rank3",
            "top3_gap_tiny_1pct",
            "top3_borderline_5pct",
            "top3_gap_close_10pct",
        ]
    ].rename(
        columns={
            "ISO3_Code": "ISO3",
            "Year": "iyear",
            "City_Code": "wup_city_code",
            "City_Name": "wup_ranked_city_name",
            "Pop": "wup_city_population_thousands",
            "Pop_plausibility": "wup_population_plausibility",
        }
    )


def add_top3_classifications(
    chunk: pd.DataFrame,
    top4: pd.DataFrame,
    diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    lookup = classification_lookup(top4)
    chunk = chunk.merge(
        lookup,
        on=["ISO3", "iyear", "wup_city_code"],
        how="left",
        validate="many_to_one",
    )

    country_year = diagnostics[
        [
            "ISO3_Code",
            "Year",
            "wup_city_count",
            "top3_coverage_complete",
            "population_gap_3_4_thousands",
            "population_gap_3_4_pct_of_rank3",
            "top3_gap_tiny_1pct",
            "top3_borderline_5pct",
            "top3_gap_close_10pct",
            "top3_any_low_plausibility",
            "top3_any_below_high_plausibility",
            "top3_membership_changed",
            "top3_order_changed",
            "country_top3_change_years_count",
            "country_frequent_top3_changes",
            "country_top3_order_change_years_count",
            "country_frequent_top3_order_changes",
        ]
    ].rename(columns={"ISO3_Code": "ISO3", "Year": "iyear"})

    # Country-year information must also exist for events whose city did not
    # match a top-4 centre.
    event_columns = set(chunk.columns)
    for column in [
        "wup_city_count",
        "top3_coverage_complete",
        "population_gap_3_4_thousands",
        "population_gap_3_4_pct_of_rank3",
        "top3_gap_tiny_1pct",
        "top3_borderline_5pct",
        "top3_gap_close_10pct",
        "top3_any_low_plausibility",
        "top3_any_below_high_plausibility",
        "top3_membership_changed",
        "top3_order_changed",
        "country_top3_change_years_count",
        "country_frequent_top3_changes",
        "country_top3_order_change_years_count",
        "country_frequent_top3_order_changes",
    ]:
        if column in event_columns:
            chunk = chunk.drop(columns=column)

    chunk = chunk.merge(
        country_year,
        on=["ISO3", "iyear"],
        how="left",
        validate="many_to_one",
    )

    rank = pd.to_numeric(chunk["population_rank"], errors="coerce")
    chunk["is_top3_dynamic_wup"] = rank.le(3).fillna(False)
    chunk["is_top4_dynamic_wup"] = rank.le(4).fillna(False)
    chunk["is_major_city_top4_if_borderline"] = (
        chunk["is_top3_dynamic_wup"]
        | (
            rank.eq(4)
            & chunk["top3_borderline_5pct"].fillna(False)
        )
    )
    chunk["top3_dynamic_robust_sample_eligible"] = (
        chunk["top3_coverage_complete"].fillna(False)
        & ~chunk["top3_borderline_5pct"].fillna(False)
    )

    if "is_top3" not in chunk.columns:
        raise ValueError(
            "Im GTD-Input fehlt `is_top3`. Zuerst geonames_cleaning.py "
            "ausführen."
        )
    chunk["is_top3_geonames_current"] = (
        chunk["is_top3"].astype("boolean").fillna(False).astype(bool)
    )

    complete = chunk["top3_coverage_complete"].fillna(False)
    chunk["is_top3_main"] = np.where(
        complete,
        chunk["is_top3_dynamic_wup"],
        chunk["is_top3_geonames_current"],
    ).astype(bool)
    chunk["is_outside_top3_main"] = ~chunk["is_top3_main"]
    chunk["is_outside_top3_dynamic_wup"] = ~chunk[
        "is_top3_dynamic_wup"
    ]
    chunk["top3_main_source"] = np.where(
        complete,
        "wup_dynamic_complete",
        "geonames_static_fallback_incomplete_wup",
    )

    fixed_sets = {}
    for reference_year, label in [
        (FIXED_REFERENCE_YEAR, "is_top3_2000_fixed"),
        (CURRENT_REFERENCE_YEAR, "is_top3_2020_fixed_wup"),
    ]:
        codes = (
            top4.loc[
                top4["Year"].eq(reference_year)
                & top4["population_rank"].le(3)
            ]
            .groupby("ISO3_Code")["City_Code"]
            .agg(set)
            .to_dict()
        )
        fixed_sets[label] = codes
        chunk[label] = [
            pd.notna(city_code)
            and int(city_code) in codes.get(iso3, set())
            for iso3, city_code in zip(
                chunk["ISO3"], chunk["wup_city_code"]
            )
        ]

    ever_codes = (
        top4.loc[top4["population_rank"].le(3)]
        .groupby("ISO3_Code")["City_Code"]
        .agg(set)
        .to_dict()
    )
    chunk["ever_top3_1993_2020"] = [
        pd.notna(city_code)
        and int(city_code) in ever_codes.get(iso3, set())
        for iso3, city_code in zip(chunk["ISO3"], chunk["wup_city_code"])
    ]

    dynamic_coord_codes = chunk["wup_city_code"].copy()
    use_coord = (
        dynamic_coord_codes.isna()
        & chunk["wup_coord_match_confident"]
    )
    dynamic_coord_codes.loc[use_coord] = chunk.loc[
        use_coord, "wup_coord_city_code"
    ]
    annual_top3_sets = (
        top4.loc[top4["population_rank"].le(3)]
        .groupby(["ISO3_Code", "Year"])["City_Code"]
        .agg(set)
        .to_dict()
    )
    chunk["is_top3_dynamic_with_coord_robustness"] = [
        pd.notna(city_code)
        and int(city_code) in annual_top3_sets.get((iso3, int(year)), set())
        for iso3, year, city_code in zip(
            chunk["ISO3"], chunk["iyear"], dynamic_coord_codes
        )
    ]

    return chunk


# =============================================================================
# OUTPUT DIAGNOSTICS AND DOCUMENTATION
# =============================================================================

CODEBOOK_ROWS = [
    (
        "is_capital_dynamic",
        "bool",
        "Historischer Hauptstadtstatus; bekannte Wechsel werden nach "
        "Ereignisdatum klassifiziert, sonst geprüfter GeoNames-Status.",
    ),
    (
        "is_capital_geonames_current",
        "bool",
        "Statischer heutiger/prüfungsbasierter Hauptstadtstatus aus dem "
        "vorherigen GeoNames-Skript.",
    ),
    (
        "is_outside_capital_dynamic",
        "bool",
        "Komplement von `is_capital_dynamic` für die spätere Aggregation.",
    ),
    (
        "capital_transition_year_ambiguous",
        "bool",
        "Ereignis liegt in einem Hauptstadtwechseljahr, aber Monat oder Tag "
        "ist unbekannt.",
    ),
    (
        "is_top3_dynamic_wup",
        "bool",
        "Reine jährliche UN-WUP-Klassifikation; positiv bei WUP-Rang 1–3.",
    ),
    (
        "is_top3_main",
        "bool",
        "Empfohlene Hauptvariable: dynamisches WUP bei mindestens drei "
        "WUP-Städten, sonst statischer GeoNames-Rückfall.",
    ),
    (
        "is_outside_top3_main",
        "bool",
        "Komplement von `is_top3_main` für die spätere Aggregation.",
    ),
    (
        "top3_main_source",
        "string",
        "Zeigt für jede Beobachtung, ob WUP oder GeoNames-Rückfall verwendet "
        "wurde.",
    ),
    (
        "is_top3_2000_fixed",
        "bool",
        "Robustheit: für alle Jahre feste WUP-Top-3 des Jahres 2000.",
    ),
    (
        "is_top3_2020_fixed_wup",
        "bool",
        "Robustheit: für alle Jahre feste WUP-Top-3 des Jahres 2020.",
    ),
    (
        "is_top3_geonames_current",
        "bool",
        "Robustheit: bisherige statische GeoNames-Klassifikation.",
    ),
    (
        "ever_top3_1993_2020",
        "bool",
        "Stadt gehörte in mindestens einem Analysejahr zur WUP-Top-3.",
    ),
    (
        "is_major_city_top4_if_borderline",
        "bool",
        "Rang 1–3 sowie Rang 4, wenn Abstand zwischen Rang 3 und 4 höchstens "
        f"{BORDERLINE_GAP_PCT:g} % beträgt.",
    ),
    (
        "is_top3_dynamic_with_coord_robustness",
        "bool",
        "Dynamische Top-3 mit zusätzlichem konservativem "
        "Koordinaten-Matching für nicht per Name erkannte Ereignisse.",
    ),
    (
        "top3_coverage_complete",
        "bool",
        "Mindestens drei veröffentlichte WUP-Städte im Land-Jahr vorhanden.",
    ),
    (
        "population_gap_3_4_pct_of_rank3",
        "float",
        "Bevölkerungsabstand Rang 3 minus Rang 4 in Prozent von Rang 3.",
    ),
    (
        "top3_borderline_5pct",
        "bool",
        "Abstand zwischen Rang 3 und Rang 4 höchstens 5 %.",
    ),
    (
        "top3_membership_changed",
        "bool",
        "Mindestens ein Ein- oder Austritt aus der Top 3 gegenüber Vorjahr.",
    ),
    (
        "top3_order_changed",
        "bool",
        "Die Reihenfolge der drei größten WUP-Städte änderte sich gegenüber "
        "dem Vorjahr; die Mitgliedschaft kann dabei gleich bleiben.",
    ),
    (
        "country_frequent_top3_changes",
        "bool",
        "Land besitzt mindestens drei jährliche Top-3-Mitgliedschaftswechsel.",
    ),
    (
        "top3_any_low_plausibility",
        "bool",
        "Mindestens eine der drei WUP-Bevölkerungsschätzungen ist als `Low` "
        "plausibility gekennzeichnet.",
    ),
    (
        "wup_name_match",
        "bool",
        "GTD-Stadtname oder vorherige GeoNames-Referenz wurde eindeutig einem "
        "WUP-Zentrum zugeordnet.",
    ),
    (
        "wup_coord_match_confident",
        "bool",
        "Unmatched event is within the coordinate threshold and clearly "
        "closer to the nearest than to the second-nearest top-4 centre.",
    ),
]


def write_reference_outputs(
    top4: pd.DataFrame,
    diagnostics: pd.DataFrame,
    city_history: pd.DataFrame,
    change_years: pd.DataFrame,
    ambiguous_aliases: pd.DataFrame,
) -> None:
    output_top4 = top4.sort_values(
        ["ISO3_Code", "Year", "population_rank"]
    )
    atomic_to_csv(output_top4, YEARLY_REFERENCE_PATH)
    atomic_to_csv(
        diagnostics.sort_values(["ISO3_Code", "Year"]),
        COUNTRY_YEAR_DIAGNOSTICS_PATH,
    )
    atomic_to_csv(
        city_history.sort_values(
            ["ISO3_Code", "best_rank", "City_Name"]
        ),
        CITY_HISTORY_PATH,
    )
    atomic_to_csv(
        change_years.sort_values(["ISO3_Code", "Year"]),
        CHANGE_YEARS_PATH,
    )
    atomic_to_csv(
        diagnostics.loc[
            diagnostics["top3_borderline_5pct"]
        ].sort_values(
            [
                "population_gap_3_4_pct_of_rank3",
                "ISO3_Code",
                "Year",
            ]
        ),
        BORDERLINE_YEARS_PATH,
    )
    atomic_to_csv(ambiguous_aliases, AMBIGUOUS_ALIASES_PATH)
    atomic_to_csv(capital_history_frame(), CAPITAL_HISTORY_PATH)
    atomic_to_csv(
        pd.DataFrame(
            CODEBOOK_ROWS,
            columns=["variable", "type", "description"],
        ),
        CODEBOOK_PATH,
    )


def update_unmatched_counts(
    accumulator: dict[tuple[str, str], int],
    chunk: pd.DataFrame,
) -> None:
    unmatched = chunk.loc[
        ~chunk["wup_name_match"]
        & chunk["gtd_city_normalized"].notna(),
        ["ISO3", "gtd_city_normalized"],
    ]
    counts = unmatched.value_counts()
    for key, value in counts.items():
        accumulator[(str(key[0]), str(key[1]))] = (
            accumulator.get((str(key[0]), str(key[1])), 0) + int(value)
        )


def write_classified_gtd(
    alias_lookup: pd.DataFrame,
    top4: pd.DataFrame,
    diagnostics: pd.DataFrame,
) -> dict[str, int]:
    print("Klassifiziere GTD-Ereignisse ...")
    temporary = CLASSIFIED_GTD_PATH.with_name(
        f"{CLASSIFIED_GTD_PATH.stem}.tmp{CLASSIFIED_GTD_PATH.suffix}"
    )
    if temporary.exists():
        temporary.unlink()

    totals = {
        "input_rows": 0,
        "output_rows": 0,
        "wup_name_matches": 0,
        "wup_coord_confident": 0,
        "capital_dynamic": 0,
        "top3_dynamic_wup": 0,
        "top3_main": 0,
        "fallback_rows": 0,
        "borderline_rows": 0,
    }
    unmatched_counts: dict[tuple[str, str], int] = {}
    first = True

    for chunk_number, chunk in enumerate(
        pd.read_csv(
            GTD_INPUT_PATH,
            chunksize=GTD_CHUNKSIZE,
            low_memory=False,
        ),
        start=1,
    ):
        # pandas behält bei chunkweisem Lesen den globalen Zeilenindex bei.
        # Ein lokaler RangeIndex verhindert Fehl-Ausrichtungen bei den zwei
        # aufeinanderfolgenden Namens-Matching-Schritten.
        chunk = chunk.reset_index(drop=True)
        input_rows = len(chunk)
        totals["input_rows"] += input_rows

        required = {"ISO3", "iyear", "city", "is_capital", "is_top3"}
        missing = required - set(chunk.columns)
        if missing:
            raise ValueError(
                f"Im GeoNames-GTD-Output fehlen Spalten: {sorted(missing)}"
            )

        chunk["ISO3"] = chunk["ISO3"].astype("string").str.upper()
        chunk["iyear"] = pd.to_numeric(
            chunk["iyear"], errors="raise"
        ).astype("int16")

        chunk = apply_historical_capitals(chunk)
        chunk["is_outside_capital_dynamic"] = ~chunk[
            "is_capital_dynamic"
        ]
        chunk = match_wup_city_names(chunk, alias_lookup)
        chunk = add_coordinate_robustness_match(chunk, top4)
        chunk = add_top3_classifications(chunk, top4, diagnostics)
        update_unmatched_counts(unmatched_counts, chunk)

        if len(chunk) != input_rows:
            raise RuntimeError(
                "Die Ereigniszahl hat sich bei der Klassifikation verändert."
            )

        chunk.to_csv(
            temporary,
            mode="w" if first else "a",
            header=first,
            index=False,
            encoding="utf-8",
        )
        first = False

        totals["output_rows"] += len(chunk)
        totals["wup_name_matches"] += int(chunk["wup_name_match"].sum())
        totals["wup_coord_confident"] += int(
            chunk["wup_coord_match_confident"].sum()
        )
        totals["capital_dynamic"] += int(
            chunk["is_capital_dynamic"].sum()
        )
        totals["top3_dynamic_wup"] += int(
            chunk["is_top3_dynamic_wup"].sum()
        )
        totals["top3_main"] += int(chunk["is_top3_main"].sum())
        totals["fallback_rows"] += int(
            chunk["top3_main_source"]
            .eq("geonames_static_fallback_incomplete_wup")
            .sum()
        )
        totals["borderline_rows"] += int(
            chunk["top3_borderline_5pct"].fillna(False).sum()
        )
        print(f"    GTD-Chunk {chunk_number}: {len(chunk):,} Zeilen")

    if first:
        raise ValueError("GTD-Input enthält keine Datenzeilen.")
    if totals["input_rows"] != totals["output_rows"]:
        raise RuntimeError("GTD-Zeilenzahl ist nicht erhalten geblieben.")

    temporary.replace(CLASSIFIED_GTD_PATH)

    unmatched = pd.DataFrame(
        [
            {
                "ISO3": iso3,
                "gtd_city_normalized": city,
                "event_count": count,
            }
            for (iso3, city), count in unmatched_counts.items()
        ]
    )
    if not unmatched.empty:
        unmatched = unmatched.sort_values(
            ["event_count", "ISO3", "gtd_city_normalized"],
            ascending=[False, True, True],
        )
    atomic_to_csv(unmatched, UNMATCHED_GTD_PATH)
    return totals


def write_summary(
    totals: dict[str, int],
    wup_path: Path,
    wup: pd.DataFrame,
    diagnostics: pd.DataFrame,
    city_history: pd.DataFrame,
    ambiguous_aliases: pd.DataFrame,
) -> None:
    n = totals["input_rows"]

    def pct(value: int) -> str:
        return f"{100 * value / n:.2f}%" if n else "n/a"

    incomplete = diagnostics.loc[~diagnostics["top3_coverage_complete"]]
    borderline = diagnostics.loc[diagnostics["top3_borderline_5pct"]]
    frequent_countries = (
        diagnostics.loc[
            diagnostics["country_frequent_top3_changes"],
            "ISO3_Code",
        ]
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    frequent_order_countries = (
        diagnostics.loc[
            diagnostics["country_frequent_top3_order_changes"],
            "ISO3_Code",
        ]
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    frequent_cities = city_history.loc[
        city_history["frequent_top3_switches"]
    ]
    low_plausibility = diagnostics.loc[
        diagnostics["top3_any_low_plausibility"]
    ]

    lines = [
        "# Übersicht der historischen Stadtklassifikation",
        "",
        f"Analysezeitraum: {START_YEAR}–{END_YEAR}",
        "",
        "## Daten und Reproduzierbarkeit",
        "",
        "- Quelle: United Nations, World Urbanization Prospects 2025, "
        "DEGURBA Cities bulk CSV.",
        f"- Lokale Quelldatei: `{wup_path}`",
        f"- SHA-256: `{sha256_file(wup_path)}`",
        f"- Eingelesene WUP-Stadtjahre: {len(wup):,}",
        f"- Unterscheidbare WUP-Städte: {wup['City_Code'].nunique():,}",
        "",
        "## GTD-Klassifikation",
        "",
        f"- GTD-Ereignisse: {n:,}",
        f"- Eindeutige WUP-Namensmatches: "
        f"{totals['wup_name_matches']:,} ({pct(totals['wup_name_matches'])})",
        f"- Zusätzliche sichere Koordinatenmatches (nur Robustheit): "
        f"{totals['wup_coord_confident']:,} "
        f"({pct(totals['wup_coord_confident'])})",
        f"- Dynamische Hauptstadt-Ereignisse: "
        f"{totals['capital_dynamic']:,} ({pct(totals['capital_dynamic'])})",
        f"- Reine dynamische WUP-Top-3-Ereignisse: "
        f"{totals['top3_dynamic_wup']:,} "
        f"({pct(totals['top3_dynamic_wup'])})",
        f"- Empfohlene Hauptklassifikation `is_top3_main`: "
        f"{totals['top3_main']:,} ({pct(totals['top3_main'])})",
        f"- Beobachtungen mit statischem GeoNames-Rückfall: "
        f"{totals['fallback_rows']:,} ({pct(totals['fallback_rows'])})",
        "",
        "## Abdeckung und Grenzfälle",
        "",
        f"- Land-Jahre insgesamt: {len(diagnostics):,}",
        f"- Land-Jahre mit weniger als drei veröffentlichten WUP-Städten: "
        f"{len(incomplete):,}",
        f"- Betroffene Länder/Gebiete: "
        f"{incomplete['ISO3_Code'].nunique():,}",
        f"- Land-Jahre mit höchstens {BORDERLINE_GAP_PCT:g} % Abstand "
        f"zwischen Rang 3 und 4: {len(borderline):,}",
        f"- Land-Jahre mit mindestens einer als `Low` markierten "
        f"Top-3-Schätzung: {len(low_plausibility):,}",
        f"- Ereignisse in solchen Grenzfall-Land-Jahren: "
        f"{totals['borderline_rows']:,} ({pct(totals['borderline_rows'])})",
        "",
        "## Wechsel",
        "",
        f"- Länder mit mindestens drei Top-3-Wechseljahren: "
        f"{len(frequent_countries):,}",
        "- ISO3 dieser Länder: "
        + (", ".join(frequent_countries) if frequent_countries else "keine"),
        f"- Länder mit mindestens drei Änderungen der Top-3-Reihenfolge: "
        f"{len(frequent_order_countries):,}",
        "- ISO3 dieser Länder: "
        + (
            ", ".join(frequent_order_countries)
            if frequent_order_countries
            else "keine"
        ),
        f"- Städte mit mindestens drei Ein-/Austritten: "
        f"{len(frequent_cities):,}",
        "",
        "## Empfohlene Verwendung",
        "",
        "1. Hauptanalyse: `is_capital_dynamic` und `is_top3_main`.",
        "2. Saubere WUP-Teilstichprobe: `is_top3_dynamic_wup`, aber nur "
        "`top3_coverage_complete == True`.",
        "3. Grenzfallrobustheit: Land-Jahre mit "
        "`top3_borderline_5pct == True` ausschließen oder "
        "`is_major_city_top4_if_borderline` verwenden.",
        "4. Zeitrobustheit: `is_top3_2000_fixed`, "
        "`is_top3_2020_fixed_wup`, `is_top3_geonames_current` und "
        "`ever_top3_1993_2020` vergleichen.",
        "5. Koordinatenvariante nur als Robustheitsprüfung verwenden.",
        "",
        "## Wichtige Interpretationsgrenzen",
        "",
        "- WUP veröffentlicht in einzelnen kleinen Ländern weniger als drei "
        "Städte; der Rückfall ist deshalb ausdrücklich markiert.",
        "- WUP misst harmonisierte urbane Zentren. Ein WUP-Zentrum kann mehrere "
        "administrative Städte umfassen.",
        "- Ein geringer Abstand zwischen Rang 3 und 4 ist Mess- und "
        "Rangunsicherheit, nicht automatisch ein echter Strukturbruch.",
        f"- {len(ambiguous_aliases):,} mehrdeutige WUP-Aliaszeilen wurden "
        "nicht automatisch gematcht.",
        "- Historische Hauptstadtintervalle überschreiben nur klar "
        "datierbare Wechsel; alle Annahmen stehen in "
        "`historical_capital_overrides.csv`.",
        "",
        "## Ausgabedateien",
        "",
        f"- `{CLASSIFIED_GTD_PATH.name}`: Ereignisdatensatz",
        f"- `{YEARLY_REFERENCE_PATH.name}`: jährliche WUP-Ränge 1–4",
        f"- `{COUNTRY_YEAR_DIAGNOSTICS_PATH.name}`: Abdeckung, Abstände, Wechsel",
        f"- `{BORDERLINE_YEARS_PATH.name}`: nur knappe Rang-3/4-Fälle",
        f"- `{CHANGE_YEARS_PATH.name}`: Wechsel- und Grenzfalljahre",
        f"- `{CITY_HISTORY_PATH.name}`: Stadtverläufe und häufige Wechsel",
        f"- `{UNMATCHED_GTD_PATH.name}`: häufige nicht erkannte GTD-Namen",
        f"- `{AMBIGUOUS_ALIASES_PATH.name}`: ausgeschlossene Mehrdeutigkeiten",
        f"- `{CAPITAL_HISTORY_PATH.name}`: Hauptstadtintervalle",
        f"- `{CODEBOOK_PATH.name}`: Variablenübersicht",
        "",
    ]

    temporary = SUMMARY_PATH.with_name(
        f"{SUMMARY_PATH.stem}.tmp{SUMMARY_PATH.suffix}"
    )
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(SUMMARY_PATH)


# =============================================================================
# VALIDATION AND CLI
# =============================================================================

def check_inputs() -> None:
    if not GTD_INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Fehlender GeoNames-GTD-Output: {GTD_INPUT_PATH}\n"
            "Zuerst geonames_cleaning.py ausführen."
        )
    if not GEONAMES_REFERENCE_PATH.exists():
        print(
            "Hinweis: Die GeoNames-Referenzdatei wurde nicht gefunden. "
            "Entscheidend ist, dass der GTD-Input die Spalten is_top3 und "
            "is_capital enthält."
        )


def validate_results(
    top4: pd.DataFrame,
    diagnostics: pd.DataFrame,
    totals: dict[str, int],
) -> None:
    if (top4["population_rank"] > 4).any():
        raise AssertionError("Top-4-Datei enthält einen Rang > 4.")
    if top4.duplicated(["ISO3_Code", "Year", "population_rank"]).any():
        raise AssertionError("Doppelter Rang innerhalb eines Land-Jahres.")
    if totals["input_rows"] != totals["output_rows"]:
        raise AssertionError("GTD-Zeilenzahl nicht erhalten.")
    if (
        diagnostics["top3_borderline_5pct"]
        & ~diagnostics["rank4_available"]
    ).any():
        raise AssertionError("Grenzfall ohne Rang 4.")


def run_pipeline(force_download: bool = False) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    check_inputs()
    wup_path = download_wup_data(force=force_download)
    wup = read_wup_period(wup_path)
    top4, diagnostics = build_yearly_rankings(wup)
    diagnostics, city_history, change_years = add_change_diagnostics(
        top4, diagnostics
    )
    alias_lookup, ambiguous_aliases = build_wup_alias_lookup(top4)

    write_reference_outputs(
        top4,
        diagnostics,
        city_history,
        change_years,
        ambiguous_aliases,
    )
    totals = write_classified_gtd(alias_lookup, top4, diagnostics)
    validate_results(top4, diagnostics, totals)
    write_summary(
        totals,
        wup_path,
        wup,
        diagnostics,
        city_history,
        ambiguous_aliases,
    )

    print("\nKlassifikation erfolgreich abgeschlossen.")
    print(f"    GTD-Output: {CLASSIFIED_GTD_PATH}")
    print(f"    Übersicht:  {SUMMARY_PATH}")
    print(f"    Codebook:    {CODEBOOK_PATH}")


def run_self_test() -> None:
    wup = pd.DataFrame(
        {
            "ISO3_Code": ["AAA"] * 8,
            "City_Code": [1, 2, 3, 4, 1, 2, 4, 3],
            "City_Name": [
                "Alpha",
                "Beta",
                "Gamma",
                "Delta",
                "Alpha",
                "Beta",
                "Delta",
                "Gamma",
            ],
            "Capital": [1, 0, 0, 0] * 2,
            "Year": [2000] * 4 + [2001] * 4,
            "PWCent_Latitude": [0.0, 1.0, 2.0, 3.0] * 2,
            "PWCent_Longitude": [0.0, 1.0, 2.0, 3.0] * 2,
            "Pop_plausibility": ["High"] * 8,
            "Pop": [100, 90, 80, 78, 105, 92, 82, 80],
        }
    )
    top4, diagnostics = build_yearly_rankings(wup)
    diagnostics, history, changes = add_change_diagnostics(top4, diagnostics)
    lookup, ambiguous = build_wup_alias_lookup(top4)

    assert len(top4) == 8
    assert diagnostics["top3_borderline_5pct"].all()
    assert diagnostics.loc[
        diagnostics["Year"].eq(2001), "top3_membership_changed"
    ].item()
    assert history["ever_top3_1993_2020"].all()
    assert len(changes) == 2
    assert ambiguous.empty
    assert lookup.duplicated(["ISO3", "city_alias_normalized"]).sum() == 0
    print("Self-test erfolgreich.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Historische GTD-Stadtklassifikation mit UN WUP 2025."
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Vorhandene WUP-Datei erneut herunterladen.",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Nur UN-WUP-Datei herunterladen/prüfen.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Kleinen synthetischen Funktionstest ausführen.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        run_self_test()
        return
    if args.download_only:
        download_wup_data(force=args.force_download)
        return
    run_pipeline(force_download=args.force_download)


if __name__ == "__main__":
    main()
