from __future__ import annotations

"""Bereitet quartalsweise FDI- und klassifizierte GTD-Daten auf."""

from pathlib import Path

import numpy as np
import pandas as pd

from terror_and_fdi.config import INTERIM, RAW


GTD_INPUT = (
    INTERIM / "ghs_ucdb_classification" / "gtd_with_ghs_city_groups.csv"
)
OUTPUT_DIR = INTERIM / "quarterly"

# Analytical treatment of each factual capital-match status.
#
# Requested standard specification:
# - missing_city and near_capital_name_unmatched: outside capital
# - name_coordinate_conflict, no reference, unresolved country: excluded
#
# For a robustness check, change any value independently to:
#     "outside" -> classify as outside capital
#     "capital" -> classify as capital
#     "exclude" -> retain in total, but put in capital_unknown
#
# Examples:
# CAPITAL_STATUS_TREATMENT["missing_city"] = "exclude"
# CAPITAL_STATUS_TREATMENT["near_capital_name_unmatched"] = "capital"
# CAPITAL_STATUS_TREATMENT["name_coordinate_conflict"] = "capital"
# CAPITAL_STATUS_TREATMENT["no_capital_reference_for_country_date"] = "outside"
# CAPITAL_STATUS_TREATMENT["unresolved_country"] = "outside"
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


def clean_imf_fdi(input_path: Path, output_path: Path) -> None:
    df = pd.read_csv(input_path)
    df = df.drop(
        columns=[
            "BOP_ACCOUNTING_ENTRY",
            "UNIT",
            "FREQUENCY",
            "SCALE",
            "INDICATOR",
        ],
        errors="ignore",
    ).rename(
        columns={
            "OBS_VALUE": "net_fdi_imf",
            "COUNTRY": "country",
            "TIME_PERIOD": "time_period",
        }
    )
    df.to_stata(output_path, write_index=False)


def nullable_bool(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    text = series.astype("string").str.strip().str.lower()
    result = pd.Series(pd.NA, index=series.index, dtype="Int8")
    result.loc[numeric.eq(1) | text.eq("true")] = 1
    result.loc[numeric.eq(0) | text.eq("false")] = 0
    return result


def capital_from_status(
    status: pd.Series,
    treatments: dict[str, str] | None = None,
) -> pd.Series:
    """Create a nullable 1/0 capital variable from configurable statuses."""
    treatments = (
        CAPITAL_STATUS_TREATMENT if treatments is None else treatments
    )
    allowed = {"capital", "outside", "exclude"}
    invalid = {
        key: value
        for key, value in treatments.items()
        if value not in allowed
    }
    if invalid:
        raise ValueError(
            f"Ungültige CAPITAL_STATUS_TREATMENT-Werte: {invalid}"
        )

    observed = set(status.dropna().astype(str).unique())
    undefined = observed - set(treatments)
    if undefined:
        raise ValueError(
            "Keine Behandlung definiert für capital_match_status: "
            f"{sorted(undefined)}"
        )

    return (
        status.map(treatments)
        .map({"capital": 1, "outside": 0})
        .astype("Int8")
    )


def clean_gtd_quarterly(input_path: Path, output_path: Path) -> None:
    df = pd.read_csv(input_path, low_memory=False)
    required = {
        "ISO3",
        "country_txt",
        "iyear",
        "imonth",
        "success",
        "targtype1",
        "nkill",
        "nwound",
        "capital_match_status",
        "is_top3_ghs_urban_centre",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Im GTD-Input fehlen: {sorted(missing)}")

    unknown_months = ~df["imonth"].between(1, 12)
    print(f"Ereignisse ohne gültigen Monat (ausgeschlossen): {unknown_months.sum():,}")
    df = df.loc[~unknown_months].copy()

    df["quarter"] = (df["imonth"] - 1) // 3 + 1
    df["incidents"] = 1
    df["successful"] = df["success"].eq(1).astype(int)
    df["fatalities"] = pd.to_numeric(df["nkill"], errors="coerce").fillna(0)
    df["wounded"] = pd.to_numeric(df["nwound"], errors="coerce").fillna(0)
    df["casualties"] = df["fatalities"] + df["wounded"]
    df["business"] = df["targtype1"].eq(1).astype(int)

    capital = capital_from_status(df["capital_match_status"])
    top3 = nullable_bool(df["is_top3_ghs_urban_centre"])
    locations = {
        "total": pd.Series(True, index=df.index),
        "capital": capital.eq(1),
        "outside_capital": capital.eq(0),
        "capital_unknown": capital.isna(),
        "top3_ghs": top3.eq(1),
        "outside_top3_ghs": top3.eq(0),
        "top3_ghs_unknown": top3.isna(),
    }
    measures = [
        "incidents",
        "successful",
        "fatalities",
        "wounded",
        "casualties",
        "business",
    ]

    value_columns = []
    for measure in measures:
        for location, mask in locations.items():
            column = f"{measure}_{location}"
            df[column] = df[measure].where(mask, 0)
            value_columns.append(column)

    country_names = (
        df.groupby("ISO3")["country_txt"]
        .agg(lambda values: values.mode().iat[0])
        .rename("country_txt")
        .reset_index()
    )
    keys = ["ISO3", "iyear", "quarter"]
    quarterly = df.groupby(keys, observed=True)[value_columns].sum().reset_index()
    quarterly = quarterly.rename(columns={"iyear": "year"}).merge(
        country_names, on="ISO3", how="left", validate="many_to_one"
    )

    countries = country_names
    years = range(quarterly["year"].min(), quarterly["year"].max() + 1)
    panel = (
        countries.assign(_key=1)
        .merge(pd.DataFrame({"year": years, "_key": 1}), on="_key")
        .merge(pd.DataFrame({"quarter": range(1, 5), "_key": 1}), on="_key")
        .drop(columns="_key")
    )
    quarterly = panel.merge(
        quarterly,
        on=["ISO3", "country_txt", "year", "quarter"],
        how="left",
        validate="one_to_one",
    )
    quarterly[value_columns] = quarterly[value_columns].fillna(0)

    for measure in measures:
        total = quarterly[f"{measure}_total"]
        capital_sum = (
            quarterly[f"{measure}_capital"]
            + quarterly[f"{measure}_outside_capital"]
            + quarterly[f"{measure}_capital_unknown"]
        )
        top3_sum = (
            quarterly[f"{measure}_top3_ghs"]
            + quarterly[f"{measure}_outside_top3_ghs"]
            + quarterly[f"{measure}_top3_ghs_unknown"]
        )
        if not np.allclose(total, capital_sum) or not np.allclose(total, top3_sum):
            raise RuntimeError(f"Konsistenztest fehlgeschlagen: {measure}")

    quarterly.to_stata(output_path, write_index=False)
    print(f"Quartalsdatensatz gespeichert: {output_path}")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    clean_imf_fdi(
        RAW / "imf" / "net_fdi_quarterly_imf.csv",
        OUTPUT_DIR / "fdi_imf_processed.dta",
    )
    clean_gtd_quarterly(
        GTD_INPUT,
        OUTPUT_DIR / "gtd_processed.dta",
    )


if __name__ == "__main__":
    main()
