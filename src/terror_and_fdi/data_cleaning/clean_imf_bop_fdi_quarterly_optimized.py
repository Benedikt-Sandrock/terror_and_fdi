"""
clean_imf_bop_fdi_quarterly.py

Prepare quarterly IMF Balance of Payments (BOP) Direct Investment data
for merging with GTD country-quarter terrorism data.

Input expected from IMF export with columns:
    COUNTRY
    BOP_ACCOUNTING_ENTRY
    INDICATOR
    UNIT
    FREQUENCY
    TIME_PERIOD
    OBS_VALUE
    SCALE

Output:
    - one row per country-quarter
    - ISO3 country code for merging
    - FDI inflows, outflows, and IMF net in million USD

Interpretation:
    fdi_inflow_musd  = Liabilities, Net incurrence of liabilities
    fdi_outflow_musd = Assets, Net acquisition of financial assets
    fdi_net_imf_musd = Net = Assets - Liabilities

Optional convenience variable:
    fdi_net_inflow_musd = Liabilities - Assets = -fdi_net_imf_musd

Author: generated for quarterly FDI/GTD merge workflow
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from terror_and_fdi.config import RAW, INTERIM

import pandas as pd

# ---------------------------------------------------------------------
# Paths: adapt if needed
# ---------------------------------------------------------------------
INPUT_FILE = RAW / "imf" /  "fdi_data_quarterly.csv"


OUTPUT_CSV = INTERIM / "quarterly" / "fdi_quarterly_imf_clean.csv"
OUTPUT_DTA = INTERIM / "quarterly" / "fdi_quarterly_imf_clean.dta"
COUNTRY_ISSUES_CSV = INTERIM / "quarterly" / "fdi_quarterly_imf_country_code_issues.csv"
SUMMARY_CSV = INTERIM / "quarterly" / "fdi_quarterly_imf_availability_summary.csv"

# Restrict to the GTD analysis window. Set to None if you want all quarters.
START_PERIOD: Optional[str] = "1994-Q1"
END_PERIOD: Optional[str] = "2020-Q4"

# Keep values in million USD.
# In this IMF export, SCALE is mixed: many rows say "Millions", while some rows
# have SCALE missing and OBS_VALUE is plain USD. The script normalizes both to MUSD.
# If you prefer plain USD in the final output, set MULTIPLY_TO_USD = True.
MULTIPLY_TO_USD = False

# Optional: restrict IMF observations to countries present in the GTD data.
# Leave as None to keep all IMF countries.
GTD_COUNTRY_FILE: Optional[Path] = None
GTD_ISO3_COLUMN = "ISO3"


# ---------------------------------------------------------------------
# IMF labels used in the downloaded file
# ---------------------------------------------------------------------
ENTRY_TO_VARIABLE = {
    "Liabilities, Net incurrence of liabilities": "fdi_inflow_musd",
    "Assets, Net acquisition of financial assets": "fdi_outflow_musd",
    "Net (net acquisition of financial assets less net incurrence of liabilities), Transactions": "fdi_net_imf_musd",
}

EXPECTED_INDICATOR = "Direct investment, Total financial assets/liabilities"
EXPECTED_FREQUENCY = "Quarterly"
EXPECTED_UNIT = "US dollar"

# Manual ISO3 fixes for names that converters often miss or treat differently.
# Add to this dictionary if the country issues file flags additional cases.
MANUAL_ISO3 = {
    "Afghanistan, Islamic Republic of": "AFG",
    "Armenia, Republic of": "ARM",
    "Aruba, Kingdom of the Netherlands": "ABW",
    "Azerbaijan, Republic of": "AZE",
    "Bahrain, Kingdom of": "BHR",
    "Belarus, Republic of": "BLR",
    "Bahamas, The": "BHS",
    "Bolivia": "BOL",
    "Brunei Darussalam": "BRN",
    "Congo, Democratic Republic of the": "COD",
    "Congo, Republic of": "COG",
    "Curaçao, Kingdom of the Netherlands": "CUW",
    "Czech Republic": "CZE",
    "China, People's Republic of": "CHN",
    "Croatia, Republic of": "HRV",
    "Estonia, Republic of": "EST",
    "Eswatini, Kingdom of": "SWZ",
    "Ethiopia, The Federal Democratic Republic of": "ETH",
    "Egypt, Arab Republic of": "EGY",
    "Eritrea, The State of": "ERI",
    "Fiji, Republic of": "FJI",
    "Gambia, The": "GMB",
    "Hong Kong Special Administrative Region, People's Republic of China": "HKG",
    "Iran, Islamic Republic of": "IRN",
    "Kazakhstan, Republic of": "KAZ",
    "Kosovo, Republic of": "XKX",
    "Latvia, Republic of": "LVA",
    "Lesotho, Kingdom of": "LSO",
    "Lithuania, Republic of": "LTU",
    "Korea, Republic of": "KOR",
    "Kyrgyz Republic": "KGZ",
    "Lao People's Democratic Republic": "LAO",
    "Madagascar, Republic of": "MDG",
    "Mauritania, Islamic Republic of": "MRT",
    "Mozambique, Republic of": "MOZ",
    "Micronesia, Federated States of": "FSM",
    "Moldova, Republic of": "MDA",
    "Netherlands, The": "NLD",
    "North Macedonia, Republic of": "MKD",
    "Poland, Republic of": "POL",
    "Serbia, Republic of": "SRB",
    "Slovenia, Republic of": "SVN",
    "Tajikistan, Republic of": "TJK",
    "Timor-Leste, Democratic Republic of": "TLS",
    "Russia": "RUS",
    "Sint Maarten, Kingdom of the Netherlands": "SXM",
    "Slovak Republic": "SVK",
    "São Tomé and Príncipe, Democratic Republic of": "STP",
    "Tanzania, United Republic of": "TZA",
    "Türkiye, Republic of": "TUR",
    "United States": "USA",
    "Uzbekistan, Republic of": "UZB",
    "Venezuela, República Bolivariana de": "VEN",
    "Viet Nam": "VNM",
    "West Bank and Gaza": "PSE",
    "Yemen, Republic of": "YEM",
}


def period_to_index(period: str) -> int:
    """Convert 'YYYY-Qn' to a sortable integer YYYY*4 + quarter."""
    m = re.fullmatch(r"(\d{4})-Q([1-4])", str(period))
    if not m:
        raise ValueError(f"Invalid quarterly TIME_PERIOD: {period!r}")
    year = int(m.group(1))
    quarter = int(m.group(2))
    return year * 4 + quarter


def add_time_variables(df: pd.DataFrame) -> pd.DataFrame:
    """Add year, quarter, quarter_start_month, and sortable period index."""
    out = df.copy()
    extracted = out["time_period"].str.extract(r"^(\d{4})-Q([1-4])$")
    out["year"] = extracted[0].astype("int16")
    out["quarter"] = extracted[1].astype("int8")
    out["quarter_start_month"] = ((out["quarter"] - 1) * 3 + 1).astype("int8")
    out["period_index"] = out["year"].astype(int) * 4 + out["quarter"].astype(int)
    return out


def build_country_iso3_map(countries: pd.Series) -> dict[str, Optional[str]]:
    """Build one country-name -> ISO3 map.

    country_converter is called once for all unresolved unique names, never once
    per observation or country-quarter.
    """
    unique_countries = (
        countries.dropna().astype(str).str.strip().drop_duplicates().tolist()
    )

    mapping: dict[str, Optional[str]] = {
        country: MANUAL_ISO3.get(country) for country in unique_countries
    }
    unresolved = [country for country, iso3 in mapping.items() if iso3 is None]

    if unresolved:
        try:
            import country_converter as coco  # type: ignore

            # One vectorized call for all unresolved country names.
            converted = coco.convert(
                names=unresolved,
                to="ISO3",
                not_found=None,
            )
            if isinstance(converted, str):
                converted = [converted]

            for country, iso3 in zip(unresolved, converted):
                if iso3 is not None and str(iso3).lower() != "not found":
                    mapping[country] = str(iso3).upper()
        except Exception as exc:
            print(f"Warning: country_converter batch conversion failed: {exc}")

    # Fallback only for still-unresolved unique country names.
    still_unresolved = [country for country, iso3 in mapping.items() if iso3 is None]
    if still_unresolved:
        try:
            import pycountry  # type: ignore

            for country in still_unresolved:
                try:
                    mapping[country] = pycountry.countries.lookup(country).alpha_3
                except LookupError:
                    pass
        except ImportError:
            pass

    print(
        f"ISO3 map created for {len(unique_countries):,} unique country names; "
        f"{sum(value is None for value in mapping.values()):,} unresolved."
    )
    return mapping


def load_gtd_iso3_values(path: Optional[Path]) -> Optional[set[str]]:
    """Load unique ISO3 values from an optional GTD CSV, DTA, or Parquet file."""
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"GTD country file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        gtd = pd.read_csv(path, usecols=[GTD_ISO3_COLUMN])
    elif suffix == ".dta":
        gtd = pd.read_stata(path, columns=[GTD_ISO3_COLUMN])
    elif suffix in {".parquet", ".pq"}:
        gtd = pd.read_parquet(path, columns=[GTD_ISO3_COLUMN])
    else:
        raise ValueError("GTD_COUNTRY_FILE must be CSV, DTA, or Parquet.")

    iso3 = (
        gtd[GTD_ISO3_COLUMN]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
    )
    values = set(iso3[iso3.str.fullmatch(r"[A-Z]{3}")])
    print(f"Loaded {len(values):,} unique GTD ISO3 codes from {path}")
    return values


def load_and_clean_imf_fdi(input_file: Path) -> pd.DataFrame:
    """Load IMF-BOP FDI export and return country-quarter panel in wide format."""
    df = pd.read_csv(input_file)

    # Standardize column names internally.
    df.columns = [c.strip().upper() for c in df.columns]

    required = {
        "COUNTRY",
        "BOP_ACCOUNTING_ENTRY",
        "INDICATOR",
        "UNIT",
        "FREQUENCY",
        "TIME_PERIOD",
        "OBS_VALUE",
        "SCALE",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    # Drop IMF placeholder rows with no period/value.
    df = df.dropna(subset=["COUNTRY", "TIME_PERIOD", "OBS_VALUE"]).copy()

    # Keep only the intended quarterly direct-investment observations.
    df = df[df["INDICATOR"].eq(EXPECTED_INDICATOR)].copy()
    df = df[df["FREQUENCY"].eq(EXPECTED_FREQUENCY)].copy()
    df = df[df["UNIT"].eq(EXPECTED_UNIT)].copy()
    df = df[df["BOP_ACCOUNTING_ENTRY"].isin(ENTRY_TO_VARIABLE)].copy()

    if df.empty:
        raise ValueError("No observations left after filtering. Check indicator/frequency/unit labels.")

    # Normalize scale.
    # - SCALE == "Millions": OBS_VALUE is already in million USD.
    # - SCALE missing: in this IMF export, OBS_VALUE is plain USD, so divide by 1,000,000.
    # This matters for countries such as Germany, Denmark, Colombia, Costa Rica, etc.
    non_missing_scales = set(df["SCALE"].dropna().unique())
    unexpected_scales = non_missing_scales - {"Millions"}
    if unexpected_scales:
        raise ValueError(f"Unexpected SCALE values: {sorted(unexpected_scales)}")

    df["obs_value_raw"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    df = df.dropna(subset=["obs_value_raw"]).copy()

    scale_missing = df["SCALE"].isna()
    df["value_musd"] = df["obs_value_raw"]
    df.loc[scale_missing, "value_musd"] = df.loc[scale_missing, "obs_value_raw"] / 1_000_000

    if MULTIPLY_TO_USD:
        df["value"] = df["value_musd"] * 1_000_000
        variable_suffix = "usd"
    else:
        df["value"] = df["value_musd"]
        variable_suffix = "musd"

    print(f"Rows with SCALE missing treated as plain USD and converted: {scale_missing.sum():,}")

    df["variable"] = df["BOP_ACCOUNTING_ENTRY"].map(ENTRY_TO_VARIABLE)
    if MULTIPLY_TO_USD:
        df["variable"] = df["variable"].str.replace("_musd", "_usd", regex=False)

    df = df.rename(
        columns={
            "COUNTRY": "country",
            "TIME_PERIOD": "time_period",
        }
    )
    df = df.drop(columns=["_period_index"], errors="ignore")

    # Validate duplicate keys before pivoting.
    dupes = df.duplicated(["country", "time_period", "variable"], keep=False)
    if dupes.any():
        examples = df.loc[dupes, ["country", "time_period", "variable", "value"]].head(20)
        raise ValueError(f"Duplicate country-quarter-variable observations found:\n{examples}")

    wide = (
        df.pivot(index=["country", "time_period"], columns="variable", values="value")
        .reset_index()
        .rename_axis(columns=None)
    )

    # Build the country map once, then apply the dictionary vectorially.
    country_iso3_map = build_country_iso3_map(wide["country"])
    wide["ISO3"] = wide["country"].map(country_iso3_map)
    wide = add_time_variables(wide)

    # Optional early sample restriction to countries occurring in GTD.
    gtd_iso3 = load_gtd_iso3_values(GTD_COUNTRY_FILE)
    if gtd_iso3 is not None:
        before = len(wide)
        wide = wide[wide["ISO3"].isin(gtd_iso3)].copy()
        print(f"GTD country filter: {before:,} -> {len(wide):,} country-quarter rows")

    # Convenience net variable for intuitive interpretation: positive = net inward FDI.
    inflow_col = f"fdi_inflow_{variable_suffix}"
    outflow_col = f"fdi_outflow_{variable_suffix}"
    net_imf_col = f"fdi_net_imf_{variable_suffix}"
    net_inflow_col = f"fdi_net_inflow_{variable_suffix}"

    if inflow_col in wide.columns and outflow_col in wide.columns:
        wide[net_inflow_col] = wide[inflow_col] - wide[outflow_col]

    # Diagnostic: compare IMF net with assets - liabilities where all three are available.
    if {inflow_col, outflow_col, net_imf_col}.issubset(wide.columns):
        calculated_net = wide[outflow_col] - wide[inflow_col]
        wide["fdi_net_check_diff"] = wide[net_imf_col] - calculated_net
        # Floating point tolerance; do not fail because IMF may round components differently.
        max_abs_diff = wide["fdi_net_check_diff"].abs().max(skipna=True)
        print(f"Max |reported IMF net - (outflow - inflow)|: {max_abs_diff:.6g}")

    # Availability flags.
    for col in [inflow_col, outflow_col, net_imf_col]:
        if col in wide.columns:
            wide[f"has_{col}"] = wide[col].notna().astype("int8")

    # Preferred sort/order for merging.
    first_cols = [
        "ISO3",
        "country",
        "time_period",
        "year",
        "quarter",
        "quarter_start_month",
        inflow_col,
        outflow_col,
        net_imf_col,
        net_inflow_col,
    ]
    first_cols = [c for c in first_cols if c in wide.columns]
    other_cols = [c for c in wide.columns if c not in first_cols]
    wide = wide[first_cols + other_cols].sort_values(["ISO3", "country", "year", "quarter"])

    return wide


def write_outputs(wide: pd.DataFrame) -> None:
    """Write cleaned data and simple diagnostics."""
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    COUNTRY_ISSUES_CSV.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_CSV.parent.mkdir(parents=True, exist_ok=True)

    wide.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

    # Stata export: variable names are already Stata-compatible and short enough.
    try:
        wide.to_stata(OUTPUT_DTA, write_index=False, version=118)
    except Exception as exc:
        print(f"Warning: Stata export failed: {exc}")

    country_issues = (
        wide.loc[wide["ISO3"].isna(), ["country"]]
        .drop_duplicates()
        .sort_values("country")
    )
    country_issues.to_csv(COUNTRY_ISSUES_CSV, index=False, encoding="utf-8")

    fdi_cols = [c for c in wide.columns if c.startswith("fdi_") and not c.endswith("check_diff")]
    summary = (
        wide.groupby(["ISO3", "country"], dropna=False)
        .agg(
            first_period=("time_period", "min"),
            last_period=("time_period", "max"),
            n_quarters=("time_period", "count"),
            **{f"n_nonmissing_{c}": (c, "count") for c in fdi_cols},
        )
        .reset_index()
        .sort_values(["ISO3", "country"], na_position="last")
    )
    summary.to_csv(SUMMARY_CSV, index=False, encoding="utf-8")

    print("\nSaved:")
    print(f"  {OUTPUT_CSV}")
    print(f"  {OUTPUT_DTA}")
    print(f"  {COUNTRY_ISSUES_CSV}")
    print(f"  {SUMMARY_CSV}")
    print("\nShape:", wide.shape)
    print("Countries:", wide["country"].nunique())
    print("ISO3 missing countries:", country_issues["country"].nunique())


def main() -> None:
    wide = load_and_clean_imf_fdi(INPUT_FILE)
    write_outputs(wide)


if __name__ == "__main__":
    main()
