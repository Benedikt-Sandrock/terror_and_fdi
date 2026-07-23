from __future__ import annotations

"""
Validierung der historischen WUP-/GTD-Stadtklassifikation.

Voraussetzung:
    python geonames_cleaning.py
    python wup_dynamic_city_classification.py

Danach:
    python validate_wup_city_classification.py

Das Skript verändert den klassifizierten GTD-Datensatz nicht. Es prüft die
Klassifikationslogik und schreibt tabellarische Review-Dateien sowie eine
Markdown-Zusammenfassung nach
`INTERIM / "wup_city_classification" / "validation_controls"`.
"""

import argparse
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from terror_and_fdi.config import INTERIM, RAW


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_INPUT_DIR = INTERIM / "wup_city_classification"
DEFAULT_OUTPUT_DIR = DEFAULT_INPUT_DIR / "validation_controls"
DEFAULT_WUP_PATH = (
    RAW
    / "un_wup"
    / "WUP2025-DB-DEGURBA-Cities-Population-Surface-Data.csv.gz"
)

CLASSIFIED_GTD_FILENAME = "gtd_with_dynamic_city_groups.csv"
TOP4_FILENAME = "wup_top4_country_year.csv"
DIAGNOSTICS_FILENAME = "wup_top3_country_year_diagnostics.csv"
CITY_HISTORY_FILENAME = "wup_top3_city_history.csv"
UNMATCHED_FILENAME = "gtd_unmatched_city_review.csv"

START_YEAR = 1993
END_YEAR = 2020
EXPECTED_YEAR_COUNT = END_YEAR - START_YEAR + 1
FREQUENT_CHANGE_THRESHOLD = 3
COORD_REVIEW_THRESHOLD_KM = 20.0

SPECIAL_CHANGE_COUNTRIES = {"AGO", "LBR", "PRI", "SDN", "SSD", "THA", "UGA"}


# =============================================================================
# HELPERS
# =============================================================================

TRUE_VALUES = {"true", "1", "yes", "y", "t"}
FALSE_VALUES = {"false", "0", "no", "n", "f", ""}


def parse_bool(series: pd.Series, column: str) -> pd.Series:
    """Convert common CSV boolean encodings without treating 'False' as true."""
    if pd.api.types.is_bool_dtype(series.dtype):
        return series.fillna(False).astype(bool)

    normalized = series.astype("string").str.strip().str.lower()
    invalid = normalized.dropna().loc[
        ~normalized.dropna().isin(TRUE_VALUES | FALSE_VALUES)
    ]
    if not invalid.empty:
        examples = sorted(invalid.unique().tolist())[:10]
        raise ValueError(
            f"Spalte {column!r} enthält unbekannte Bool-Werte: {examples}"
        )
    return normalized.isin(TRUE_VALUES)


def require_columns(
    frame: pd.DataFrame,
    required: Iterable[str],
    filename: Path,
) -> None:
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(
            f"In {filename.name} fehlen Spalten: {sorted(missing)}"
        )


def atomic_to_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}.tmp{path.suffix}")
    frame.to_csv(temporary, index=False, encoding="utf-8")
    temporary.replace(path)


def atomic_write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}.tmp{path.suffix}")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def safe_pct(numerator: int | float, denominator: int | float) -> float:
    return 100 * numerator / denominator if denominator else math.nan


def numeric_sum(frame: pd.DataFrame, candidates: list[str]) -> pd.Series:
    """Return the first available numeric casualty column, otherwise zeros."""
    for column in candidates:
        if column in frame.columns:
            return pd.to_numeric(frame[column], errors="coerce").fillna(0)
    return pd.Series(0.0, index=frame.index)


def bool_equal(left: pd.Series, right: pd.Series) -> pd.Series:
    return left.fillna(False).astype(bool).eq(right.fillna(False).astype(bool))


def add_check(
    checks: list[dict[str, object]],
    name: str,
    passed: bool,
    affected_rows: int,
    detail: str,
    severity: str = "error",
) -> None:
    checks.append(
        {
            "check": name,
            "status": "PASS" if passed else "FAIL",
            "severity_if_failed": severity,
            "affected_rows": int(affected_rows),
            "detail": detail,
        }
    )


# =============================================================================
# CONTROLS
# =============================================================================

def integrity_controls(
    gtd: pd.DataFrame,
    top4: pd.DataFrame,
    diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    checks: list[dict[str, object]] = []

    add_check(
        checks,
        "GTD years in analysis window",
        bool(gtd["iyear"].between(START_YEAR, END_YEAR).all()),
        int((~gtd["iyear"].between(START_YEAR, END_YEAR)).sum()),
        f"Expected {START_YEAR}–{END_YEAR}.",
    )

    top4_duplicate = top4.duplicated(
        ["ISO3_Code", "Year", "population_rank"], keep=False
    )
    add_check(
        checks,
        "Unique top-4 rank per country-year",
        not top4_duplicate.any(),
        int(top4_duplicate.sum()),
        "Each ISO3 × year × population_rank must occur once.",
    )

    diagnostics_duplicate = diagnostics.duplicated(
        ["ISO3_Code", "Year"], keep=False
    )
    add_check(
        checks,
        "Unique diagnostics row per country-year",
        not diagnostics_duplicate.any(),
        int(diagnostics_duplicate.sum()),
        "Each ISO3 × year must occur once.",
    )

    rank_expected = pd.to_numeric(
        gtd["population_rank"], errors="coerce"
    ).le(3).fillna(False)
    mismatch = ~bool_equal(gtd["is_top3_dynamic_wup"], rank_expected)
    add_check(
        checks,
        "Dynamic WUP equals rank 1–3",
        not mismatch.any(),
        int(mismatch.sum()),
        "`is_top3_dynamic_wup` must equal population_rank <= 3.",
    )

    complete = gtd["top3_coverage_complete_bool"]
    expected_main = np.where(
        complete,
        gtd["is_top3_dynamic_wup"],
        gtd["is_top3_geonames_current"],
    ).astype(bool)
    mismatch = ~bool_equal(
        gtd["is_top3_main"], pd.Series(expected_main, index=gtd.index)
    )
    add_check(
        checks,
        "Main classification follows documented fallback",
        not mismatch.any(),
        int(mismatch.sum()),
        "Complete WUP coverage uses dynamic WUP; incomplete coverage uses "
        "static GeoNames.",
    )

    expected_source = np.where(
        complete,
        "wup_dynamic_complete",
        "geonames_static_fallback_incomplete_wup",
    )
    mismatch = gtd["top3_main_source"].astype("string").ne(expected_source)
    add_check(
        checks,
        "Fallback source marker is consistent",
        not mismatch.any(),
        int(mismatch.sum()),
        "`top3_main_source` must agree with `top3_coverage_complete`.",
    )

    mismatch = ~bool_equal(
        gtd["is_outside_top3_main"], ~gtd["is_top3_main"]
    )
    add_check(
        checks,
        "Outside-top3 is exact complement",
        not mismatch.any(),
        int(mismatch.sum()),
        "`is_outside_top3_main == ~is_top3_main`.",
    )

    mismatch = ~bool_equal(
        gtd["is_outside_capital_dynamic"], ~gtd["is_capital_dynamic"]
    )
    add_check(
        checks,
        "Outside-capital is exact complement",
        not mismatch.any(),
        int(mismatch.sum()),
        "`is_outside_capital_dynamic == ~is_capital_dynamic`.",
    )

    name_match_without_code = (
        gtd["wup_name_match"] & gtd["wup_city_code"].isna()
    )
    add_check(
        checks,
        "Name matches have a WUP city code",
        not name_match_without_code.any(),
        int(name_match_without_code.sum()),
        "Every successful name match needs `wup_city_code`.",
    )

    confident_without_code = (
        gtd["wup_coord_match_confident"]
        & gtd["wup_coord_city_code"].isna()
    )
    add_check(
        checks,
        "Confident coordinate matches have a WUP city code",
        not confident_without_code.any(),
        int(confident_without_code.sum()),
        "Every confident coordinate match needs `wup_coord_city_code`.",
    )

    return pd.DataFrame(checks)


def fallback_controls(
    gtd: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    fallback = gtd.loc[
        gtd["top3_main_source"].eq(
            "geonames_static_fallback_incomplete_wup"
        )
    ].copy()

    crosstab = (
        pd.crosstab(
            fallback["is_top3_dynamic_wup"],
            fallback["is_top3_main"],
            dropna=False,
        )
        .rename_axis(index="is_top3_dynamic_wup")
        .reset_index()
    )

    if fallback.empty:
        return crosstab, pd.DataFrame()

    fallback["fallback_changed_classification"] = (
        fallback["is_top3_dynamic_wup"] != fallback["is_top3_main"]
    )
    country = (
        fallback.groupby("ISO3", dropna=False)
        .agg(
            fallback_events=("is_top3_main", "size"),
            top3_dynamic_wup=("is_top3_dynamic_wup", "sum"),
            top3_main=("is_top3_main", "sum"),
            changed_events=("fallback_changed_classification", "sum"),
            unique_cities=("gtd_city_normalized", "nunique"),
        )
        .reset_index()
    )
    country["changed_share_pct"] = (
        100 * country["changed_events"] / country["fallback_events"]
    )
    country = country.sort_values(
        ["fallback_events", "ISO3"], ascending=[False, True]
    )
    return crosstab, country


def borderline_controls(
    gtd: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rank = pd.to_numeric(gtd["population_rank"], errors="coerce")
    borderline_year = gtd["top3_borderline_5pct"]
    directly_affected = borderline_year & rank.isin([3, 4])

    rows = gtd.loc[directly_affected].copy()
    if rows.empty:
        return pd.DataFrame(), pd.DataFrame()

    rows["population_rank"] = rank.loc[rows.index].astype("Int64")
    review = (
        rows.groupby(
            [
                "ISO3",
                "iyear",
                "population_rank",
                "wup_ranked_city_name",
                "wup_city_code",
            ],
            dropna=False,
        )
        .agg(
            event_count=("is_top3_main", "size"),
            main_top3_events=("is_top3_main", "sum"),
            gap_pct_rank3=("population_gap_3_4_pct_of_rank3", "first"),
            plausibility=("wup_population_plausibility", "first"),
        )
        .reset_index()
        .sort_values(
            ["event_count", "ISO3", "iyear"],
            ascending=[False, True, True],
        )
    )

    country = (
        rows.groupby("ISO3", dropna=False)
        .agg(
            directly_affected_events=("is_top3_main", "size"),
            rank3_events=("population_rank", lambda x: int(x.eq(3).sum())),
            rank4_events=("population_rank", lambda x: int(x.eq(4).sum())),
            affected_country_years=("iyear", "nunique"),
        )
        .reset_index()
        .sort_values(
            ["directly_affected_events", "ISO3"], ascending=[False, True]
        )
    )
    return review, country


def plausibility_controls(
    gtd: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rank = pd.to_numeric(gtd["population_rank"], errors="coerce")
    matched_top3 = gtd["is_top3_dynamic_wup"] & rank.le(3)
    city_low = (
        gtd["wup_population_plausibility"]
        .astype("string")
        .str.strip()
        .str.casefold()
        .eq("low")
    )

    gtd["is_top3_high_medium_quality"] = matched_top3 & ~city_low
    affected = gtd.loc[matched_top3 & city_low].copy()
    if affected.empty:
        return pd.DataFrame(), pd.DataFrame()

    event_review = (
        affected.groupby(
            [
                "ISO3",
                "iyear",
                "population_rank",
                "wup_ranked_city_name",
                "wup_city_code",
            ],
            dropna=False,
        )
        .agg(
            event_count=("is_top3_dynamic_wup", "size"),
            plausibility=("wup_population_plausibility", "first"),
        )
        .reset_index()
        .sort_values(
            ["event_count", "ISO3", "iyear"],
            ascending=[False, True, True],
        )
    )

    country = (
        affected.groupby("ISO3", dropna=False)
        .agg(
            low_quality_top3_events=("is_top3_dynamic_wup", "size"),
            low_quality_rank3_events=(
                "population_rank",
                lambda x: int(pd.to_numeric(x, errors="coerce").eq(3).sum()),
            ),
            affected_country_years=("iyear", "nunique"),
            affected_cities=("wup_city_code", "nunique"),
        )
        .reset_index()
        .sort_values(
            ["low_quality_top3_events", "ISO3"], ascending=[False, True]
        )
    )
    return event_review, country


def coordinate_controls(
    gtd: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = gtd.loc[gtd["wup_coord_distance_km"].notna()].copy()
    confident = candidates.loc[candidates["wup_coord_match_confident"]].copy()

    percentile_rows: list[dict[str, object]] = []
    for label, data in [
        ("all_nearest_candidates", candidates),
        ("confident_matches", confident),
    ]:
        distances = pd.to_numeric(
            data["wup_coord_distance_km"], errors="coerce"
        ).dropna()
        second = pd.to_numeric(
            data["wup_coord_second_distance_km"], errors="coerce"
        )
        margin = second - pd.to_numeric(
            data["wup_coord_distance_km"], errors="coerce"
        )
        row: dict[str, object] = {
            "group": label,
            "n": len(distances),
            "mean_km": distances.mean(),
            "max_km": distances.max(),
            "mean_margin_km": margin.mean(),
        }
        for quantile in [0.50, 0.75, 0.90, 0.95, 0.99]:
            row[f"p{int(quantile * 100)}_km"] = distances.quantile(quantile)
        percentile_rows.append(row)

    if confident.empty:
        near_threshold = pd.DataFrame()
    else:
        distance = pd.to_numeric(
            confident["wup_coord_distance_km"], errors="coerce"
        )
        margin = (
            pd.to_numeric(
                confident["wup_coord_second_distance_km"], errors="coerce"
            )
            - distance
        )
        confident["coord_distance_margin_km"] = margin
        columns = [
            column
            for column in [
                "eventid",
                "ISO3",
                "iyear",
                "city",
                "latitude",
                "longitude",
                "wup_coord_city_name",
                "wup_coord_city_code",
                "wup_coord_distance_km",
                "wup_coord_second_distance_km",
                "coord_distance_margin_km",
            ]
            if column in confident.columns
        ]
        near_threshold = confident.loc[
            distance.ge(COORD_REVIEW_THRESHOLD_KM), columns
        ].sort_values("wup_coord_distance_km", ascending=False)

    return pd.DataFrame(percentile_rows), near_threshold


def unmatched_controls(gtd: pd.DataFrame) -> pd.DataFrame:
    unmatched = gtd.loc[
        ~gtd["wup_name_match"] & gtd["gtd_city_normalized"].notna()
    ].copy()
    if unmatched.empty:
        return pd.DataFrame()

    unmatched["_deaths"] = numeric_sum(unmatched, ["nkill", "deaths"])
    unmatched["_wounded"] = numeric_sum(unmatched, ["nwound", "wounded"])
    unmatched["_casualties"] = unmatched["_deaths"] + unmatched["_wounded"]
    unmatched["_capital_event"] = unmatched["is_capital_dynamic"]
    unmatched["_geonames_top3_event"] = unmatched[
        "is_top3_geonames_current"
    ]
    unmatched["_coord_confident"] = unmatched["wup_coord_match_confident"]

    review = (
        unmatched.groupby(
            ["ISO3", "gtd_city_normalized"], dropna=False
        )
        .agg(
            event_count=("gtd_city_normalized", "size"),
            deaths=("_deaths", "sum"),
            wounded=("_wounded", "sum"),
            casualties=("_casualties", "sum"),
            capital_events=("_capital_event", "sum"),
            geonames_top3_events=("_geonames_top3_event", "sum"),
            confident_coord_matches=("_coord_confident", "sum"),
            first_year=("iyear", "min"),
            last_year=("iyear", "max"),
        )
        .reset_index()
    )
    review["priority_score"] = (
        review["event_count"]
        + 5 * review["capital_events"]
        + 3 * review["geonames_top3_events"]
        + np.log1p(review["casualties"])
    )
    return review.sort_values(
        ["priority_score", "event_count", "casualties"],
        ascending=False,
    )


def wup_coverage_controls(
    top4: pd.DataFrame,
    diagnostics: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    all_city_years = (
        top4.groupby(["ISO3_Code", "City_Code", "City_Name"], dropna=False)
        .agg(
            years_observed=("Year", "nunique"),
            first_year=("Year", "min"),
            last_year=("Year", "max"),
            best_rank=("population_rank", "min"),
            worst_rank=("population_rank", "max"),
        )
        .reset_index()
    )
    all_city_years["missing_years_within_1993_2020"] = (
        EXPECTED_YEAR_COUNT - all_city_years["years_observed"]
    )
    all_city_years["balanced_1993_2020"] = all_city_years[
        "years_observed"
    ].eq(EXPECTED_YEAR_COUNT)

    country = (
        diagnostics.groupby("ISO3_Code", dropna=False)
        .agg(
            country_years=("Year", "nunique"),
            complete_top3_years=("top3_coverage_complete_bool", "sum"),
            min_published_cities=("wup_city_count", "min"),
            max_published_cities=("wup_city_count", "max"),
            borderline_years=("top3_borderline_5pct_bool", "sum"),
            low_top3_years=("top3_any_low_plausibility_bool", "sum"),
            membership_change_years=("top3_membership_changed_bool", "sum"),
            order_change_years=("top3_order_changed_bool", "sum"),
        )
        .reset_index()
    )
    country["incomplete_top3_years"] = (
        country["country_years"] - country["complete_top3_years"]
    )
    country["complete_top3_share_pct"] = (
        100 * country["complete_top3_years"] / country["country_years"]
    )
    country = country.sort_values(
        ["incomplete_top3_years", "ISO3_Code"], ascending=[False, True]
    )
    return all_city_years, country


def raw_wup_coverage_controls(
    wup_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Check the full WUP city-year panel, not merely annual top-4 rows.

    Missing observations only before a city's first or after its last
    publication are consistent with a publication threshold. Internal gaps
    between first and last observation deserve closer inspection.
    """
    if not wup_path.exists():
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(
            [
                {
                    "check": "Full WUP source available",
                    "status": "SKIPPED",
                    "severity_if_failed": "warning",
                    "affected_rows": 0,
                    "detail": f"File not found: {wup_path}",
                }
            ]
        )

    pieces: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        wup_path,
        usecols=["ISO3_Code", "City_Code", "City_Name", "Year", "Pop"],
        chunksize=250_000,
        low_memory=False,
    ):
        year = pd.to_numeric(chunk["Year"], errors="coerce")
        selected = chunk.loc[year.between(START_YEAR, END_YEAR)].copy()
        if not selected.empty:
            pieces.append(selected)
    if not pieces:
        raise ValueError(
            f"Keine WUP-Zeilen für {START_YEAR}–{END_YEAR} in {wup_path}"
        )

    wup = pd.concat(pieces, ignore_index=True)
    wup["Year"] = pd.to_numeric(wup["Year"], errors="raise").astype(int)
    wup["City_Code"] = pd.to_numeric(
        wup["City_Code"], errors="raise"
    ).astype("int64")
    wup["Pop"] = pd.to_numeric(wup["Pop"], errors="coerce")

    duplicate = wup.duplicated(
        ["ISO3_Code", "City_Code", "Year"], keep=False
    )
    checks: list[dict[str, object]] = []
    add_check(
        checks,
        "Unique raw WUP city-years",
        not duplicate.any(),
        int(duplicate.sum()),
        "Each ISO3 × City_Code × Year must occur once in the source period.",
    )

    city = (
        wup.groupby(
            ["ISO3_Code", "City_Code", "City_Name"], dropna=False
        )
        .agg(
            years_observed=("Year", "nunique"),
            first_year=("Year", "min"),
            last_year=("Year", "max"),
            min_population_thousands=("Pop", "min"),
            max_population_thousands=("Pop", "max"),
        )
        .reset_index()
    )
    city["years_in_observed_span"] = (
        city["last_year"] - city["first_year"] + 1
    )
    city["internal_missing_years"] = (
        city["years_in_observed_span"] - city["years_observed"]
    )
    city["missing_years_before_first"] = city["first_year"] - START_YEAR
    city["missing_years_after_last"] = END_YEAR - city["last_year"]
    city["balanced_1993_2020"] = city["years_observed"].eq(
        EXPECTED_YEAR_COUNT
    )
    city["possible_publication_threshold_pattern"] = (
        city["internal_missing_years"].eq(0)
        & ~city["balanced_1993_2020"]
    )
    internal_gap_count = int(city["internal_missing_years"].gt(0).sum())
    add_check(
        checks,
        "No internal gaps in raw WUP city histories",
        internal_gap_count == 0,
        internal_gap_count,
        "Missing years at the beginning/end can reflect publication "
        "thresholds; gaps between first and last observation are suspicious.",
        severity="warning",
    )

    year = (
        wup.groupby("Year")
        .agg(
            published_city_years=("City_Code", "size"),
            distinct_cities=("City_Code", "nunique"),
            countries_or_territories=("ISO3_Code", "nunique"),
            missing_population=("Pop", lambda x: int(x.isna().sum())),
        )
        .reset_index()
        .sort_values("Year")
    )
    expected_years = set(range(START_YEAR, END_YEAR + 1))
    absent_years = sorted(expected_years - set(year["Year"]))
    add_check(
        checks,
        "All analysis years present in raw WUP",
        not absent_years,
        len(absent_years),
        f"Absent years: {absent_years or 'none'}",
    )

    checks.append(
        {
            "check": "Raw WUP period row count",
            "status": "INFO",
            "severity_if_failed": "none",
            "affected_rows": len(wup),
            "detail": (
                f"{len(wup):,} city-years, "
                f"{wup['City_Code'].nunique():,} distinct City_Code values."
            ),
        }
    )
    return (
        city.sort_values(
            ["internal_missing_years", "years_observed", "ISO3_Code"],
            ascending=[False, True, True],
        ),
        year,
        pd.DataFrame(checks),
    )


def change_controls(
    diagnostics: pd.DataFrame,
    top4: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    country = (
        diagnostics.groupby("ISO3_Code", dropna=False)
        .agg(
            membership_change_years=("top3_membership_changed_bool", "sum"),
            order_change_years=("top3_order_changed_bool", "sum"),
            borderline_years=("top3_borderline_5pct_bool", "sum"),
            tiny_gap_years=("top3_gap_tiny_1pct_bool", "sum"),
            low_plausibility_years=(
                "top3_any_low_plausibility_bool",
                "sum",
            ),
            min_gap_3_4_pct=(
                "population_gap_3_4_pct_of_rank3",
                "min",
            ),
            median_gap_3_4_pct=(
                "population_gap_3_4_pct_of_rank3",
                "median",
            ),
        )
        .reset_index()
    )
    country["special_review_country"] = country["ISO3_Code"].isin(
        SPECIAL_CHANGE_COUNTRIES
    )
    country = country.loc[
        country["membership_change_years"].ge(FREQUENT_CHANGE_THRESHOLD)
        | country["order_change_years"].ge(FREQUENT_CHANGE_THRESHOLD)
        | country["special_review_country"]
    ].sort_values(
        ["membership_change_years", "order_change_years", "ISO3_Code"],
        ascending=[False, False, True],
    )

    years = diagnostics.loc[
        diagnostics["top3_membership_changed_bool"]
        | diagnostics["top3_order_changed_bool"]
        | diagnostics["ISO3_Code"].isin(SPECIAL_CHANGE_COUNTRIES)
    ].copy()

    top4_names = (
        top4.sort_values(["ISO3_Code", "Year", "population_rank"])
        .groupby(["ISO3_Code", "Year"], as_index=False)
        .agg(
            top4_names=(
                "City_Name",
                lambda x: " | ".join(x.astype(str)),
            )
        )
    )
    years = years.merge(
        top4_names,
        on=["ISO3_Code", "Year"],
        how="left",
        validate="one_to_one",
    )
    keep = [
        "ISO3_Code",
        "Year",
        "top3_membership_changed",
        "top3_order_changed",
        "entered_city_codes",
        "exited_city_codes",
        "population_gap_3_4_pct_of_rank3",
        "top3_borderline_5pct",
        "top3_any_low_plausibility",
        "top4_names",
    ]
    keep = [column for column in keep if column in years.columns]
    return country, years[keep].sort_values(["ISO3_Code", "Year"])


# =============================================================================
# SUMMARY
# =============================================================================

def build_summary(
    gtd: pd.DataFrame,
    checks: pd.DataFrame,
    fallback_country: pd.DataFrame,
    borderline_review: pd.DataFrame,
    low_review: pd.DataFrame,
    coordinate_summary: pd.DataFrame,
    unmatched_review: pd.DataFrame,
    city_coverage: pd.DataFrame,
    raw_city_coverage: pd.DataFrame,
    raw_wup_checks: pd.DataFrame,
    country_changes: pd.DataFrame,
) -> str:
    n = len(gtd)
    fallback_mask = gtd["top3_main_source"].eq(
        "geonames_static_fallback_incomplete_wup"
    )
    fallback_changed = fallback_mask & (
        gtd["is_top3_dynamic_wup"] != gtd["is_top3_main"]
    )
    rank = pd.to_numeric(gtd["population_rank"], errors="coerce")
    borderline_year = gtd["top3_borderline_5pct"]
    directly_borderline = borderline_year & rank.isin([3, 4])
    low_matched_top3 = (
        gtd["is_top3_dynamic_wup"]
        & gtd["wup_population_plausibility"]
        .astype("string")
        .str.casefold()
        .eq("low")
    )
    failed = checks["status"].eq("FAIL")
    error_failures = failed & checks["severity_if_failed"].eq("error")

    confident = gtd["wup_coord_match_confident"]
    confident_distance = pd.to_numeric(
        gtd.loc[confident, "wup_coord_distance_km"], errors="coerce"
    )
    high_priority_unmatched = (
        int(
            (
                unmatched_review["capital_events"].gt(0)
                | unmatched_review["geonames_top3_events"].gt(0)
            ).sum()
        )
        if not unmatched_review.empty
        else 0
    )
    incomplete_city_histories = int(
        (~city_coverage["balanced_1993_2020"]).sum()
    )
    raw_internal_gaps = (
        int(raw_city_coverage["internal_missing_years"].gt(0).sum())
        if not raw_city_coverage.empty
        else 0
    )
    raw_balanced = (
        int(raw_city_coverage["balanced_1993_2020"].sum())
        if not raw_city_coverage.empty
        else 0
    )
    raw_source_status = (
        str(raw_wup_checks.iloc[0]["status"])
        if not raw_wup_checks.empty
        else "SKIPPED"
    )

    def fmt_pct(value: int) -> str:
        return f"{safe_pct(value, n):.2f}%"

    coord_p95 = (
        confident_distance.quantile(0.95)
        if not confident_distance.empty
        else math.nan
    )

    lines = [
        "# Validierung der WUP-Stadtklassifikation",
        "",
        f"Analysezeitraum: {START_YEAR}–{END_YEAR}",
        "",
        "## Ergebnis der technischen Integritätsprüfungen",
        "",
        f"- Prüfungen insgesamt: {len(checks):,}",
        f"- Fehlgeschlagene Prüfungen: {int(failed.sum()):,}",
        f"- Davon Fehler: {int(error_failures.sum()):,}",
        "- Gesamturteil: "
        + (
            "**technische Fehler beheben, bevor die Daten verwendet werden**"
            if error_failures.any()
            else "**keine Verletzung der geprüften Klassifikationsregeln**"
        ),
        "",
        "Details stehen in `integrity_checks.csv`.",
        "",
        "## 1. GeoNames-Rückfall",
        "",
        f"- Fallback-Ereignisse: {int(fallback_mask.sum()):,} "
        f"({fmt_pct(int(fallback_mask.sum()))})",
        f"- Tatsächlich gegenüber der reinen WUP-Variable geänderte Ereignisse: "
        f"{int(fallback_changed.sum()):,} "
        f"({fmt_pct(int(fallback_changed.sum()))})",
        f"- Betroffene Länder: {len(fallback_country):,}",
        "",
        "Eine kleine Differenz zwischen `is_top3_dynamic_wup` und "
        "`is_top3_main` ist plausibel, wenn die meisten Fallback-Ereignisse "
        "auch nach GeoNames außerhalb der Top 3 liegen.",
        "",
        "## 2. Knappe Ränge 3 und 4",
        "",
        f"- Alle Ereignisse in 5-%-Grenzfall-Land-Jahren: "
        f"{int(borderline_year.sum()):,} ({fmt_pct(int(borderline_year.sum()))})",
        f"- Davon tatsächlich in Rang-3- oder Rang-4-Städten: "
        f"{int(directly_borderline.sum()):,} "
        f"({fmt_pct(int(directly_borderline.sum()))})",
        f"- Aggregierte betroffene Stadt-Jahre: {len(borderline_review):,}",
        "",
        "Die zweite Zahl ist die engere und methodisch aussagekräftigere "
        "Unsicherheitskennzahl.",
        "",
        "## 3. WUP-Plausibilitätsstatus",
        "",
        f"- Dynamische Top-3-Ereignisse mit konkret gematchter `Low`-Stadt: "
        f"{int(low_matched_top3.sum()):,} "
        f"({fmt_pct(int(low_matched_top3.sum()))})",
        f"- Betroffene Stadt-Jahre: {len(low_review):,}",
        "",
        "`is_top3_high_medium_quality` wird intern als dynamische "
        "Top-3-Zuordnung ohne `Low`-Status berechnet; die aggregierten "
        "Ergebnisse stehen in den Plausibilitäts-Review-Dateien.",
        "",
        "## 4. Koordinatenmatches",
        "",
        f"- Sichere Koordinatenmatches: {int(confident.sum()):,} "
        f"({fmt_pct(int(confident.sum()))})",
        f"- 95. Perzentil der Distanz: {coord_p95:.2f} km"
        if not math.isnan(coord_p95)
        else "- 95. Perzentil der Distanz: keine sicheren Matches",
        f"- Matches ab {COORD_REVIEW_THRESHOLD_KM:g} km werden separat "
        "zur Sichtprüfung ausgegeben.",
        "",
        "## 5. Nicht erkannte Städtenamen",
        "",
        f"- Unterschiedliche nicht erkannte ISO3/Stadt-Kombinationen: "
        f"{len(unmatched_review):,}",
        f"- Prioritäre Kombinationen mit Hauptstadt- oder statischem "
        f"Top-3-Hinweis: {high_priority_unmatched:,}",
        "",
        "Die Datei ist nach einer Prioritätskennzahl aus Ereigniszahl, "
        "Opfern sowie Hauptstadt-/Top-3-Hinweisen sortiert.",
        "",
        "## 6. WUP-Abdeckung",
        "",
        f"- Top-4-Stadtverläufe mit weniger als {EXPECTED_YEAR_COUNT} "
        f"beobachteten Jahren: {incomplete_city_histories:,}",
        f"- Vollständige WUP-Stadtverläufe mit allen {EXPECTED_YEAR_COUNT} "
        f"Jahren: {raw_balanced:,}",
        f"- Vollständige WUP-Stadtverläufe mit internen Jahreslücken: "
        f"{raw_internal_gaps:,}",
        f"- Status der Rohdateiprüfung: {raw_source_status}",
        "",
        "Das ist nicht automatisch ein Fehler: `wup_top4_country_year.csv` "
        "enthält nur Städte, die in einem Jahr Rang 1–4 erreichen. Eine Stadt "
        "kann daher aus dieser Datei verschwinden, obwohl sie weiterhin in der "
        "vollständigen WUP-Datei vorhanden ist. Die separate Rohdateiprüfung "
        "unterscheidet fehlende Randjahre von verdächtigeren internen Lücken.",
        "",
        "## 7. Häufige Wechsel",
        "",
        f"- Länder in der vertieften Wechselprüfung: {len(country_changes):,}",
        "- Besondere Prüfung: AGO, LBR, PRI, SDN, SSD, THA, UGA.",
        "",
        "Für jedes Wechseljahr werden Top-4-Namen, Rangabstand, "
        "Plausibilitätsstatus sowie Ein- und Austritte ausgegeben. So lässt "
        "sich erkennen, ob Wechsel überwiegend bei sehr kleinen Abständen "
        "auftreten.",
        "",
        "## Ausgabedateien",
        "",
        "- `integrity_checks.csv`",
        "- `fallback_crosstab.csv`",
        "- `fallback_country_review.csv`",
        "- `borderline_rank3_rank4_review.csv`",
        "- `borderline_country_review.csv`",
        "- `low_plausibility_top3_review.csv`",
        "- `low_plausibility_country_review.csv`",
        "- `coordinate_distance_summary.csv`",
        "- `coordinate_matches_near_threshold.csv`",
        "- `unmatched_city_priority_review.csv`",
        "- `wup_top4_city_coverage_review.csv`",
        "- `wup_country_coverage_review.csv`",
        "- `raw_wup_city_coverage_review.csv`",
        "- `raw_wup_year_coverage_review.csv`",
        "- `raw_wup_integrity_checks.csv`",
        "- `frequent_change_country_review.csv`",
        "- `frequent_change_year_review.csv`",
    ]
    return "\n".join(lines) + "\n"


# =============================================================================
# MAIN
# =============================================================================

def load_inputs(
    input_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    gtd_path = input_dir / CLASSIFIED_GTD_FILENAME
    top4_path = input_dir / TOP4_FILENAME
    diagnostics_path = input_dir / DIAGNOSTICS_FILENAME

    for path in [gtd_path, top4_path, diagnostics_path]:
        if not path.exists():
            raise FileNotFoundError(
                f"Fehlende Eingabedatei: {path}\n"
                "Zuerst wup_dynamic_city_classification.py ausführen."
            )

    print(f"Lese {gtd_path.name} ...")
    gtd = pd.read_csv(gtd_path, low_memory=False)
    print(f"Lese {top4_path.name} ...")
    top4 = pd.read_csv(top4_path, low_memory=False)
    print(f"Lese {diagnostics_path.name} ...")
    diagnostics = pd.read_csv(diagnostics_path, low_memory=False)

    require_columns(
        gtd,
        {
            "ISO3",
            "iyear",
            "city",
            "gtd_city_normalized",
            "is_capital_dynamic",
            "is_outside_capital_dynamic",
            "is_top3_dynamic_wup",
            "is_top3_main",
            "is_outside_top3_main",
            "is_top3_geonames_current",
            "top3_main_source",
            "top3_coverage_complete",
            "top3_borderline_5pct",
            "population_rank",
            "wup_city_code",
            "wup_ranked_city_name",
            "wup_population_plausibility",
            "wup_name_match",
            "wup_coord_match_confident",
            "wup_coord_city_code",
            "wup_coord_distance_km",
            "wup_coord_second_distance_km",
        },
        gtd_path,
    )
    require_columns(
        top4,
        {
            "ISO3_Code",
            "Year",
            "City_Code",
            "City_Name",
            "population_rank",
        },
        top4_path,
    )
    require_columns(
        diagnostics,
        {
            "ISO3_Code",
            "Year",
            "wup_city_count",
            "top3_coverage_complete",
            "top3_borderline_5pct",
            "top3_gap_tiny_1pct",
            "top3_any_low_plausibility",
            "top3_membership_changed",
            "top3_order_changed",
            "population_gap_3_4_pct_of_rank3",
        },
        diagnostics_path,
    )

    gtd["iyear"] = pd.to_numeric(gtd["iyear"], errors="raise").astype(int)
    top4["Year"] = pd.to_numeric(top4["Year"], errors="raise").astype(int)
    diagnostics["Year"] = pd.to_numeric(
        diagnostics["Year"], errors="raise"
    ).astype(int)

    gtd_bool_columns = [
        "is_capital_dynamic",
        "is_outside_capital_dynamic",
        "is_top3_dynamic_wup",
        "is_top3_main",
        "is_outside_top3_main",
        "is_top3_geonames_current",
        "top3_coverage_complete",
        "top3_borderline_5pct",
        "wup_name_match",
        "wup_coord_match_confident",
    ]
    for column in gtd_bool_columns:
        gtd[column] = parse_bool(gtd[column], column)
    gtd["top3_coverage_complete_bool"] = gtd["top3_coverage_complete"]

    diagnostics_bool_columns = [
        "top3_coverage_complete",
        "top3_borderline_5pct",
        "top3_gap_tiny_1pct",
        "top3_any_low_plausibility",
        "top3_membership_changed",
        "top3_order_changed",
    ]
    for column in diagnostics_bool_columns:
        diagnostics[f"{column}_bool"] = parse_bool(
            diagnostics[column], column
        )

    return gtd, top4, diagnostics


def run_validation(
    input_dir: Path,
    output_dir: Path,
    wup_path: Path,
) -> None:
    gtd, top4, diagnostics = load_inputs(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Prüfe technische Konsistenz ...")
    checks = integrity_controls(gtd, top4, diagnostics)

    print("Prüfe GeoNames-Rückfall ...")
    fallback_crosstab, fallback_country = fallback_controls(gtd)

    print("Prüfe knappe Ränge 3 und 4 ...")
    borderline_review, borderline_country = borderline_controls(gtd)

    print("Prüfe Low-Plausibilitätsfälle ...")
    low_review, low_country = plausibility_controls(gtd)

    print("Prüfe Koordinatenmatches ...")
    coordinate_summary, coordinate_threshold = coordinate_controls(gtd)

    print("Priorisiere nicht erkannte Städtenamen ...")
    unmatched_review = unmatched_controls(gtd)

    print("Prüfe WUP-Abdeckung und Wechsel ...")
    city_coverage, country_coverage = wup_coverage_controls(
        top4, diagnostics
    )
    print("Prüfe vollständige WUP-Rohdatei ...")
    raw_city_coverage, raw_year_coverage, raw_wup_checks = (
        raw_wup_coverage_controls(wup_path)
    )
    change_country, change_year = change_controls(diagnostics, top4)

    outputs = {
        "integrity_checks.csv": checks,
        "fallback_crosstab.csv": fallback_crosstab,
        "fallback_country_review.csv": fallback_country,
        "borderline_rank3_rank4_review.csv": borderline_review,
        "borderline_country_review.csv": borderline_country,
        "low_plausibility_top3_review.csv": low_review,
        "low_plausibility_country_review.csv": low_country,
        "coordinate_distance_summary.csv": coordinate_summary,
        "coordinate_matches_near_threshold.csv": coordinate_threshold,
        "unmatched_city_priority_review.csv": unmatched_review,
        "wup_top4_city_coverage_review.csv": city_coverage,
        "wup_country_coverage_review.csv": country_coverage,
        "raw_wup_city_coverage_review.csv": raw_city_coverage,
        "raw_wup_year_coverage_review.csv": raw_year_coverage,
        "raw_wup_integrity_checks.csv": raw_wup_checks,
        "frequent_change_country_review.csv": change_country,
        "frequent_change_year_review.csv": change_year,
    }
    for filename, frame in outputs.items():
        atomic_to_csv(frame, output_dir / filename)

    summary = build_summary(
        gtd=gtd,
        checks=checks,
        fallback_country=fallback_country,
        borderline_review=borderline_review,
        low_review=low_review,
        coordinate_summary=coordinate_summary,
        unmatched_review=unmatched_review,
        city_coverage=city_coverage,
        raw_city_coverage=raw_city_coverage,
        raw_wup_checks=raw_wup_checks,
        country_changes=change_country,
    )
    atomic_write_text(summary, output_dir / "validation_summary.md")

    failed_errors = checks[
        checks["status"].eq("FAIL")
        & checks["severity_if_failed"].eq("error")
    ]
    print(f"Fertig. Ausgaben: {output_dir}")
    print(
        f"Integritätsprüfungen: {len(checks) - len(failed_errors)}/"
        f"{len(checks)} ohne Fehler"
    )
    if not failed_errors.empty:
        raise RuntimeError(
            "Mindestens eine technische Integritätsprüfung ist "
            "fehlgeschlagen. Details: integrity_checks.csv"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validiert die dynamische UN-WUP-/GTD-Klassifikation."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Ordner mit den Outputs der WUP-Klassifikation.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Zielordner für Kontrolltabellen und Summary.",
    )
    parser.add_argument(
        "--wup-file",
        type=Path,
        default=DEFAULT_WUP_PATH,
        help="Offizielle komprimierte WUP-Städtedatei für die Panelkontrolle.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run_validation(
        input_dir=arguments.input_dir,
        output_dir=arguments.output_dir,
        wup_path=arguments.wup_file,
    )
