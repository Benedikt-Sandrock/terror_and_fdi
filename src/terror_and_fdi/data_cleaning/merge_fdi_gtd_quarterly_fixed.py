"""
Merge cleaned quarterly IMF FDI data with quarterly GTD aggregates.

Result:
    - only countries with at least one GTD observation are retained
    - complete country-quarter grid for 1994-Q1 through 2020-Q4
    - quarters without GTD events receive zeros in terrorism variables
    - missing FDI observations remain missing (never replaced by zero)

Required merge keys in both inputs:
    ISO3, year, quarter

The GTD input should ideally already contain one row per country-quarter.
If duplicate country-quarter rows are present, numeric terrorism variables are summed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from terror_and_fdi.config import INTERIM, PROCESSED


# -----------------------------------------------------------------------------
# Paths and sample window
# -----------------------------------------------------------------------------
FDI_FILE = INTERIM / "quarterly" / "fdi_quarterly_imf_clean.csv"
GTD_FILE = INTERIM / "quarterly" /  "gtd_quarterly_terror.csv"  # adjust filename if needed

OUTPUT_CSV = PROCESSED / "fdi_gtd_quarterly_merged.csv"
OUTPUT_DTA = PROCESSED / "fdi_gtd_quarterly_merged.dta"
MERGE_DIAGNOSTICS_CSV = PROCESSED / "fdi_gtd_quarterly_merge_diagnostics.csv"

START_YEAR = 1994
END_YEAR = 2020
WRITE_STATA = True

MERGE_KEYS = ["ISO3", "year", "quarter"]

# Only columns matching these prefixes are automatically interpreted as
# terrorism counts/sums and filled with zero in no-attack quarters.
TERROR_PREFIXES = (
    "incidents_",
    "attacks_",
    "fatalities_",
    "deaths_",
    "killed_",
    "wounded_",
    "injured_",
    "hostages_",
    "casualties_",
)

# Exact variable names can be added here if they do not use a prefix above.
ADDITIONAL_TERROR_COLUMNS: list[str] = []


# -----------------------------------------------------------------------------
# File loading
# -----------------------------------------------------------------------------
def read_data(path: Path) -> pd.DataFrame:
    """Read CSV, Stata, or Parquet data."""
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".dta":
        return pd.read_stata(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)

    raise ValueError(f"Unsupported file type: {path.suffix}")


def normalize_keys(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Standardize and validate ISO3/year/quarter merge keys."""
    out = df.copy()

    # Accept old lowercase ISO3 naming, but standardize output to ISO3.
    if "ISO3" not in out.columns and "iso3" in out.columns:
        out = out.rename(columns={"iso3": "ISO3"})

    missing = set(MERGE_KEYS) - set(out.columns)
    if missing:
        raise ValueError(f"{name} is missing merge keys: {sorted(missing)}")

    out["ISO3"] = out["ISO3"].astype("string").str.strip().str.upper()
    out["year"] = pd.to_numeric(out["year"], errors="coerce")
    out["quarter"] = pd.to_numeric(out["quarter"], errors="coerce")

    # Drop invalid/non-country ISO3 values (for example IMF aggregates such as
    # "EURO AREA (EA)") instead of aborting the whole merge.
    invalid_iso3 = (
        out["ISO3"].isna()
        | ~out["ISO3"].str.fullmatch(r"[A-Z]{3}", na=False)
    )
    if invalid_iso3.any():
        invalid_values = sorted(
            out.loc[invalid_iso3, "ISO3"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )
        print(
            f"Dropping {invalid_iso3.sum():,} rows with invalid/non-country "
            f"ISO3 values from {name}: {invalid_values}"
        )
        out = out.loc[~invalid_iso3].copy()

    # Invalid years or quarters are genuine data errors and should still stop
    # execution.
    invalid_time = (
        out["year"].isna()
        | out["quarter"].isna()
        | ~out["quarter"].isin([1, 2, 3, 4])
    )
    if invalid_time.any():
        examples = out.loc[invalid_time, MERGE_KEYS].head(20)
        raise ValueError(f"Invalid year/quarter merge keys in {name}:\n{examples}")

    out["year"] = out["year"].astype("int16")
    out["quarter"] = out["quarter"].astype("int8")

    out = out[out["year"].between(START_YEAR, END_YEAR)].copy()
    return out


# -----------------------------------------------------------------------------
# GTD preparation
# -----------------------------------------------------------------------------
def identify_terror_columns(columns: Iterable[str]) -> list[str]:
    """Identify GTD count/sum variables that should be zero in empty quarters."""
    detected = [
        col
        for col in columns
        if col not in MERGE_KEYS
        and (
            col.lower().startswith(TERROR_PREFIXES)
            or col in ADDITIONAL_TERROR_COLUMNS
        )
    ]
    return sorted(set(detected))


def prepare_gtd(gtd: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Validate GTD data and ensure one row per country-quarter."""
    gtd = normalize_keys(gtd, "GTD data")

    terror_cols = identify_terror_columns(gtd.columns)
    if not terror_cols:
        raise ValueError(
            "No terrorism variables were detected. Add their names to "
            "ADDITIONAL_TERROR_COLUMNS or extend TERROR_PREFIXES."
        )

    # Convert terrorism measures to numeric before aggregation/filling.
    for col in terror_cols:
        gtd[col] = pd.to_numeric(gtd[col], errors="coerce")

    duplicate_keys = gtd.duplicated(MERGE_KEYS, keep=False)
    if duplicate_keys.any():
        print(
            f"GTD contains {duplicate_keys.sum():,} rows on duplicate country-quarter "
            "keys. Numeric terrorism variables will be summed."
        )
        gtd = (
            gtd.groupby(MERGE_KEYS, as_index=False, observed=True)[terror_cols]
            .sum(min_count=1)
        )
    else:
        # Keep only keys and terrorism variables. This avoids accidental overlap
        # with country names or diagnostic columns from the FDI dataset.
        gtd = gtd[MERGE_KEYS + terror_cols].copy()

    if gtd.duplicated(MERGE_KEYS).any():
        raise RuntimeError("GTD keys are still duplicated after aggregation.")

    return gtd, terror_cols


# -----------------------------------------------------------------------------
# Merge
# -----------------------------------------------------------------------------
def build_country_quarter_grid(gtd_countries: list[str]) -> pd.DataFrame:
    """Create every quarter in the sample window for each GTD country."""
    countries = pd.DataFrame({"ISO3": sorted(gtd_countries)})
    periods = pd.MultiIndex.from_product(
        [range(START_YEAR, END_YEAR + 1), range(1, 5)],
        names=["year", "quarter"],
    ).to_frame(index=False)

    grid = countries.merge(periods, how="cross")
    grid["year"] = grid["year"].astype("int16")
    grid["quarter"] = grid["quarter"].astype("int8")
    return grid


def merge_fdi_and_gtd(fdi: pd.DataFrame, gtd: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create balanced country-quarter grid and merge FDI and GTD data."""
    fdi = normalize_keys(fdi, "FDI data")
    gtd, terror_cols = prepare_gtd(gtd)

    if fdi.duplicated(MERGE_KEYS).any():
        examples = fdi.loc[fdi.duplicated(MERGE_KEYS, keep=False), MERGE_KEYS].head(20)
        raise ValueError(f"FDI data contain duplicate merge keys:\n{examples}")

    # Requirement 1: countries are defined by actual presence in GTD.
    gtd_countries = sorted(gtd["ISO3"].dropna().unique())
    fdi = fdi[fdi["ISO3"].isin(gtd_countries)].copy()

    grid = build_country_quarter_grid(gtd_countries)

    # Merge FDI first. Quarters/countries without FDI remain missing.
    merged = grid.merge(
        fdi,
        on=MERGE_KEYS,
        how="left",
        validate="one_to_one",
        indicator="_fdi_merge",
    )
    merged["has_fdi_observation"] = merged["_fdi_merge"].eq("both").astype("int8")
    merged = merged.drop(columns="_fdi_merge")

    # Merge GTD next. Completely absent GTD quarters are genuine zero-event quarters.
    merged = merged.merge(
        gtd,
        on=MERGE_KEYS,
        how="left",
        validate="one_to_one",
        indicator="_gtd_merge",
    )
    merged["has_gtd_row"] = merged["_gtd_merge"].eq("both").astype("int8")
    merged = merged.drop(columns="_gtd_merge")

    # Requirement 2: fill only terrorism measures, never FDI measures.
    merged[terror_cols] = merged[terror_cols].fillna(0)

    # Counts and summed event variables are generally integers. Use nullable
    # integer type only where all observed values are integer-valued.
    for col in terror_cols:
        values = merged[col]
        if ((values % 1) == 0).all():
            merged[col] = values.astype("int64")

    merged["time_period"] = (
        merged["year"].astype(str) + "-Q" + merged["quarter"].astype(str)
    )

    # Put keys first, then identifiers/flags, then remaining variables.
    first_cols = [
        "ISO3",
        "year",
        "quarter",
        "time_period",
        "has_fdi_observation",
        "has_gtd_row",
    ]
    first_cols += [c for c in terror_cols if c not in first_cols]
    other_cols = [c for c in merged.columns if c not in first_cols]
    merged = merged[first_cols + other_cols].sort_values(MERGE_KEYS).reset_index(drop=True)

    diagnostics = pd.DataFrame(
        {
            "statistic": [
                "gtd_countries",
                "country_quarters_in_grid",
                "quarters_with_fdi_observation",
                "quarters_without_fdi_observation",
                "quarters_with_gtd_row",
                "zero_event_quarters_created_or_filled",
            ],
            "value": [
                len(gtd_countries),
                len(merged),
                int(merged["has_fdi_observation"].sum()),
                int((merged["has_fdi_observation"] == 0).sum()),
                int(merged["has_gtd_row"].sum()),
                int((merged["has_gtd_row"] == 0).sum()),
            ],
        }
    )

    print(f"GTD countries retained: {len(gtd_countries):,}")
    print(f"Final country-quarter rows: {len(merged):,}")
    print(f"Terrorism variables filled with zero: {terror_cols}")
    print(
        "FDI values were not filled: "
        f"{(merged['has_fdi_observation'] == 0).sum():,} grid rows have no FDI observation."
    )

    return merged, diagnostics


# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------
def write_outputs(merged: pd.DataFrame, diagnostics: pd.DataFrame) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    merged.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    diagnostics.to_csv(MERGE_DIAGNOSTICS_CSV, index=False, encoding="utf-8")

    if WRITE_STATA:
        try:
            stata = merged.copy()
            # pandas/Stata cannot export pandas StringDtype reliably in every version.
            for col in stata.select_dtypes(include="string").columns:
                stata[col] = stata[col].astype(object)
            stata.to_stata(OUTPUT_DTA, write_index=False, version=118)
        except Exception as exc:
            print(f"Warning: Stata export failed: {exc}")

    print("\nSaved:")
    print(f"  {OUTPUT_CSV}")
    if WRITE_STATA:
        print(f"  {OUTPUT_DTA}")
    print(f"  {MERGE_DIAGNOSTICS_CSV}")


def main() -> None:
    fdi = read_data(FDI_FILE)
    gtd = read_data(GTD_FILE)
    merged, diagnostics = merge_fdi_and_gtd(fdi, gtd)
    write_outputs(merged, diagnostics)


if __name__ == "__main__":
    main()
