"""
Download monthly IMF exchange rates and aggregate them to quarters.

Data source
-----------
IMF International Financial Statistics (IFS), accessed through the DBnomics API.

Series:
    ENDA_XDC_USD_RATE
    Exchange Rates, Domestic Currency per U.S. Dollar,
    Period Average, Rate

Interpretation:
    exchange_rate_lcu_per_usd = units of domestic currency per 1 US dollar

Quarterly conversion:
    Arithmetic mean of the available monthly period-average observations.

Required packages:
    pip install pandas requests pycountry

Input:
    A CSV, Stata, or Parquet file containing an ISO3 column.

Output merge keys:
    ISO3, year, quarter
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from terror_and_fdi.config import INTERIM, PROCESSED


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

COUNTRY_FILE = PROCESSED / "fdi_gtd_quarterly_merged.csv"
ISO3_COLUMN = "ISO3"

OUTPUT_MONTHLY = INTERIM / "quarterly" / "imf_exchange_rates_monthly.csv"
OUTPUT_QUARTERLY = INTERIM / "quarterly" / "imf_exchange_rates_quarterly.csv"
OUTPUT_ISSUES = INTERIM / "quarterly" / "imf_exchange_rate_download_issues.csv"

START_PERIOD = "1994-01"
END_PERIOD = "2020-12"

DBNOMICS_API = "https://api.db.nomics.world/v22/series"
PROVIDER = "IMF"
DATASET = "IFS"
FREQUENCY = "M"
INDICATOR = "ENDA_XDC_USD_RATE"

REQUEST_TIMEOUT = 45
PAUSE_BETWEEN_REQUESTS = 0.05


# IMF reference-area codes are generally ISO2, but some economies require
# manual handling.
ISO3_TO_IMF_REF_AREA = {
    "XKX": "XK",
    "PSE": "PS",
    "HKG": "HK",
    "MAC": "MO",
    "CUW": "1C_355",
    "SXM": "1C_355",
}

# Non-country entities or cases for which no separate national exchange rate
# should be requested.
EXCLUDE_ISO3 = {
    "XKX",  # remove this line if a usable XK series is confirmed
}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def make_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )

    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "terror-and-fdi-research/1.0"})
    return session


def read_country_codes(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Country file not found: {path}")

    suffix = path.suffix.lower()

    if suffix == ".csv":
        df = pd.read_csv(path, usecols=[ISO3_COLUMN])
    elif suffix == ".dta":
        df = pd.read_stata(path, columns=[ISO3_COLUMN])
    elif suffix in {".parquet", ".pq"}:
        df = pd.read_parquet(path, columns=[ISO3_COLUMN])
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    codes = (
        df[ISO3_COLUMN]
        .astype("string")
        .str.strip()
        .str.upper()
        .dropna()
        .drop_duplicates()
    )

    invalid = codes[~codes.str.fullmatch(r"[A-Z]{3}", na=False)]
    if not invalid.empty:
        raise ValueError(f"Invalid ISO3 values: {invalid.tolist()}")

    return sorted(code for code in codes.tolist() if code not in EXCLUDE_ISO3)


def iso3_to_imf_ref_area(iso3: str) -> Optional[str]:
    """Convert one ISO3 code to the IMF/IFS reference-area code."""
    if iso3 in ISO3_TO_IMF_REF_AREA:
        return ISO3_TO_IMF_REF_AREA[iso3]

    try:
        import pycountry

        country = pycountry.countries.get(alpha_3=iso3)
        if country is None:
            return None
        return country.alpha_2
    except ImportError as exc:
        raise ImportError(
            "pycountry is required. Install it with: pip install pycountry"
        ) from exc


def build_series_code(ref_area: str) -> str:
    return f"{FREQUENCY}.{ref_area}.{INDICATOR}"


def build_url(series_code: str) -> str:
    return f"{DBNOMICS_API}/{PROVIDER}/{DATASET}/{series_code}?observations=1"


def extract_series_document(payload: dict) -> Optional[dict]:
    """Extract the single returned DBnomics series document."""
    series = payload.get("series", {})
    docs = series.get("docs", [])

    if not docs:
        return None

    return docs[0]


def parse_series_document(doc: dict, iso3: str, ref_area: str) -> pd.DataFrame:
    periods = doc.get("period") or []
    values = doc.get("value") or []

    if len(periods) != len(values):
        raise ValueError(
            f"Period/value length mismatch: {len(periods)} vs {len(values)}"
        )

    out = pd.DataFrame(
        {
            "ISO3": iso3,
            "imf_ref_area": ref_area,
            "time_period": periods,
            "exchange_rate_lcu_per_usd": values,
        }
    )

    out["date"] = pd.to_datetime(
        out["time_period"],
        format="%Y-%m",
        errors="coerce",
    )
    out["exchange_rate_lcu_per_usd"] = pd.to_numeric(
        out["exchange_rate_lcu_per_usd"],
        errors="coerce",
    )

    out = out.dropna(subset=["date", "exchange_rate_lcu_per_usd"]).copy()
    out = out[
        out["date"].between(
            pd.Timestamp(START_PERIOD),
            pd.Timestamp(END_PERIOD),
            inclusive="both",
        )
    ].copy()

    # A domestic-currency-per-USD exchange rate must be positive.
    out = out[out["exchange_rate_lcu_per_usd"] > 0].copy()

    return out


def download_country(
    session: requests.Session,
    iso3: str,
) -> tuple[pd.DataFrame, Optional[str]]:
    ref_area = iso3_to_imf_ref_area(iso3)

    if ref_area is None:
        return pd.DataFrame(), "Could not convert ISO3 to IMF reference-area code"

    series_code = build_series_code(ref_area)
    url = build_url(series_code)

    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return pd.DataFrame(), f"Request failed for {series_code}: {exc}"
    except ValueError as exc:
        return pd.DataFrame(), f"Invalid JSON for {series_code}: {exc}"

    doc = extract_series_document(payload)
    if doc is None:
        return pd.DataFrame(), f"No IMF/IFS series found: {series_code}"

    series_name = str(doc.get("series_name", ""))
    expected_text = "Domestic Currency per U.S. Dollar"

    if expected_text.lower() not in series_name.lower():
        return (
            pd.DataFrame(),
            f"Unexpected series returned for {series_code}: {series_name}",
        )

    try:
        data = parse_series_document(doc, iso3, ref_area)
    except ValueError as exc:
        return pd.DataFrame(), f"Could not parse {series_code}: {exc}"

    if data.empty:
        return (
            pd.DataFrame(),
            f"Series exists but has no usable values in {START_PERIOD}–{END_PERIOD}",
        )

    data["series_code"] = series_code
    data["series_name"] = series_name
    return data, None


def aggregate_to_quarterly(monthly: pd.DataFrame) -> pd.DataFrame:
    out = monthly.copy()
    out["year"] = out["date"].dt.year.astype("int16")
    out["quarter"] = out["date"].dt.quarter.astype("int8")

    quarterly = (
        out.groupby(["ISO3", "year", "quarter"], as_index=False)
        .agg(
            exchange_rate_lcu_per_usd=(
                "exchange_rate_lcu_per_usd",
                "mean",
            ),
            n_months_exchange_rate=(
                "exchange_rate_lcu_per_usd",
                "count",
            ),
        )
        .sort_values(["ISO3", "year", "quarter"])
        .reset_index(drop=True)
    )

    quarterly["complete_exchange_rate_quarter"] = (
        quarterly["n_months_exchange_rate"] == 3
    ).astype("int8")

    quarterly["time_period"] = (
        quarterly["year"].astype(str)
        + "-Q"
        + quarterly["quarter"].astype(str)
    )

    return quarterly[
        [
            "ISO3",
            "year",
            "quarter",
            "time_period",
            "exchange_rate_lcu_per_usd",
            "n_months_exchange_rate",
            "complete_exchange_rate_quarter",
        ]
    ]


def main() -> None:
    countries = read_country_codes(COUNTRY_FILE)
    print(f"Countries requested: {len(countries):,}")

    session = make_session()
    monthly_frames: list[pd.DataFrame] = []
    issues: list[dict[str, str]] = []

    for index, iso3 in enumerate(countries, start=1):
        print(
            f"[{index:>3}/{len(countries)}] Downloading {iso3} ...",
            end=" ",
            flush=True,
        )

        data, error = download_country(session, iso3)

        if error:
            print("no usable series")
            issues.append({"ISO3": iso3, "issue": error})
        else:
            print(f"{len(data):,} monthly observations")
            monthly_frames.append(data)

        time.sleep(PAUSE_BETWEEN_REQUESTS)

    if not monthly_frames:
        issue_preview = pd.DataFrame(issues).head(10).to_string(index=False)
        raise RuntimeError(
            "No exchange-rate data were downloaded.\n"
            f"First issues:\n{issue_preview}"
        )

    monthly = (
        pd.concat(monthly_frames, ignore_index=True)
        .sort_values(["ISO3", "date"])
        .reset_index(drop=True)
    )

    if monthly.duplicated(["ISO3", "date"]).any():
        examples = monthly.loc[
            monthly.duplicated(["ISO3", "date"], keep=False),
            ["ISO3", "date", "exchange_rate_lcu_per_usd", "series_code"],
        ].head(20)
        raise ValueError(f"Duplicate country-month observations:\n{examples}")

    quarterly = aggregate_to_quarterly(monthly)

    OUTPUT_MONTHLY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_QUARTERLY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_ISSUES.parent.mkdir(parents=True, exist_ok=True)

    monthly_export = monthly.copy()
    monthly_export["date"] = monthly_export["date"].dt.strftime("%Y-%m-%d")
    monthly_export.to_csv(OUTPUT_MONTHLY, index=False, encoding="utf-8")

    quarterly.to_csv(OUTPUT_QUARTERLY, index=False, encoding="utf-8")
    pd.DataFrame(issues, columns=["ISO3", "issue"]).to_csv(
        OUTPUT_ISSUES,
        index=False,
        encoding="utf-8",
    )

    print("\nSaved:")
    print(f"  {OUTPUT_MONTHLY}")
    print(f"  {OUTPUT_QUARTERLY}")
    print(f"  {OUTPUT_ISSUES}")

    print(f"\nCountries successfully downloaded: {monthly['ISO3'].nunique():,}")
    print(f"Countries without usable series: {len(issues):,}")
    print(f"Quarterly observations: {len(quarterly):,}")
    print(
        "Incomplete quarters: "
        f"{(quarterly['complete_exchange_rate_quarter'] == 0).sum():,}"
    )


if __name__ == "__main__":
    main()
