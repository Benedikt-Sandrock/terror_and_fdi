"""
Classify GTD events using a date-valid CShapes capital reference.

The classifier separates the factual match status from the analytical
specification. In the standard specification:

* 1  = the GTD city is an exact normalized capital name or known alias;
* 0  = outside the capital, including missing-city and unmatched-name cases
       within the near-capital review radius;
* NA = excluded from the capital/non-capital split, for example because the
       country/reference is unresolved or name and coordinates conflict.

The script preserves every GTD row and writes diagnostics plus a stratified
manual-review sample. ``capital_match_status`` is retained independently of
``is_capital_dynamic``, so every status can be treated differently in later
robustness checks without repeating the spatial/name matching.

Install dependencies once:
    pip install pandas numpy country_converter

Typical use:
    python classify_gtd_capitals_cshapes.py

By default, the script uses RAW and INTERIM from terror_and_fdi.config:
    RAW / "gtd" / "gtd_1993.csv"
    INTERIM / "capital_reference_dynamic.csv"
    INTERIM / "capital_name_aliases.csv"
    INTERIM / "cshapes_capital_classification" /
        "gtd_with_cshapes_capital.csv"

Explicit paths:
    python classify_gtd_capitals_cshapes.py \
        --gtd-input path/to/gtd.csv \
        --capital-reference path/to/capital_reference.csv \
        --output path/to/classified_gtd.csv
"""

from __future__ import annotations

import argparse
import logging
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
import os

import numpy as np
import pandas as pd

from terror_and_fdi.config import INTERIM, RAW

try:
    import country_converter as coco
except ImportError as exc:
    raise ImportError(
        "The package 'country_converter' is required. "
        "Install it with: pip install country_converter"
    ) from exc


DEFAULT_GTD_INPUT = RAW / "gtd" / "gtd_1993.csv"
DEFAULT_CAPITAL_REFERENCE = INTERIM / "capital_reference_dynamic.csv"
DEFAULT_ALIAS_FILE = INTERIM / "capital_name_aliases.csv"
DEFAULT_OUTPUT_DIR = INTERIM / "cshapes_capital_classification"
DEFAULT_OUTPUT = DEFAULT_OUTPUT_DIR / "gtd_with_cshapes_capital.csv"

DEFAULT_CHUNK_SIZE = 200_000
DEFAULT_REVIEW_PER_CLASS = 100
DEFAULT_NEAR_CAPITAL_KM = 25.0
DEFAULT_NAME_COORDINATE_CONFLICT_KM = 100.0

REQUIRED_GTD_COLUMNS = {
    "iyear",
    "imonth",
    "iday",
    "country_txt",
    "city",
}
REQUIRED_REFERENCE_COLUMNS = {
    "iso3",
    "gwcode",
    "country_name",
    "capital_name",
    "valid_from",
    "valid_until",
    "capital_longitude",
    "capital_latitude",
}

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

# GTD uses several country labels that need explicit handling. Historical codes
# are retained when the CShapes reference contains the same historical entity.
COUNTRY_OVERRIDES_ISO3: dict[str, str | None] = {
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
    "Slovak Republic": "SVK",
    "Macedonia": "MKD",
    "St. Kitts and Nevis": "KNA",
    "St. Lucia": "LCA",
    "Zaire": "COD",
    "West Germany (FRG)": "DEU",
    "East Germany (GDR)": "DDR",
    "Yugoslavia": "YUG",
    "Serbia-Montenegro": "SCG",
    "Czechoslovakia": "CSK",
    "Soviet Union": "SUN",
    "South Vietnam": "VNM",
    "North Vietnam": "VNM",
    "International": None,
}

# Each set contains conservative spelling/name variants of one city. A group
# is only activated when one of its names is the applicable CShapes capital.
CAPITAL_ALIAS_GROUPS_RAW = [
    {"Astana", "Nur-Sultan", "Nur Sultan", "Aqmola", "Akmola"},
    {"Kyiv", "Kiev"},
    {"Yangon", "Rangoon"},
    {"Naypyidaw", "Nay Pyi Taw", "Naypyitaw"},
    {"Kinshasa", "Leopoldville", "Léopoldville"},
    {"Ho Chi Minh City", "Saigon"},
    {"Beijing", "Peking"},
    {"Ulaanbaatar", "Ulan Bator", "Ulanbaatar"},
    {"Podgorica", "Titograd"},
    {"Harare", "Salisbury"},
    {"Maputo", "Lourenco Marques", "Lourenço Marques"},
    {"Washington", "Washington DC", "Washington D.C."},
    {"Mexico City", "Mexico D.F.", "Ciudad de México"},
    {"Addis Ababa", "Addis Abeba"},
    {"N'Djamena", "Ndjamena", "N Djamena"},
    {"Sanaa", "Sana'a", "Sana"},
    {"Bujumbura", "Usumbura"},
    {"Gitega", "Kitega"},
    {"Almaty", "Alma-Ata", "Alma Ata"},
    {"Jerusalem", "East Jerusalem"},
    {"Mumbai", "Bombay"},
    {"Chennai", "Madras"},
    {"Kolkata", "Calcutta"},
]

OUTPUT_CLASSIFICATION_COLUMNS = [
    "ISO3",
    "event_date_start",
    "event_date_end",
    "capital_date_precision",
    "capital_reference_available",
    "capital_reference_candidates",
    "capital_transition_ambiguous",
    "capital_name_at_event",
    "capital_name_normalized",
    "capital_gwcode",
    "capital_reference_source",
    "capital_latitude",
    "capital_longitude",
    "gtd_city_normalized",
    "capital_name_match",
    "capital_distance_km",
    "capital_match_status",
    "capital_dynamic_source",
    "capital_spec_treatment",
    "capital_spec_included",
    "capital_spec_exclusion_reason",
    "is_capital_dynamic",
    "capital_status_missing_city",
    "capital_status_name_coordinate_conflict",
    "capital_status_near_capital_name_unmatched",
    "capital_status_no_capital_reference_for_country_date",
    "capital_status_unresolved_country",
]

USABLE_REFERENCE_STATUSES = {
    "capital_name_or_alias_match",
    "outside_capital",
    "missing_city",
    "near_capital_name_unmatched",
    "name_coordinate_conflict",
}

ALL_MATCH_STATUSES = [
    "capital_name_or_alias_match",
    "outside_capital",
    "missing_city",
    "near_capital_name_unmatched",
    "name_coordinate_conflict",
    "no_capital_reference_for_country_date",
    "ambiguous_capital_period",
    "missing_event_date",
    "unresolved_country",
    "unclassified",
]

# Change an entry to "outside", "capital", or "exclude" for an alternative
# specification. The default below is the requested standard specification.
# The raw status and one status flag per requested robustness group are always
# retained in the output, irrespective of these analytical treatments.
CAPITAL_STATUS_TREATMENT: dict[str, str] = {
    "capital_name_or_alias_match": "capital",
    "outside_capital": "outside",
    "missing_city": "outside",
    "near_capital_name_unmatched": "outside",
    "name_coordinate_conflict": "exclude",
    "no_capital_reference_for_country_date": "exclude",
    "unresolved_country": "exclude",
    "ambiguous_capital_period": "exclude",
    "missing_event_date": "exclude",
    "unclassified": "exclude",
}

ROBUSTNESS_STATUS_FLAGS = [
    "missing_city",
    "name_coordinate_conflict",
    "near_capital_name_unmatched",
    "no_capital_reference_for_country_date",
    "unresolved_country",
]


if not os.path.exists(DEFAULT_GTD_INPUT):
    print("Restricting GTD to years after 1993...")
    gtd_old = pd.read_csv(RAW / "gtd" / "gtd.csv")
    gtd_new = gtd_old[gtd_old["iyear"] > 1993]
    gtd_new.to_csv(DEFAULT_GTD_INPUT, index=False)

def apply_capital_specification(
    frame: pd.DataFrame,
    treatments: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    Apply an analytical treatment to the already determined match statuses.

    No row is removed. ``exclude`` is represented by NA in
    ``is_capital_dynamic`` and by 0 in ``capital_spec_included``.
    """
    result = frame.copy()
    treatments = (
        CAPITAL_STATUS_TREATMENT if treatments is None else treatments
    )
    allowed = {"capital", "outside", "exclude"}
    invalid_treatments = {
        status: treatment
        for status, treatment in treatments.items()
        if treatment not in allowed
    }
    if invalid_treatments:
        raise ValueError(
            "Invalid capital-status treatments: "
            f"{invalid_treatments}. Allowed: {sorted(allowed)}"
        )

    observed = set(
        result["capital_match_status"].dropna().astype(str).unique()
    )
    missing_treatments = observed - set(treatments)
    if missing_treatments:
        raise ValueError(
            "No analytical treatment defined for statuses: "
            f"{sorted(missing_treatments)}"
        )

    treatment = result["capital_match_status"].map(treatments).astype("string")
    result["capital_spec_treatment"] = treatment
    result["is_capital_dynamic"] = (
        treatment.map({"capital": 1, "outside": 0})
        .astype("Int8")
    )
    result["capital_spec_included"] = (
        treatment.ne("exclude").astype("Int8")
    )
    result["capital_spec_exclusion_reason"] = (
        result["capital_match_status"].where(treatment.eq("exclude"))
    )

    for status in ROBUSTNESS_STATUS_FLAGS:
        result[f"capital_status_{status}"] = (
            result["capital_match_status"].eq(status).astype("Int8")
        )

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify GTD events with date-valid CShapes capitals."
    )
    parser.add_argument(
        "--gtd-input",
        type=Path,
        default=DEFAULT_GTD_INPUT,
        help="Raw GTD CSV.",
    )
    parser.add_argument(
        "--capital-reference",
        type=Path,
        default=DEFAULT_CAPITAL_REFERENCE,
        help="Output of create_capital_reference_cshapes.py.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Classified event-level GTD CSV.",
    )
    parser.add_argument(
        "--alias-file",
        type=Path,
        default=DEFAULT_ALIAS_FILE,
        help=(
            "CSV with columns iso3, capital_name, alias. By default, "
            "INTERIM / 'capital_name_aliases.csv' is read and its aliases "
            "are added to the built-in conservative aliases."
        ),
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="Number of GTD rows processed at once.",
    )
    parser.add_argument(
        "--near-capital-km",
        type=float,
        default=DEFAULT_NEAR_CAPITAL_KM,
        help=(
            "An unmatched, specificity-1 point within this distance receives "
            "status near_capital_name_unmatched. Its analytical treatment is "
            "defined separately in CAPITAL_STATUS_TREATMENT."
        ),
    )
    parser.add_argument(
        "--name-coordinate-conflict-km",
        type=float,
        default=DEFAULT_NAME_COORDINATE_CONFLICT_KM,
        help=(
            "A name match farther away than this (specificity 1) is NA."
        ),
    )
    parser.add_argument(
        "--review-per-class",
        type=int,
        default=DEFAULT_REVIEW_PER_CLASS,
        help="Maximum manual-review rows for each of 1, 0, and NA.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Seed used for the deterministic review sample.",
    )
    return parser.parse_args()


def normalize_city_name(value: object) -> str | pd.NA:
    """Normalize city names for conservative exact matching."""
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


CAPITAL_ALIAS_GROUPS = [
    frozenset(
        normalized
        for value in group
        if pd.notna(normalized := normalize_city_name(value))
    )
    for group in CAPITAL_ALIAS_GROUPS_RAW
]


def basic_name_aliases(value: object) -> set[str]:
    """Derive only unambiguous aliases from one CShapes label."""
    if pd.isna(value):
        return set()

    text = str(value).strip()
    raw_aliases = {text}

    for parenthetical in re.findall(r"\(([^()]*)\)", text):
        raw_aliases.add(parenthetical)

    without_parentheses = re.sub(r"\s*\([^()]*\)", "", text).strip()
    if without_parentheses:
        raw_aliases.add(without_parentheses)

    for separator in (" / ", "/", " – "):
        if separator in text:
            raw_aliases.update(
                part.strip() for part in text.split(separator) if part.strip()
            )

    return {
        normalized
        for alias in raw_aliases
        if pd.notna(normalized := normalize_city_name(alias))
    }


def build_reference_aliases(
    reference: pd.DataFrame,
    alias_file: Path | None,
) -> pd.DataFrame:
    result = reference.copy()
    aliases_by_key: dict[tuple[str, str], set[str]] = {}

    for row in result.itertuples(index=False):
        key = (row.ISO3, row.capital_name_normalized)
        aliases = aliases_by_key.setdefault(key, set())
        aliases.update(basic_name_aliases(row.capital_name))

        for group in CAPITAL_ALIAS_GROUPS:
            if row.capital_name_normalized in group:
                aliases.update(group)

    if alias_file is not None:
        custom = pd.read_csv(alias_file)
        required = {"iso3", "capital_name", "alias"}
        missing = required - set(custom.columns)
        if missing:
            raise ValueError(
                f"Alias file is missing columns: {sorted(missing)}"
            )

        custom["ISO3"] = custom["iso3"].astype("string").str.upper()
        custom["capital_name_normalized"] = custom["capital_name"].map(
            normalize_city_name
        )
        custom["alias_normalized"] = custom["alias"].map(normalize_city_name)

        for row in custom.itertuples(index=False):
            key = (row.ISO3, row.capital_name_normalized)
            if key not in aliases_by_key:
                raise ValueError(
                    "Custom alias does not match a reference capital: "
                    f"{row.ISO3}, {row.capital_name}"
                )
            if pd.notna(row.alias_normalized):
                aliases_by_key[key].add(row.alias_normalized)

    result["_capital_aliases"] = [
        frozenset(
            aliases_by_key[(iso3, capital)]
        )
        for iso3, capital in zip(
            result["ISO3"],
            result["capital_name_normalized"],
        )
    ]
    return result


def load_capital_reference(
    path: Path,
    alias_file: Path | None = None,
) -> pd.DataFrame:
    reference = pd.read_csv(path)
    missing = REQUIRED_REFERENCE_COLUMNS - set(reference.columns)
    if missing:
        raise ValueError(
            f"Capital reference is missing columns: {sorted(missing)}"
        )

    reference = reference.rename(columns={"iso3": "ISO3"}).copy()
    reference["ISO3"] = reference["ISO3"].astype("string").str.upper()
    reference["valid_from"] = pd.to_datetime(
        reference["valid_from"], errors="raise"
    )
    reference["valid_until"] = pd.to_datetime(
        reference["valid_until"], errors="raise"
    )
    reference["capital_name_normalized"] = reference["capital_name"].map(
        normalize_city_name
    )
    reference["capital_latitude"] = pd.to_numeric(
        reference["capital_latitude"], errors="raise"
    )
    reference["capital_longitude"] = pd.to_numeric(
        reference["capital_longitude"], errors="raise"
    )
    if "reference_source" not in reference.columns:
        reference["reference_source"] = "cshapes_2_1"
    reference["reference_source"] = (
        reference["reference_source"].astype("string").fillna("unknown")
    )

    if reference["ISO3"].isna().any():
        missing_countries = sorted(
            reference.loc[
                reference["ISO3"].isna(), "country_name"
            ].astype(str).unique()
        )
        print(
            "Warning: reference rows without ISO3 are unavailable for GTD "
            "matching: " + ", ".join(missing_countries)
        )
        reference = reference.loc[reference["ISO3"].notna()].copy()

    if reference.empty:
        raise ValueError("No usable capital-reference rows remain.")

    identity_columns = [
        "ISO3",
        "capital_name_normalized",
        "capital_latitude",
        "capital_longitude",
    ]
    reference["_capital_identity"] = (
        reference[identity_columns]
        .astype("string")
        .agg("|".join, axis=1)
    )

    return build_reference_aliases(reference, alias_file)


def convert_country_to_iso3(
    country: object,
    converter: coco.CountryConverter,
) -> str | pd.NA:
    if pd.isna(country):
        return pd.NA

    country_name = str(country).strip()
    if country_name in COUNTRY_OVERRIDES_ISO3:
        override = COUNTRY_OVERRIDES_ISO3[country_name]
        return pd.NA if override is None else override

    converted = converter.convert(
        names=country_name,
        src="name_short",
        to="ISO3",
        not_found=None,
    )
    if converted is None:
        return pd.NA

    converted = str(converted).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", converted):
        return pd.NA
    return converted


def add_or_validate_iso3(
    chunk: pd.DataFrame,
    converter: coco.CountryConverter,
    country_cache: dict[str, str | pd.NA],
) -> pd.DataFrame:
    result = chunk.copy()
    countries = result["country_txt"].astype("string").str.strip()

    for country in countries.dropna().unique():
        if country not in country_cache:
            country_cache[country] = convert_country_to_iso3(
                country, converter
            )

    converted = countries.map(country_cache).astype("string")

    if "ISO3" in result.columns:
        supplied = result["ISO3"].astype("string").str.strip().str.upper()
        supplied = supplied.where(supplied.str.fullmatch(r"[A-Z]{3}"))
        conflict = (
            supplied.notna()
            & converted.notna()
            & supplied.ne(converted)
        )
        if conflict.any():
            examples = result.loc[
                conflict, ["country_txt", "ISO3"]
            ].drop_duplicates().head(10)
            raise ValueError(
                "Existing ISO3 values conflict with country_txt conversion:\n"
                + examples.to_string(index=False)
            )
        result["ISO3"] = supplied.fillna(converted)
    else:
        result["ISO3"] = converted

    return result


def build_event_date_bounds(
    chunk: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return the full possible GTD date interval and its precision."""
    year = pd.to_numeric(chunk["iyear"], errors="coerce").astype("Int64")
    month = pd.to_numeric(chunk["imonth"], errors="coerce").astype("Int64")
    day = pd.to_numeric(chunk["iday"], errors="coerce").astype("Int64")

    year_start = pd.to_datetime(
        {
            "year": year,
            "month": pd.Series(1, index=chunk.index),
            "day": pd.Series(1, index=chunk.index),
        },
        errors="coerce",
    )
    start = year_start.copy()
    end = year_start + pd.offsets.YearEnd(0)
    precision = pd.Series("year", index=chunk.index, dtype="string")

    valid_month = month.between(1, 12) & year.notna()
    month_start = pd.to_datetime(
        {
            "year": year,
            "month": month.where(valid_month, 1),
            "day": pd.Series(1, index=chunk.index),
        },
        errors="coerce",
    )
    start.loc[valid_month] = month_start.loc[valid_month]
    end.loc[valid_month] = (
        month_start.loc[valid_month] + pd.offsets.MonthEnd(0)
    )
    precision.loc[valid_month] = "month"

    possible_day = day.between(1, 31) & valid_month
    exact_date = pd.to_datetime(
        {
            "year": year,
            "month": month.where(valid_month, 1),
            "day": day.where(possible_day, 1),
        },
        errors="coerce",
    )
    valid_day = possible_day & exact_date.notna()
    start.loc[valid_day] = exact_date.loc[valid_day]
    end.loc[valid_day] = exact_date.loc[valid_day]
    precision.loc[valid_day] = "day"

    missing_year = year.isna()
    start.loc[missing_year] = pd.NaT
    end.loc[missing_year] = pd.NaT
    precision.loc[missing_year] = "missing"
    return start, end, precision


def haversine_km(
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


def select_applicable_capitals(
    chunk: pd.DataFrame,
    reference: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Match the possible event-date interval to CShapes.

    A non-day GTD date that overlaps two different capitals is intentionally
    ambiguous; it is never resolved from the city name after the fact.
    """
    left = chunk[
        ["_row_id", "ISO3", "event_date_start", "event_date_end"]
    ]
    candidate_columns = [
        "ISO3",
        "gwcode",
        "capital_name",
        "capital_name_normalized",
        "capital_latitude",
        "capital_longitude",
        "reference_source",
        "valid_from",
        "valid_until",
        "_capital_identity",
        "_capital_aliases",
    ]
    expanded = left.merge(
        reference[candidate_columns],
        on="ISO3",
        how="left",
        validate="many_to_many",
    )

    overlaps = (
        expanded["valid_from"].le(expanded["event_date_end"])
        & expanded["valid_until"].ge(expanded["event_date_start"])
    )
    applicable = expanded.loc[overlaps].copy()

    counts = (
        applicable.groupby("_row_id")["_capital_identity"]
        .nunique()
        .reindex(chunk["_row_id"], fill_value=0)
        .astype("int16")
    )

    unambiguous_ids = counts.index[counts.eq(1)]
    selected = (
        applicable.loc[applicable["_row_id"].isin(unambiguous_ids)]
        .sort_values(["_row_id", "valid_from"])
        .drop_duplicates("_row_id")
        .set_index("_row_id")
    )
    return selected, counts


def classify_chunk(
    chunk: pd.DataFrame,
    reference: pd.DataFrame,
    converter: coco.CountryConverter,
    country_cache: dict[str, str | pd.NA],
    first_row_id: int,
    near_capital_km: float,
    conflict_km: float,
) -> pd.DataFrame:
    missing = REQUIRED_GTD_COLUMNS - set(chunk.columns)
    if missing:
        raise ValueError(f"GTD input is missing columns: {sorted(missing)}")

    result = add_or_validate_iso3(chunk, converter, country_cache)
    result["_row_id"] = np.arange(
        first_row_id, first_row_id + len(result), dtype=np.int64
    )

    start, end, precision = build_event_date_bounds(result)
    result["event_date_start"] = start
    result["event_date_end"] = end
    result["capital_date_precision"] = precision
    result["gtd_city_normalized"] = result["city"].map(normalize_city_name)

    selected, candidate_counts = select_applicable_capitals(
        result, reference
    )
    row_ids = pd.Index(result["_row_id"])
    result["capital_reference_candidates"] = (
        candidate_counts.reindex(row_ids).to_numpy()
    )
    result["capital_reference_available"] = (
        result["capital_reference_candidates"].eq(1).astype("Int8")
    )
    result["capital_transition_ambiguous"] = (
        result["capital_reference_candidates"].gt(1).astype("Int8")
    )

    selected_columns = {
        "capital_name": "capital_name_at_event",
        "capital_name_normalized": "capital_name_normalized",
        "gwcode": "capital_gwcode",
        "capital_latitude": "capital_latitude",
        "capital_longitude": "capital_longitude",
        "reference_source": "capital_reference_source",
        "_capital_aliases": "_capital_aliases",
    }
    for source, target in selected_columns.items():
        result[target] = result["_row_id"].map(selected[source])

    result["capital_name_match"] = pd.Series(
        pd.NA, index=result.index, dtype="Int8"
    )
    usable_reference = result["capital_reference_available"].eq(1)
    has_city = result["gtd_city_normalized"].notna()
    match_mask = usable_reference & has_city
    result.loc[match_mask, "capital_name_match"] = [
        int(city in aliases)
        for city, aliases in zip(
            result.loc[match_mask, "gtd_city_normalized"],
            result.loc[match_mask, "_capital_aliases"],
        )
    ]

    if {"latitude", "longitude"}.issubset(result.columns):
        latitude = pd.to_numeric(result["latitude"], errors="coerce")
        longitude = pd.to_numeric(result["longitude"], errors="coerce")
        valid_coordinates = (
            latitude.between(-90, 90)
            & longitude.between(-180, 180)
        )
    else:
        latitude = pd.Series(np.nan, index=result.index)
        longitude = pd.Series(np.nan, index=result.index)
        valid_coordinates = pd.Series(False, index=result.index)

    result["capital_distance_km"] = haversine_km(
        latitude,
        longitude,
        result["capital_latitude"],
        result["capital_longitude"],
    ).where(valid_coordinates & usable_reference)

    if "specificity" in result.columns:
        precise_coordinates = pd.to_numeric(
            result["specificity"], errors="coerce"
        ).eq(1)
    else:
        precise_coordinates = pd.Series(False, index=result.index)

    result["is_capital_dynamic"] = pd.Series(
        pd.NA, index=result.index, dtype="Int8"
    )
    result["capital_match_status"] = pd.Series(
        "unclassified", index=result.index, dtype="string"
    )
    result["capital_dynamic_source"] = result[
        "capital_reference_source"
    ].astype("string")

    unresolved_country = result["ISO3"].isna()
    missing_date = result["event_date_start"].isna()
    no_reference = (
        ~unresolved_country
        & ~missing_date
        & result["capital_reference_candidates"].eq(0)
    )
    ambiguous = result["capital_reference_candidates"].gt(1)
    missing_city = usable_reference & ~has_city

    result.loc[unresolved_country, "capital_match_status"] = (
        "unresolved_country"
    )
    result.loc[
        ~unresolved_country & missing_date, "capital_match_status"
    ] = "missing_event_date"
    result.loc[no_reference, "capital_match_status"] = (
        "no_capital_reference_for_country_date"
    )
    result.loc[ambiguous, "capital_match_status"] = (
        "ambiguous_capital_period"
    )
    result.loc[missing_city, "capital_match_status"] = "missing_city"

    name_match = result["capital_name_match"].eq(1)
    name_nonmatch = result["capital_name_match"].eq(0)
    coordinate_conflict = (
        name_match
        & precise_coordinates
        & result["capital_distance_km"].gt(conflict_km)
    )
    reliable_name_match = name_match & ~coordinate_conflict
    near_unmatched = (
        name_nonmatch
        & precise_coordinates
        & result["capital_distance_km"].le(near_capital_km)
    )
    definite_noncapital = name_nonmatch & ~near_unmatched

    result.loc[reliable_name_match, "is_capital_dynamic"] = 1
    result.loc[reliable_name_match, "capital_match_status"] = (
        "capital_name_or_alias_match"
    )
    result.loc[reliable_name_match, "capital_dynamic_source"] = (
        result.loc[reliable_name_match, "capital_reference_source"]
        .astype("string")
        + "_name_alias"
    )

    result.loc[definite_noncapital, "is_capital_dynamic"] = 0
    result.loc[definite_noncapital, "capital_match_status"] = (
        "outside_capital"
    )
    result.loc[definite_noncapital, "capital_dynamic_source"] = (
        result.loc[definite_noncapital, "capital_reference_source"]
        .astype("string")
        + "_name_nonmatch"
    )

    result.loc[near_unmatched, "capital_match_status"] = (
        "near_capital_name_unmatched"
    )
    result.loc[coordinate_conflict, "capital_match_status"] = (
        "name_coordinate_conflict"
    )

    result = apply_capital_specification(result)
    result = result.drop(columns=["_capital_aliases", "_row_id"])
    return result


def update_review_candidates(
    candidates: dict[str, pd.DataFrame],
    chunk: pd.DataFrame,
    n_per_class: int,
    seed: int,
) -> None:
    if n_per_class <= 0:
        return

    review_columns = [
        column
        for column in [
            "eventid",
            "country_txt",
            "ISO3",
            "iyear",
            "imonth",
            "iday",
            "city",
            "latitude",
            "longitude",
            "specificity",
            "capital_name_at_event",
            "capital_latitude",
            "capital_longitude",
            "capital_distance_km",
            "capital_date_precision",
            "capital_match_status",
            "is_capital_dynamic",
        ]
        if column in chunk.columns
    ]

    labels = chunk["is_capital_dynamic"].astype("string").fillna("NA")
    stable_id = (
        chunk["eventid"].astype("string")
        if "eventid" in chunk.columns
        else pd.Series(chunk.index.astype(str), index=chunk.index)
    )
    hashes = pd.util.hash_pandas_object(
        stable_id + f"|{seed}", index=False
    ).astype("uint64")

    for label in ("1", "0", "NA"):
        mask = labels.eq(label)
        if not mask.any():
            continue
        sample = chunk.loc[mask, review_columns].copy()
        sample["_sample_hash"] = hashes.loc[mask].to_numpy()
        sample["_review_class"] = label

        existing = candidates.get(label)
        combined = (
            sample
            if existing is None
            else pd.concat([existing, sample], ignore_index=True)
        )
        candidates[label] = combined.nsmallest(
            n_per_class, "_sample_hash"
        )


def validate_classified_chunk(chunk: pd.DataFrame) -> None:
    values = set(
        chunk["is_capital_dynamic"].dropna().astype(int).unique()
    )
    if not values.issubset({0, 1}):
        raise RuntimeError(
            f"Invalid is_capital_dynamic values: {sorted(values)}"
        )

    expected = (
        chunk["capital_match_status"]
        .map(CAPITAL_STATUS_TREATMENT)
        .map({"capital": 1, "outside": 0})
        .astype("Int8")
    )
    mismatch = ~(
        chunk["is_capital_dynamic"].eq(expected)
        | (
            chunk["is_capital_dynamic"].isna()
            & expected.isna()
        )
    )
    if mismatch.any():
        raise RuntimeError(
            "is_capital_dynamic does not match the standard status "
            "treatment."
        )

    inclusion_mismatch = chunk["capital_spec_included"].ne(
        chunk["is_capital_dynamic"].notna().astype("Int8")
    )
    if inclusion_mismatch.any():
        raise RuntimeError(
            "capital_spec_included is inconsistent with "
            "is_capital_dynamic."
        )

    positives_without_match = (
        chunk["is_capital_dynamic"].eq(1)
        & ~chunk["capital_name_match"].eq(1)
    )
    if positives_without_match.any():
        raise RuntimeError(
            "At least one capital classification lacks a name/alias match."
        )

    reference_logic_error = (
        chunk["capital_reference_available"].eq(1)
        != chunk["capital_reference_candidates"].eq(1)
    )
    if reference_logic_error.any():
        raise RuntimeError("Capital-reference availability is inconsistent.")


def build_country_coverage(
    country_year: pd.DataFrame,
) -> pd.DataFrame:
    """
    Summarize capital-reference coverage and matches for every GTD country.

    A country with zero capital matches is not automatically a classification
    failure: it may have a usable CShapes reference but no GTD event whose city
    matches the capital. The diagnostic therefore keeps these cases separate
    from countries for which no event has a usable capital reference.
    """
    required = {
        "ISO3",
        "country_txt",
        "capital_match_status",
        "events",
    }
    missing = required - set(country_year.columns)
    if missing:
        raise ValueError(
            "Country-year diagnostics are missing columns: "
            f"{sorted(missing)}"
        )

    data = country_year.copy()
    data["_iso3_key"] = (
        data["ISO3"].astype("string").fillna("<UNRESOLVED>")
    )
    data["_country_key"] = (
        data["country_txt"].astype("string").fillna("<MISSING_COUNTRY>")
    )

    country_status = (
        data.groupby(
            ["_iso3_key", "_country_key", "capital_match_status"],
            dropna=False,
            observed=True,
        )["events"]
        .sum()
        .reset_index()
    )
    coverage = (
        country_status.pivot(
            index=["_iso3_key", "_country_key"],
            columns="capital_match_status",
            values="events",
        )
        .fillna(0)
        .reset_index()
        .rename(
            columns={
                "_iso3_key": "ISO3",
                "_country_key": "country_txt",
            }
        )
    )
    coverage.columns.name = None

    for status in ALL_MATCH_STATUSES:
        if status not in coverage.columns:
            coverage[status] = 0

    status_columns = [
        column
        for column in coverage.columns
        if column not in {"ISO3", "country_txt"}
    ]
    coverage[status_columns] = coverage[status_columns].astype("int64")

    coverage["events_total"] = coverage[status_columns].sum(axis=1)
    coverage["events_capital_identified"] = coverage[
        "capital_name_or_alias_match"
    ]
    outside_statuses = [
        status
        for status, treatment in CAPITAL_STATUS_TREATMENT.items()
        if treatment == "outside"
    ]
    excluded_statuses = [
        status
        for status, treatment in CAPITAL_STATUS_TREATMENT.items()
        if treatment == "exclude"
    ]
    coverage["events_outside_capital"] = coverage[
        outside_statuses
    ].sum(axis=1)
    coverage["events_with_usable_reference"] = coverage[
        sorted(USABLE_REFERENCE_STATUSES)
    ].sum(axis=1)
    coverage["events_without_usable_classification"] = coverage[
        excluded_statuses
    ].sum(axis=1)
    coverage["share_without_usable_classification"] = (
        coverage["events_without_usable_classification"]
        / coverage["events_total"]
    )
    coverage["has_identified_capital_event"] = (
        coverage["events_capital_identified"].gt(0).astype("Int8")
    )
    coverage["has_any_usable_capital_reference"] = (
        coverage["events_with_usable_reference"].gt(0).astype("Int8")
    )

    coverage["diagnostic_category"] = np.select(
        [
            coverage["has_identified_capital_event"].eq(1),
            coverage["has_any_usable_capital_reference"].eq(0),
        ],
        [
            "capital_event_identified",
            "no_usable_capital_reference_for_any_event",
        ],
        default="usable_reference_but_no_capital_event_match",
    )

    coverage["ISO3"] = coverage["ISO3"].replace(
        "<UNRESOLVED>", pd.NA
    )
    coverage["country_txt"] = coverage["country_txt"].replace(
        "<MISSING_COUNTRY>", pd.NA
    )

    ordered = [
        "ISO3",
        "country_txt",
        "diagnostic_category",
        "events_total",
        "events_capital_identified",
        "events_outside_capital",
        "events_with_usable_reference",
        "events_without_usable_classification",
        "share_without_usable_classification",
        "has_identified_capital_event",
        "has_any_usable_capital_reference",
    ]
    status_output = [
        column for column in ALL_MATCH_STATUSES
        if column in coverage.columns
    ]
    return coverage[ordered + status_output].sort_values(
        [
            "diagnostic_category",
            "events_without_usable_classification",
            "country_txt",
        ],
        ascending=[True, False, True],
        na_position="last",
    )


def write_diagnostics(
    output_dir: Path,
    status_counts: Counter,
    country_year_parts: list[pd.DataFrame],
    unmatched_parts: list[pd.DataFrame],
    review_candidates: dict[str, pd.DataFrame],
    country_cache: dict[str, str | pd.NA],
    total_rows: int,
    output_path: Path,
    reference_path: Path,
    near_capital_km: float,
    conflict_km: float,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    country_coverage = pd.DataFrame()

    if country_year_parts:
        country_year = pd.concat(country_year_parts, ignore_index=True)
        country_year = (
            country_year.groupby(
                ["ISO3", "country_txt", "iyear", "capital_match_status"],
                dropna=False,
                observed=True,
            )["events"]
            .sum()
            .reset_index()
        )
        country_year.to_csv(
            output_dir / "capital_country_year_diagnostics.csv",
            index=False,
            encoding="utf-8",
        )
        country_coverage = build_country_coverage(country_year)
        country_coverage.to_csv(
            output_dir / "capital_country_coverage.csv",
            index=False,
            encoding="utf-8",
        )

        countries_without_capital_match = country_coverage.loc[
            country_coverage["has_identified_capital_event"].eq(0)
        ].copy()
        countries_without_capital_match.to_csv(
            output_dir
            / "capital_countries_without_identified_capital.csv",
            index=False,
            encoding="utf-8",
        )

        countries_without_reference = country_coverage.loc[
            country_coverage[
                "has_any_usable_capital_reference"
            ].eq(0)
        ].copy()
        countries_without_reference.to_csv(
            output_dir
            / "capital_countries_without_usable_reference.csv",
            index=False,
            encoding="utf-8",
        )

    if unmatched_parts:
        unmatched = pd.concat(unmatched_parts, ignore_index=True)
        unmatched = (
            unmatched.groupby(
                [
                    "ISO3",
                    "country_txt",
                    "city",
                    "capital_name_at_event",
                    "capital_match_status",
                ],
                dropna=False,
                observed=True,
            )
            .agg(
                events=("events", "sum"),
                first_year=("first_year", "min"),
                last_year=("last_year", "max"),
            )
            .reset_index()
            .sort_values(
                ["capital_match_status", "events"],
                ascending=[True, False],
            )
        )
        unmatched.to_csv(
            output_dir / "capital_unmatched_city_review.csv",
            index=False,
            encoding="utf-8",
        )

    review_frames = [
        review_candidates[label]
        for label in ("1", "0", "NA")
        if label in review_candidates
    ]
    if review_frames:
        review = pd.concat(review_frames, ignore_index=True)
        review = review.drop(columns="_sample_hash")
        review.to_csv(
            output_dir / "capital_manual_validation_sample.csv",
            index=False,
            encoding="utf-8",
        )

    unresolved = sorted(
        country
        for country, iso3 in country_cache.items()
        if pd.isna(iso3)
    )
    countries_without_match = (
        int(
            country_coverage[
                "has_identified_capital_event"
            ].eq(0).sum()
        )
        if not country_coverage.empty
        else 0
    )
    countries_without_reference = (
        int(
            country_coverage[
                "has_any_usable_capital_reference"
            ].eq(0).sum()
        )
        if not country_coverage.empty
        else 0
    )
    rows = [
        "# Dynamic capital-classification summary",
        "",
        f"- Classified GTD rows: {total_rows:,}",
        f"- Classified event file: `{output_path}`",
        f"- Capital reference: `{reference_path}`",
        f"- Near-capital ambiguity threshold: {near_capital_km:g} km",
        f"- Name/coordinate conflict threshold: {conflict_km:g} km",
        "",
        "## Match status",
        "",
        "| Status | Events | Share |",
        "|---|---:|---:|",
    ]
    for status, count in sorted(
        status_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        share = count / total_rows if total_rows else math.nan
        rows.append(f"| {status} | {count:,} | {share:.2%} |")

    rows.extend(
        [
            "",
            "## Unresolved GTD country labels",
            "",
            (
                ", ".join(unresolved)
                if unresolved
                else "None."
            ),
            "",
            "## Country-level coverage",
            "",
            (
                "- Countries with no GTD capital-event match: "
                f"{countries_without_match:,}"
            ),
            (
                "- Countries with no usable capital reference for "
                f"any event: {countries_without_reference:,}"
            ),
            "",
            "See `capital_country_coverage.csv` for all countries, "
            "`capital_countries_without_identified_capital.csv` for zero "
            "capital-event matches, and "
            "`capital_countries_without_usable_reference.csv` for actual "
            "reference-coverage failures.",
            "",
            "## Interpretation",
            "",
            "- `1`: capital-name or confirmed-alias match.",
            "- `0`: standard-specification outside-capital case. This "
            "includes `outside_capital`, `missing_city`, and "
            "`near_capital_name_unmatched`.",
            "- `NA`: excluded from the standard capital/non-capital split. "
            "This includes `name_coordinate_conflict`, "
            "`no_capital_reference_for_country_date`, and "
            "`unresolved_country` (plus other unresolved date cases).",
            "- Every GTD row remains in the event file. "
            "`capital_spec_included` marks standard-specification inclusion.",
            "- For robustness checks, use `capital_match_status` or the "
            "`capital_status_*` flags and change only the relevant status "
            "treatment during aggregation.",
            "",
            "Inspect `capital_manual_validation_sample.csv` and "
            "`capital_unmatched_city_review.csv` before aggregation.",
        ]
    )
    (output_dir / "capital_classification_summary.md").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )


def run_classification(
    gtd_input: Path,
    reference_path: Path,
    output_path: Path,
    alias_file: Path | None = None,
    chunksize: int = DEFAULT_CHUNK_SIZE,
    near_capital_km: float = DEFAULT_NEAR_CAPITAL_KM,
    conflict_km: float = DEFAULT_NAME_COORDINATE_CONFLICT_KM,
    review_per_class: int = DEFAULT_REVIEW_PER_CLASS,
    random_seed: int = 42,
) -> None:
    if chunksize <= 0:
        raise ValueError("chunksize must be positive.")
    if near_capital_km < 0 or conflict_km <= 0:
        raise ValueError("Distance thresholds must be non-negative.")
    if near_capital_km >= conflict_km:
        raise ValueError(
            "near_capital_km must be smaller than conflict_km."
        )

    reference = load_capital_reference(reference_path, alias_file)
    converter = coco.CountryConverter()
    country_cache: dict[str, str | pd.NA] = {}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(
        f"{output_path.stem}.tmp{output_path.suffix}"
    )
    temporary.unlink(missing_ok=True)

    total_input_rows = 0
    total_output_rows = 0
    status_counts: Counter = Counter()
    country_year_parts: list[pd.DataFrame] = []
    unmatched_parts: list[pd.DataFrame] = []
    review_candidates: dict[str, pd.DataFrame] = {}
    first_chunk = True

    try:
        for chunk_number, chunk in enumerate(
            pd.read_csv(gtd_input, chunksize=chunksize, low_memory=False),
            start=1,
        ):
            input_rows = len(chunk)
            classified = classify_chunk(
                chunk=chunk,
                reference=reference,
                converter=converter,
                country_cache=country_cache,
                first_row_id=total_input_rows,
                near_capital_km=near_capital_km,
                conflict_km=conflict_km,
            )
            validate_classified_chunk(classified)

            if len(classified) != input_rows:
                raise RuntimeError(
                    "GTD row count changed inside a classification chunk."
                )

            classified.to_csv(
                temporary,
                mode="w" if first_chunk else "a",
                header=first_chunk,
                index=False,
                encoding="utf-8",
                date_format="%Y-%m-%d",
            )
            first_chunk = False

            total_input_rows += input_rows
            total_output_rows += len(classified)
            status_counts.update(
                classified["capital_match_status"].value_counts().to_dict()
            )

            country_year = (
                classified.groupby(
                    [
                        "ISO3",
                        "country_txt",
                        "iyear",
                        "capital_match_status",
                    ],
                    dropna=False,
                    observed=True,
                )
                .size()
                .rename("events")
                .reset_index()
            )
            country_year_parts.append(country_year)

            review_mask = (
                classified["capital_match_status"]
                .ne("capital_name_or_alias_match")
                & classified["city"].notna()
            )
            if review_mask.any():
                unmatched = (
                    classified.loc[review_mask]
                    .groupby(
                        [
                            "ISO3",
                            "country_txt",
                            "city",
                            "capital_name_at_event",
                            "capital_match_status",
                        ],
                        dropna=False,
                        observed=True,
                    )
                    .agg(
                        events=("city", "size"),
                        first_year=("iyear", "min"),
                        last_year=("iyear", "max"),
                    )
                    .reset_index()
                )
                unmatched_parts.append(unmatched)

            update_review_candidates(
                review_candidates,
                classified,
                n_per_class=review_per_class,
                seed=random_seed,
            )

            print(
                f"Chunk {chunk_number:,}: {input_rows:,} rows "
                f"(cumulative: {total_input_rows:,})"
            )

        if first_chunk:
            raise ValueError("The GTD input contains no data rows.")
        if total_input_rows != total_output_rows:
            raise RuntimeError(
                "Total GTD row count changed during classification."
            )

        temporary.replace(output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    write_diagnostics(
        output_dir=output_path.parent,
        status_counts=status_counts,
        country_year_parts=country_year_parts,
        unmatched_parts=unmatched_parts,
        review_candidates=review_candidates,
        country_cache=country_cache,
        total_rows=total_output_rows,
        output_path=output_path,
        reference_path=reference_path,
        near_capital_km=near_capital_km,
        conflict_km=conflict_km,
    )

    print()
    print("Dynamic capital classification completed")
    print(f"Input rows:  {total_input_rows:,}")
    print(f"Output rows: {total_output_rows:,}")
    print(f"Output:      {output_path}")
    print(f"Diagnostics: {output_path.parent}")


def main() -> None:
    logging.getLogger("country_converter").setLevel(logging.ERROR)
    args = parse_args()
    run_classification(
        gtd_input=args.gtd_input,
        reference_path=args.capital_reference,
        output_path=args.output,
        alias_file=args.alias_file,
        chunksize=args.chunksize,
        near_capital_km=args.near_capital_km,
        conflict_km=args.name_coordinate_conflict_km,
        review_per_class=args.review_per_class,
        random_seed=args.random_seed,
    )


if __name__ == "__main__":
    main()
