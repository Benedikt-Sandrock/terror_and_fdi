from __future__ import annotations

"""Download annual GDP (current USD) and population for the FDI/GTD panel.

Primary source is the World Bank WDI series NY.GDP.MKTP.CD. Gaps are filled
from the IMF WEO series NGDPD via the DataMapper API using a ratio splice:
the WEO series is rescaled to the WDI level using the median WDI/WEO ratio
over the overlapping years of the same country, so that filled values do not
introduce level breaks into the denominator.

The GDP series is only used as a scaling denominator for quarterly FDI flows,
so a lagged annual value is sufficient and preferable to quarterly GDP, which
would move business-cycle dynamics into the dependent variable.

Outputs
-------
INTERIM/gdp/gdp_annual.csv
    ISO3, year, gdp_usd, gdp_source, population, wdi_weo_ratio
INTERIM/gdp/gdp_annual_raw_wdi.csv
INTERIM/gdp/gdp_annual_raw_weo.csv
    Unmodified API responses, archived for reproducibility.
INTERIM/gdp/gdp_annual_summary.txt

Reproducibility note
--------------------
The IMF DataMapper always serves the current WEO vintage; historical values
are revised between editions. The raw WEO download is archived and the
download date is written to the summary so that a rerun can be compared
against the vintage actually used.
"""

import json
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from terror_and_fdi.config import INTERIM


OUTPUT_DIR = INTERIM / "gdp"
OUTPUT_CSV = OUTPUT_DIR / "gdp_annual.csv"
RAW_WDI_CSV = OUTPUT_DIR / "gdp_annual_raw_wdi.csv"
RAW_WEO_CSV = OUTPUT_DIR / "gdp_annual_raw_weo.csv"
SUMMARY_FILE = OUTPUT_DIR / "gdp_annual_summary.txt"

# One year before the panel start: the merge uses the lagged annual value.
START_YEAR = 1993
END_YEAR = 2020

WDI_BASE = "https://api.worldbank.org/v2"
WDI_INDICATORS = {
    "NY.GDP.MKTP.CD": "gdp_usd",
    "SP.POP.TOTL": "population",
}

WEO_BASE = "https://www.imf.org/external/datamapper/api/v1"
WEO_INDICATOR = "NGDPD"  # GDP, current prices, billions of USD
WEO_SCALE = 1e9

REQUEST_TIMEOUT = 60
MAX_RETRIES = 4
RETRY_SLEEP = 3

# The IMF uses a few non-ISO3 codes. Map them onto the ISO3 codes used in the
# panel. Only codes that actually occur in the FDI/GTD panel are listed.
WEO_CODE_TO_ISO3 = {
    "UVK": "XKX",  # Kosovo
    "WBG": "PSE",  # West Bank and Gaza
}


# -----------------------------------------------------------------------------
# HTTP helper
# -----------------------------------------------------------------------------
def get_json(url: str, params: dict | None = None) -> object:
    """GET with retries. Raises after MAX_RETRIES failed attempts."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_SLEEP * attempt)
    raise RuntimeError(f"Request failed after {MAX_RETRIES} attempts: {url}\n{last_error}")


# -----------------------------------------------------------------------------
# World Bank WDI
# -----------------------------------------------------------------------------
def fetch_wdi_country_codes() -> set[str]:
    """Return ISO3 codes of actual economies, excluding WDI aggregates."""
    payload = get_json(
        f"{WDI_BASE}/country",
        {"format": "json", "per_page": 400},
    )
    if not isinstance(payload, list) or len(payload) < 2:
        raise RuntimeError(f"Unexpected WDI country response: {payload}")

    # Aggregates such as "World" or "Euro area" carry region id "NA".
    codes = {
        entry["id"]
        for entry in payload[1]
        if entry.get("region", {}).get("id") != "NA"
    }
    if len(codes) < 150:
        raise RuntimeError(f"Implausibly few WDI economies returned: {len(codes)}")
    return codes


def fetch_wdi_indicator(indicator: str) -> pd.DataFrame:
    """Download one WDI indicator for all economies and years, page by page."""
    records: list[dict] = []
    page = 1
    while True:
        payload = get_json(
            f"{WDI_BASE}/country/all/indicator/{indicator}",
            {
                "format": "json",
                "per_page": 5000,
                "date": f"{START_YEAR}:{END_YEAR}",
                "page": page,
            },
        )
        if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
            raise RuntimeError(f"Unexpected WDI response for {indicator}: {payload}")

        header, rows = payload[0], payload[1]
        records.extend(rows)
        if page >= int(header["pages"]):
            break
        page += 1

    frame = pd.DataFrame(
        {
            "ISO3": [row.get("countryiso3code") for row in records],
            "year": [row.get("date") for row in records],
            "value": [row.get("value") for row in records],
        }
    )
    frame["ISO3"] = frame["ISO3"].astype("string").str.strip().str.upper()
    frame["year"] = pd.to_numeric(frame["year"], errors="coerce").astype("Int64")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["ISO3", "year"])
    frame = frame.loc[frame["ISO3"].str.fullmatch(r"[A-Z]{3}", na=False)]
    return frame


def fetch_wdi() -> pd.DataFrame:
    """Download all WDI indicators and return them in wide format."""
    economies = fetch_wdi_country_codes()
    print(f"WDI economies (aggregates excluded): {len(economies):,}")

    wide: pd.DataFrame | None = None
    for indicator, column in WDI_INDICATORS.items():
        frame = fetch_wdi_indicator(indicator)
        frame = frame.loc[frame["ISO3"].isin(economies)]
        frame = frame.rename(columns={"value": column})

        if frame.duplicated(["ISO3", "year"]).any():
            raise RuntimeError(f"Duplicate ISO3-year rows in WDI {indicator}.")

        observed = frame[column].notna().sum()
        print(f"  {indicator}: {observed:,} non-missing observations")

        wide = frame if wide is None else wide.merge(
            frame, on=["ISO3", "year"], how="outer", validate="one_to_one"
        )

    assert wide is not None
    wide["year"] = wide["year"].astype(int)
    return wide.sort_values(["ISO3", "year"]).reset_index(drop=True)


# -----------------------------------------------------------------------------
# IMF WEO (DataMapper)
# -----------------------------------------------------------------------------
def fetch_weo() -> pd.DataFrame:
    """Download WEO nominal GDP in USD and convert to units."""
    payload = get_json(f"{WEO_BASE}/{WEO_INDICATOR}")
    values = payload.get("values", {}).get(WEO_INDICATOR)
    if not values:
        raise RuntimeError(f"Unexpected WEO response: {list(payload)[:5]}")

    records = [
        {"ISO3": code, "year": int(year), "gdp_usd_weo": value}
        for code, series in values.items()
        for year, value in series.items()
        if value is not None
    ]
    frame = pd.DataFrame.from_records(records)
    frame["ISO3"] = (
        frame["ISO3"].astype("string").str.strip().str.upper().replace(WEO_CODE_TO_ISO3)
    )
    frame = frame.loc[frame["ISO3"].str.fullmatch(r"[A-Z]{3}", na=False)]
    frame = frame.loc[frame["year"].between(START_YEAR, END_YEAR)]
    frame["gdp_usd_weo"] = pd.to_numeric(frame["gdp_usd_weo"], errors="coerce") * WEO_SCALE

    if frame.duplicated(["ISO3", "year"]).any():
        raise RuntimeError("Duplicate ISO3-year rows in WEO data.")

    print(f"WEO: {frame['gdp_usd_weo'].notna().sum():,} non-missing observations")
    return frame.dropna(subset=["gdp_usd_weo"]).reset_index(drop=True)


# -----------------------------------------------------------------------------
# Ratio splice
# -----------------------------------------------------------------------------
def splice_gdp(wdi: pd.DataFrame, weo: pd.DataFrame) -> pd.DataFrame:
    """Fill WDI gaps with level-adjusted WEO values.

    For each country the median WDI/WEO ratio over overlapping years is used to
    rescale the WEO series before filling. Countries without any overlap are
    filled with the unadjusted WEO level and flagged as such.
    """
    merged = wdi.merge(weo, on=["ISO3", "year"], how="outer", validate="one_to_one")

    overlap = merged.loc[
        merged["gdp_usd"].notna()
        & merged["gdp_usd_weo"].notna()
        & merged["gdp_usd_weo"].ne(0)
    ].copy()
    overlap["ratio"] = overlap["gdp_usd"] / overlap["gdp_usd_weo"]

    ratios = (
        overlap.groupby("ISO3")["ratio"]
        .median()
        .rename("wdi_weo_ratio")
    )
    merged = merged.merge(ratios, on="ISO3", how="left")

    needs_fill = merged["gdp_usd"].isna() & merged["gdp_usd_weo"].notna()
    scaled = merged["gdp_usd_weo"] * merged["wdi_weo_ratio"].fillna(1.0)

    merged["gdp_source"] = pd.NA
    merged.loc[merged["gdp_usd"].notna(), "gdp_source"] = "wdi"
    merged.loc[needs_fill & merged["wdi_weo_ratio"].notna(), "gdp_source"] = "weo_spliced"
    merged.loc[needs_fill & merged["wdi_weo_ratio"].isna(), "gdp_source"] = "weo_unscaled"
    merged.loc[needs_fill, "gdp_usd"] = scaled.loc[needs_fill]

    merged["gdp_source"] = merged["gdp_source"].astype("string")

    filled = int(needs_fill.sum())
    unscaled = int((merged["gdp_source"] == "weo_unscaled").sum())
    print(f"Gaps filled from WEO: {filled:,} (of which unscaled: {unscaled:,})")

    if (merged["gdp_usd"].dropna() <= 0).any():
        bad = merged.loc[merged["gdp_usd"].le(0), ["ISO3", "year", "gdp_usd"]]
        raise RuntimeError(f"Non-positive GDP values:\n{bad.head(20)}")

    merged["year"] = merged["year"].astype(int)
    columns = [
        "ISO3",
        "year",
        "gdp_usd",
        "gdp_source",
        "population",
        "wdi_weo_ratio",
        "gdp_usd_weo",
    ]
    return merged[columns].sort_values(["ISO3", "year"]).reset_index(drop=True)


# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
def build_summary(gdp: pd.DataFrame) -> str:
    by_source = gdp["gdp_source"].value_counts(dropna=False)
    lines = [
        "Annual GDP reference file",
        "=" * 40,
        "",
        f"Downloaded: {date.today().isoformat()}",
        f"WDI indicators: {', '.join(WDI_INDICATORS)}",
        f"WEO indicator: {WEO_INDICATOR} (DataMapper, current vintage)",
        f"Years: {START_YEAR}-{END_YEAR}",
        "",
        f"Rows: {len(gdp):,}",
        f"Countries: {gdp['ISO3'].nunique():,}",
        f"Non-missing GDP: {gdp['gdp_usd'].notna().sum():,}",
        f"Non-missing population: {gdp['population'].notna().sum():,}",
        "",
        "GDP by source:",
    ]
    lines.extend(f"  {source}: {count:,}" for source, count in by_source.items())
    lines.extend(
        [
            "",
            "GDP is in current USD (units, not millions). Population is headcount.",
            "WEO values were rescaled by the country-specific median WDI/WEO",
            "ratio before filling, so that spliced values match the WDI level.",
            "",
            "The DataMapper serves the current WEO vintage. The raw download is",
            "archived next to this summary.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    wdi = fetch_wdi()
    wdi.to_csv(RAW_WDI_CSV, index=False)

    weo = fetch_weo()
    weo.to_csv(RAW_WEO_CSV, index=False)

    gdp = splice_gdp(wdi, weo)
    gdp.to_csv(OUTPUT_CSV, index=False)
    SUMMARY_FILE.write_text(build_summary(gdp), encoding="utf-8")

    print(f"\nRows: {len(gdp):,}  Countries: {gdp['ISO3'].nunique():,}")
    print(f"Saved: {OUTPUT_CSV}")
    print(f"Saved: {SUMMARY_FILE}")


if __name__ == "__main__":
    main()