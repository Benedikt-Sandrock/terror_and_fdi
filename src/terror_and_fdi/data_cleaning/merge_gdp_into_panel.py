from __future__ import annotations

"""Attach annual GDP and population to the quarterly FDI/GTD panel.

The scaling denominator is the *lagged* annual value (year - 1). Using the
lagged year removes simultaneity between the denominator and the quarterly
flow in the numerator, and using an annual rather than a quarterly
denominator keeps business-cycle dynamics out of the dependent variable.

Constructed variables
---------------------
gdp_lag_usd           GDP of year - 1, current USD
gdp_lag_q_usd         gdp_lag_usd / 4, the quarterly-equivalent denominator
pop_lag               population of year - 1
fdi_in_pct_qgdp       fdi_inflow_musd as percent of quarterly GDP
fdi_net_pct_qgdp      fdi_net_inflow_musd as percent of quarterly GDP
fdi_in_pc_usd         fdi_inflow_musd per capita, USD
ihs_fdi_in_pct_qgdp   inverse hyperbolic sine of fdi_in_pct_qgdp
ihs_fdi_net_pct_qgdp  inverse hyperbolic sine of fdi_net_pct_qgdp
ihs_fdi_in_pc         inverse hyperbolic sine of fdi_in_pc_usd
has_gdp_lag           1 if the lagged GDP denominator is available

FDI is never imputed. Rows without a denominator keep missing scaled values
and are identified by has_gdp_lag.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from terror_and_fdi.config import INTERIM, PROCESSED


PANEL_FILE = PROCESSED / "fdi_gtd_quarterly_merged.csv"
GDP_FILE = INTERIM / "gdp" / "gdp_annual.csv"

OUTPUT_CSV = PROCESSED / "fdi_gtd_quarterly_scaled.csv"
OUTPUT_DTA = PROCESSED / "fdi_gtd_quarterly_scaled.dta"
DIAGNOSTICS_CSV = PROCESSED / "fdi_gtd_quarterly_scaled_diagnostics.csv"
COVERAGE_CSV = PROCESSED / "fdi_gtd_quarterly_scaled_coverage.csv"

INCOME_CLASSIFICATION_PATH = INTERIM / "country_metadata_processed.csv"

WRITE_STATA = True

# FDI variables are reported in millions of USD, GDP in USD.
MUSD_TO_USD = 1e6

FDI_LEVEL_COLUMNS = ["fdi_inflow_musd", "fdi_net_inflow_musd"]

# Countries whose USD-converted GDP is distorted by parallel exchange rates or
# hyperinflation. They are flagged, not dropped, so that the exclusion can be
# made in the do-file and reported as a robustness check.
DISTORTED_FX = ["VEN", "ZWE"]

# Conduit economies dominated by special purpose entities. Also flagged only.
SPE_ECONOMIES = ["LUX", "NLD", "IRL", "HKG", "CYP", "MLT", "BEL", "SGP", "CHE"]


def read_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    for path in (PANEL_FILE, GDP_FILE):
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")

    panel = pd.read_csv(PANEL_FILE, low_memory=False)
    gdp = pd.read_csv(GDP_FILE)

    required_panel = {"ISO3", "year", "quarter", "has_fdi_observation"}
    missing = required_panel - set(panel.columns)
    if missing:
        raise ValueError(f"Panel is missing columns: {sorted(missing)}")

    required_gdp = {"ISO3", "year", "gdp_usd"}
    missing = required_gdp - set(gdp.columns)
    if missing:
        raise ValueError(f"GDP file is missing columns: {sorted(missing)}")

    return panel, gdp


def prepare_gdp(gdp: pd.DataFrame) -> pd.DataFrame:
    """Reduce the GDP file to the lagged denominator keyed on the panel year."""
    out = gdp.copy()
    out["ISO3"] = out["ISO3"].astype("string").str.strip().str.upper()
    out["year"] = pd.to_numeric(out["year"], errors="raise").astype(int)

    if out.duplicated(["ISO3", "year"]).any():
        examples = out.loc[out.duplicated(["ISO3", "year"], keep=False)].head(20)
        raise ValueError(f"Duplicate ISO3-year rows in GDP file:\n{examples}")

    keep = ["ISO3", "year", "gdp_usd"]
    if "population" in out.columns:
        keep.append("population")
    if "gdp_source" in out.columns:
        keep.append("gdp_source")
    out = out[keep].copy()

    # Shift forward by one year so that a merge on the panel year picks up the
    # value of the preceding year.
    out["year"] = out["year"] + 1
    renames = {"gdp_usd": "gdp_lag_usd", "gdp_source": "gdp_lag_source"}
    if "population" in out.columns:
        renames["population"] = "pop_lag"
    return out.rename(columns=renames)


def attach_gdp(panel: pd.DataFrame, gdp_lag: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    out["ISO3"] = out["ISO3"].astype("string").str.strip().str.upper()
    out["year"] = pd.to_numeric(out["year"], errors="raise").astype(int)
    out["quarter"] = pd.to_numeric(out["quarter"], errors="raise").astype(int)

    if out.duplicated(["ISO3", "year", "quarter"]).any():
        raise ValueError("Panel contains duplicate ISO3-year-quarter rows.")

    n_before = len(out)
    out = out.merge(gdp_lag, on=["ISO3", "year"], how="left", validate="many_to_one")
    if len(out) != n_before:
        raise RuntimeError("Row count changed during the GDP merge.")

    out["has_gdp_lag"] = out["gdp_lag_usd"].notna().astype("int8")
    return out


def build_scaled_variables(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    denominator = out["gdp_lag_usd"].where(out["gdp_lag_usd"] > 0)
    out["gdp_lag_q_usd"] = denominator / 4.0

    for column, target in (
        ("fdi_inflow_musd", "fdi_in_pct_qgdp"),
        ("fdi_net_inflow_musd", "fdi_net_pct_qgdp"),
    ):
        if column not in out.columns:
            print(f"Note: {column} not present, skipping {target}.")
            continue
        values = pd.to_numeric(out[column], errors="coerce") * MUSD_TO_USD
        out[target] = 100.0 * values / out["gdp_lag_q_usd"]

    if "pop_lag" in out.columns and "fdi_inflow_musd" in out.columns:
        population = out["pop_lag"].where(out["pop_lag"] > 0)
        out["fdi_in_pc_usd"] = (
            pd.to_numeric(out["fdi_inflow_musd"], errors="coerce") * MUSD_TO_USD
        ) / population

    for source, target in (
        ("fdi_in_pct_qgdp", "ihs_fdi_in_pct_qgdp"),
        ("fdi_net_pct_qgdp", "ihs_fdi_net_pct_qgdp"),
        ("fdi_in_pc_usd", "ihs_fdi_in_pc"),
    ):
        if source in out.columns:
            out[target] = np.arcsinh(out[source])

    out["flag_distorted_fx"] = out["ISO3"].isin(DISTORTED_FX).astype("int8")
    out["flag_spe_economy"] = out["ISO3"].isin(SPE_ECONOMIES).astype("int8")

    return out


def validate_scaled(df: pd.DataFrame) -> None:
    """Denominators must never be imputed and must never turn missing FDI into a number."""
    for level, scaled in (
        ("fdi_inflow_musd", "fdi_in_pct_qgdp"),
        ("fdi_net_inflow_musd", "fdi_net_pct_qgdp"),
    ):
        if scaled not in df.columns:
            continue
        invented = df[scaled].notna() & df[level].isna()
        if invented.any():
            raise RuntimeError(
                f"{scaled} is non-missing where {level} is missing "
                f"({int(invented.sum())} rows)."
            )

    if "fdi_in_pct_qgdp" in df.columns:
        both = df["fdi_inflow_musd"].notna() & df["has_gdp_lag"].eq(1)
        if not df.loc[both, "fdi_in_pct_qgdp"].notna().all():
            raise RuntimeError("Scaled FDI is missing although both inputs are present.")


def build_diagnostics(df: pd.DataFrame) -> pd.DataFrame:
    with_fdi = df["has_fdi_observation"].eq(1)
    usable = with_fdi & df["has_gdp_lag"].eq(1)
    core = usable & df["flag_spe_economy"].eq(0) & df["flag_distorted_fx"].eq(0)

    statistics = {
        "panel_rows": len(df),
        "countries_in_panel": df["ISO3"].nunique(),
        "rows_with_fdi": int(with_fdi.sum()),
        "countries_with_fdi": int(df.loc[with_fdi, "ISO3"].nunique()),
        "rows_with_lagged_gdp": int(df["has_gdp_lag"].sum()),
        "rows_with_fdi_and_gdp": int(usable.sum()),
        "rows_lost_to_missing_gdp": int((with_fdi & ~df["has_gdp_lag"].eq(1)).sum()),
        "countries_with_fdi_and_gdp": int(df.loc[usable, "ISO3"].nunique()),
        "rows_core_sample": int(core.sum()),
        "countries_core_sample": int(df.loc[core, "ISO3"].nunique()),
    }
    if "gdp_lag_source" in df.columns:
        for source, count in df.loc[usable, "gdp_lag_source"].value_counts().items():
            statistics[f"gdp_source_{source}"] = int(count)

    return pd.DataFrame(
        {"statistic": list(statistics), "value": list(statistics.values())}
    )


def build_coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Per-country report of what the GDP merge costs, worst cases first."""
    with_fdi = df.loc[df["has_fdi_observation"].eq(1)]
    coverage = (
        with_fdi.groupby("ISO3")
        .agg(
            fdi_quarters=("has_fdi_observation", "size"),
            quarters_with_gdp=("has_gdp_lag", "sum"),
            first_year=("year", "min"),
            last_year=("year", "max"),
        )
        .reset_index()
    )
    coverage["quarters_lost"] = (
        coverage["fdi_quarters"] - coverage["quarters_with_gdp"]
    )
    coverage["share_lost"] = (
        coverage["quarters_lost"] / coverage["fdi_quarters"]
    ).round(4)
    return coverage.sort_values(
        ["quarters_lost", "ISO3"], ascending=[False, True]
    ).reset_index(drop=True)


def write_outputs(
    df: pd.DataFrame, diagnostics: pd.DataFrame, coverage: pd.DataFrame
) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    diagnostics.to_csv(DIAGNOSTICS_CSV, index=False, encoding="utf-8")
    coverage.to_csv(COVERAGE_CSV, index=False, encoding="utf-8")

    if WRITE_STATA:
        try:
            stata = df.copy()
            for column in stata.select_dtypes(include=["string", "object"]).columns:
                stata[column] = stata[column].astype(object)
            stata.to_stata(OUTPUT_DTA, write_index=False, version=118)
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            print(f"Warning: Stata export failed: {exc}")

    print("\nSaved:")
    print(f"  {OUTPUT_CSV}")
    if WRITE_STATA:
        print(f"  {OUTPUT_DTA}")
    print(f"  {DIAGNOSTICS_CSV}")
    print(f"  {COVERAGE_CSV}")


def main() -> None:
    panel, gdp = read_inputs()
    merged = attach_gdp(panel, prepare_gdp(gdp))
    merged = build_scaled_variables(merged)
    validate_scaled(merged)

    diagnostics = build_diagnostics(merged)
    coverage = build_coverage(merged)

    income_class = pd.read_csv(INCOME_CLASSIFICATION_PATH)

    merged = pd.merge(merged, income_class, how="left", on="ISO3")

    print(diagnostics.to_string(index=False))
    worst = coverage.loc[coverage["quarters_lost"] > 0]
    if worst.empty:
        print("\nNo country loses quarters to a missing GDP denominator.")
    else:
        print(f"\nCountries losing quarters to a missing denominator: {len(worst)}")
        print(worst.head(15).to_string(index=False))

    write_outputs(merged, diagnostics, coverage)


if __name__ == "__main__":
    main()