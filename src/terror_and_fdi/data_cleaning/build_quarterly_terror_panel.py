from __future__ import annotations

"""Aggregate the validated event-level GTD classifications by country-quarter.

The capital split is the main specification; the GHS TOP3 split is a
robustness specification. Every event with a resolved ISO3 code and a valid
year/month contributes to the total outcomes, even when it cannot be assigned
to one of the two location splits.

The output intentionally contains only country-quarters observed in the GTD.
The complete analysis panel should later be constructed from the FDI data and
the terror variables added by a left merge. Missing terror quarters can then
be set to zero without creating observations outside a country's FDI coverage.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from terror_and_fdi.config import INTERIM


INPUT_FILE = (
    INTERIM
    / "ghs_ucdb_classification"
    / "gtd_with_ghs_city_groups.csv"
)
OUTPUT_DIR = INTERIM / "quarterly"
OUTPUT_CSV = OUTPUT_DIR / "gtd_quarterly_terror.csv"
OUTPUT_DTA = OUTPUT_DIR / "gtd_quarterly_terror.dta"
SUMMARY_FILE = OUTPUT_DIR / "gtd_quarterly_terror_summary.txt"

KEY_COLUMNS = ["ISO3", "year", "quarter"]

# Short suffixes keep every Stata variable name below the 32-character limit.
LOCATION_SUFFIXES = {
    "total": "total",
    "capital": "capital",
    "outside_capital": "outside_capital",
    "capital_unknown": "capital_unknown",
    "top3": "top3",
    "outside_top3": "outside_top3",
    "top3_unknown": "top3_unknown",
}

MEASURES = [
    "attacks",
    "successful",
    "fatalities",
    "wounded",
    "casualties",
    "business_target",
]


def nullable_binary(series: pd.Series, column_name: str) -> pd.Series:
    """Convert common representations of 1/0/true/false to nullable Int8."""
    numeric = pd.to_numeric(series, errors="coerce")
    text = series.astype("string").str.strip().str.lower()

    result = pd.Series(pd.NA, index=series.index, dtype="Int8")
    result.loc[numeric.eq(1) | text.isin({"true", "yes"})] = 1
    result.loc[numeric.eq(0) | text.isin({"false", "no"})] = 0

    nonmissing_input = series.notna() & text.ne("")
    invalid = nonmissing_input & result.isna()
    if invalid.any():
        examples = sorted(series.loc[invalid].astype(str).unique())[:10]
        raise ValueError(
            f"Invalid values in {column_name}: {examples}"
        )
    return result


def modal_country_name(values: pd.Series) -> str | pd.NA:
    values = values.dropna().astype("string").str.strip()
    values = values.loc[values.ne("")]
    if values.empty:
        return pd.NA
    modes = values.mode()
    return str(modes.iloc[0])


def validate_required_columns(df: pd.DataFrame) -> None:
    required = {
        "ISO3",
        "country_txt",
        "iyear",
        "imonth",
        "success",
        "targtype1",
        "nkill",
        "nwound",
        "is_capital_dynamic",
        "is_top3_ghs_urban_centre",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in GTD input: {sorted(missing)}")


def prepare_events(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    validate_required_columns(df)
    diagnostics: dict[str, int] = {"input_events": len(df)}

    iso3 = df["ISO3"].astype("string").str.strip().str.upper()
    valid_iso3 = iso3.str.fullmatch(r"[A-Z]{3}", na=False)

    year = pd.to_numeric(df["iyear"], errors="coerce")
    month = pd.to_numeric(df["imonth"], errors="coerce")
    valid_year = year.notna() & year.between(1993, 2020)
    valid_month = month.between(1, 12)

    diagnostics["events_without_valid_iso3"] = int((~valid_iso3).sum())
    diagnostics["events_without_valid_year"] = int((~valid_year).sum())
    diagnostics["events_without_valid_month"] = int((~valid_month).sum())

    usable = valid_iso3 & valid_year & valid_month
    diagnostics["events_in_quarterly_aggregation"] = int(usable.sum())
    diagnostics["events_excluded_from_aggregation"] = int((~usable).sum())

    result = df.loc[usable].copy()
    result["ISO3"] = iso3.loc[usable]
    result["year"] = year.loc[usable].astype(int)
    result["quarter"] = ((month.loc[usable].astype(int) - 1) // 3 + 1)

    if "eventid" in result.columns:
        duplicate_eventids = result["eventid"].duplicated(keep=False)
        if duplicate_eventids.any():
            examples = result.loc[duplicate_eventids, "eventid"].head(10).tolist()
            raise ValueError(f"Duplicate eventid values found: {examples}")

    result["_capital"] = nullable_binary(
        result["is_capital_dynamic"], "is_capital_dynamic"
    )
    result["_top3"] = nullable_binary(
        result["is_top3_ghs_urban_centre"],
        "is_top3_ghs_urban_centre",
    )

    nkill = pd.to_numeric(result["nkill"], errors="coerce")
    nwound = pd.to_numeric(result["nwound"], errors="coerce")
    diagnostics["events_missing_nkill"] = int(nkill.isna().sum())
    diagnostics["events_missing_nwound"] = int(nwound.isna().sum())
    diagnostics["events_capital_unknown"] = int(result["_capital"].isna().sum())
    diagnostics["events_top3_unknown"] = int(result["_top3"].isna().sum())

    # GTD missing values are set to zero only for sums. Their frequency remains
    # visible in the missing_nkill_* and missing_nwound_* diagnostics.
    result["attacks"] = 1
    result["successful"] = (
        pd.to_numeric(result["success"], errors="coerce").eq(1).astype(int)
    )
    result["fatalities"] = nkill.fillna(0)
    result["wounded"] = nwound.fillna(0)
    result["casualties"] = result["fatalities"] + result["wounded"]
    result["business_target"] = (
        pd.to_numeric(result["targtype1"], errors="coerce").eq(1).astype(int)
    )
    result["missing_nkill"] = nkill.isna().astype(int)
    result["missing_nwound"] = nwound.isna().astype(int)

    return result, diagnostics


def location_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "total": pd.Series(True, index=df.index),
        "capital": df["_capital"].eq(1),
        "outside_capital": df["_capital"].eq(0),
        "capital_unknown": df["_capital"].isna(),
        "top3": df["_top3"].eq(1),
        "outside_top3": df["_top3"].eq(0),
        "top3_unknown": df["_top3"].isna(),
    }


def add_split_columns(df: pd.DataFrame) -> list[str]:
    masks = location_masks(df)
    base_variables = MEASURES + ["missing_nkill", "missing_nwound"]
    value_columns: list[str] = []

    for variable in base_variables:
        for location, suffix in LOCATION_SUFFIXES.items():
            output_column = f"{variable}_{suffix}"
            if len(output_column) > 32:
                raise ValueError(
                    f"Stata variable name is too long: {output_column}"
                )
            df[output_column] = df[variable].where(masks[location], 0)
            value_columns.append(output_column)

    return value_columns


def validate_aggregation(quarterly: pd.DataFrame) -> None:
    variables = MEASURES + ["missing_nkill", "missing_nwound"]
    for variable in variables:
        total = quarterly[f"{variable}_total"]
        capital_partition = (
            quarterly[f"{variable}_capital"]
            + quarterly[f"{variable}_outside_capital"]
            + quarterly[f"{variable}_capital_unknown"]
        )
        top3_partition = (
            quarterly[f"{variable}_top3"]
            + quarterly[f"{variable}_outside_top3"]
            + quarterly[f"{variable}_top3_unknown"]
        )
        if not np.allclose(total, capital_partition, equal_nan=True):
            raise RuntimeError(
                f"Capital partition does not sum to total for {variable}."
            )
        if not np.allclose(total, top3_partition, equal_nan=True):
            raise RuntimeError(
                f"TOP3 partition does not sum to total for {variable}."
            )

    if quarterly.duplicated(KEY_COLUMNS).any():
        raise RuntimeError("Duplicate ISO3-year-quarter rows in output.")


def aggregate_quarterly(df: pd.DataFrame) -> pd.DataFrame:
    value_columns = add_split_columns(df)

    country_names = (
        df.groupby("ISO3", observed=True)["country_txt"]
        .agg(modal_country_name)
        .rename("country_txt")
    )

    quarterly = (
        df.groupby(KEY_COLUMNS, observed=True, sort=True)[value_columns]
        .sum()
        .reset_index()
        .merge(
            country_names,
            left_on="ISO3",
            right_index=True,
            how="left",
            validate="many_to_one",
        )
    )
    quarterly = quarterly[
        ["ISO3", "country_txt", "year", "quarter", *value_columns]
    ]

    # Counts and GTD outcomes should be integral. Fail instead of silently
    # rounding unexpected fractional values.
    for column in value_columns:
        values = pd.to_numeric(quarterly[column], errors="raise")
        if not np.allclose(values, np.round(values), equal_nan=True):
            raise ValueError(f"Non-integral aggregated values in {column}.")
        quarterly[column] = np.round(values).astype("int64")

    validate_aggregation(quarterly)
    return quarterly.sort_values(KEY_COLUMNS).reset_index(drop=True)


def build_summary(
    events: pd.DataFrame,
    quarterly: pd.DataFrame,
    diagnostics: dict[str, int],
) -> str:
    lines = [
        "Quarterly GTD terror aggregation summary",
        "=" * 40,
        "",
        f"Input: {INPUT_FILE}",
        f"Output CSV: {OUTPUT_CSV}",
        f"Output Stata: {OUTPUT_DTA}",
        "",
    ]
    lines.extend(
        f"{key}: {value:,}" for key, value in diagnostics.items()
    )
    lines.extend(
        [
            "",
            f"Countries in output: {quarterly['ISO3'].nunique():,}",
            f"Observed country-quarters: {len(quarterly):,}",
            f"Years: {quarterly['year'].min()}-{quarterly['year'].max()}",
            f"Attacks in output: {quarterly['attacks_total'].sum():,}",
            "",
            "Analytical identities checked:",
            "total = capital + outside_capital + capital_unknown",
            "total = top3 + outside_top3 + top3_unknown",
            "",
            "Missing nkill/nwound values contribute zero to the corresponding",
            "outcome sum but are counted separately in missing_nkill_* and",
            "missing_nwound_* variables.",
            "",
            "No zero-attack quarters were created. Use the FDI panel as the",
            "base for the next merge and fill missing terror outcomes with 0.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"GTD input not found: {INPUT_FILE}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(INPUT_FILE, low_memory=False)
    events, diagnostics = prepare_events(raw)
    if events.empty:
        raise ValueError("No GTD events remain after validating ISO3 and date.")

    quarterly = aggregate_quarterly(events)
    quarterly.to_csv(OUTPUT_CSV, index=False)
    quarterly.to_stata(OUTPUT_DTA, write_index=False, version=118)
    SUMMARY_FILE.write_text(
        build_summary(events, quarterly, diagnostics),
        encoding="utf-8",
    )

    print(f"Quarterly rows: {len(quarterly):,}")
    print(f"Countries: {quarterly['ISO3'].nunique():,}")
    print(f"CSV saved: {OUTPUT_CSV}")
    print(f"Stata file saved: {OUTPUT_DTA}")
    print(f"Summary saved: {SUMMARY_FILE}")


if __name__ == "__main__":
    main()
