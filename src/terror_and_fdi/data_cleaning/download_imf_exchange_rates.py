"""
Download IMF Exchange Rates (ER) and prepare quarterly exchange rates for merging.

Target series:
    Domestic/national currency units per US dollar, period average, monthly.

Output:
    One row per ISO3-year-quarter with:
        ISO3
        year
        quarter
        exchange_rate_lcu_per_usd

The monthly period-average values are aggregated to quarterly values using
the arithmetic mean of the available monthly observations.

Requirements:
    pip install pandas requests
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from terror_and_fdi.config import INTERIM, PROCESSED


COUNTRY_FILE = PROCESSED / "fdi_gtd_quarterly_merged.csv"
ISO3_COLUMN = "ISO3"

OUTPUT_MONTHLY = INTERIM / "quarterly" / "imf_exchange_rates_monthly.csv"
OUTPUT_QUARTERLY = INTERIM / "quarterly" / "imf_exchange_rates_quarterly.csv"
OUTPUT_ISSUES = INTERIM / "quarterly" / "imf_exchange_rate_download_issues.csv"

START_PERIOD = "1994-01"
END_PERIOD = "2020-12"

IMF_API_BASE = "https://api.imf.org/external/sdmx/3.0"
DATAFLOW = "IMF.STA,ER,4.0.1"

SERIES_KEY_TEMPLATES = (
    "{iso3}.USD_XDC.PA_RT.M",
    "{iso3}.XDC_USD.PA_RT.M",
)

REQUEST_TIMEOUT = 120
PAUSE_BETWEEN_COUNTRIES = 0.05
CSV_ACCEPT_HEADERS = (
    "application/vnd.sdmx.data+csv;version=2.0.0",
    "text/csv",
)


def make_session() -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "terror-and-fdi-research/1.0",
            "Accept-Language": "en",
        }
    )
    return session


def read_country_codes(path: Path, iso3_column: str) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Country file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path, usecols=[iso3_column])
    elif suffix == ".dta":
        df = pd.read_stata(path, columns=[iso3_column])
    elif suffix in {".parquet", ".pq"}:
        df = pd.read_parquet(path, columns=[iso3_column])
    else:
        raise ValueError(f"Unsupported country-file type: {path.suffix}")

    codes = (
        df[iso3_column]
        .astype("string")
        .str.strip()
        .str.upper()
        .dropna()
        .drop_duplicates()
    )
    invalid = codes[~codes.str.fullmatch(r"[A-Z]{3}", na=False)]
    if not invalid.empty:
        raise ValueError(f"Invalid ISO3 values in country file: {invalid.tolist()}")

    return sorted(codes.tolist())


def build_data_url(series_key: str) -> str:
    return (
        f"{IMF_API_BASE}/data/{DATAFLOW}/{series_key}"
        f"?startPeriod={START_PERIOD}&endPeriod={END_PERIOD}"
    )


def parse_sdmx_csv(content: bytes) -> pd.DataFrame:
    if not content.strip():
        return pd.DataFrame()
    text = content.decode("utf-8-sig", errors="replace")
    try:
        return pd.read_csv(io.StringIO(text))
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def request_series(
    session: requests.Session,
    series_key: str,
) -> tuple[pd.DataFrame, str]:
    url = build_data_url(series_key)
    last_error = ""

    for accept in CSV_ACCEPT_HEADERS:
        response = session.get(
            url,
            headers={"Accept": accept},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code in {404, 406}:
            last_error = f"HTTP {response.status_code} with Accept={accept}"
            continue

        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "json" in content_type.lower():
            last_error = f"Unexpected JSON response: {response.text[:300]}"
            continue

        frame = parse_sdmx_csv(response.content)
        if not frame.empty:
            return frame, url

        last_error = "Empty response"

    return pd.DataFrame(), f"{url} ({last_error})"


def find_column(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    lookup = {str(col).upper(): str(col) for col in df.columns}
    for candidate in candidates:
        if candidate.upper() in lookup:
            return lookup[candidate.upper()]
    return None


def response_describes_lcu_per_usd(df: pd.DataFrame) -> bool:
    label_columns = [
        col
        for col in df.columns
        if any(
            token in str(col).upper()
            for token in ("INDICATOR", "SERIES", "TITLE", "DESCRIPTION", "CURRENCY")
        )
    ]
    if not label_columns:
        return False

    labels = " ".join(
        df[label_columns]
        .astype("string")
        .fillna("")
        .stack()
        .astype(str)
        .str.lower()
        .unique()
    )
    desired_phrases = (
        "domestic currency per us dollar",
        "national currency per us dollar",
        "local currency per us dollar",
        "currency units per us dollar",
        "currency per u.s. dollar",
    )
    return any(phrase in labels for phrase in desired_phrases)


def standardize_monthly_response(
    raw: pd.DataFrame,
    iso3: str,
    series_key: str,
) -> pd.DataFrame:
    time_col = find_column(raw, ("TIME_PERIOD", "TIME_PERIOD_START"))
    value_col = find_column(raw, ("OBS_VALUE", "VALUE"))

    if time_col is None or value_col is None:
        raise ValueError(
            f"Could not identify TIME_PERIOD/OBS_VALUE columns. "
            f"Returned columns: {raw.columns.tolist()}"
        )

    out = raw[[time_col, value_col]].copy()
    out.columns = ["time_period", "exchange_rate_lcu_per_usd"]
    out["ISO3"] = iso3
    out["series_key"] = series_key

    out["time_period"] = out["time_period"].astype("string").str.slice(0, 7)
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
    out = out[out["exchange_rate_lcu_per_usd"] > 0].copy()

    if out.duplicated(["ISO3", "date"]).any():
        out = (
            out.groupby(["ISO3", "date"], as_index=False)
            .agg(
                exchange_rate_lcu_per_usd=("exchange_rate_lcu_per_usd", "mean"),
                series_key=("series_key", "first"),
            )
        )

    return out


def download_country(
    session: requests.Session,
    iso3: str,
) -> tuple[pd.DataFrame, str | None]:
    errors: list[str] = []

    for candidate_number, template in enumerate(SERIES_KEY_TEMPLATES):
        series_key = template.format(iso3=iso3)

        try:
            raw, request_info = request_series(session, series_key)
        except requests.RequestException as exc:
            errors.append(f"{series_key}: {exc}")
            continue

        if raw.empty:
            errors.append(f"{series_key}: no observations; {request_info}")
            continue

        labels_confirm_direction = response_describes_lcu_per_usd(raw)
        if candidate_number > 0 and not labels_confirm_direction:
            errors.append(
                f"{series_key}: data returned, but direction could not be "
                "verified as local currency per USD"
            )
            continue

        try:
            monthly = standardize_monthly_response(raw, iso3, series_key)
        except ValueError as exc:
            errors.append(f"{series_key}: {exc}")
            continue

        if monthly.empty:
            errors.append(f"{series_key}: observations could not be parsed")
            continue

        return monthly, None

    return pd.DataFrame(), " | ".join(errors)


def aggregate_to_quarterly(monthly: pd.DataFrame) -> pd.DataFrame:
    out = monthly.copy()
    out["year"] = out["date"].dt.year.astype("int16")
    out["quarter"] = out["date"].dt.quarter.astype("int8")

    quarterly = (
        out.groupby(["ISO3", "year", "quarter"], as_index=False)
        .agg(
            exchange_rate_lcu_per_usd=("exchange_rate_lcu_per_usd", "mean"),
            n_months_exchange_rate=("exchange_rate_lcu_per_usd", "count"),
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
    countries = read_country_codes(COUNTRY_FILE, ISO3_COLUMN)
    print(f"Countries requested: {len(countries):,}")

    session = make_session()
    monthly_frames: list[pd.DataFrame] = []
    issues: list[dict[str, str]] = []

    for index, iso3 in enumerate(countries, start=1):
        print(f"[{index:>3}/{len(countries)}] Downloading {iso3} ...", end=" ")

        monthly, error = download_country(session, iso3)

        if error is not None:
            print("no usable series")
            issues.append({"ISO3": iso3, "issue": error})
        else:
            print(f"{len(monthly):,} monthly observations")
            monthly_frames.append(monthly)

        time.sleep(PAUSE_BETWEEN_COUNTRIES)

    if not monthly_frames:
        raise RuntimeError(
            "No exchange-rate series were downloaded. Check API availability, "
            "dataflow version, and the returned terminal messages."
        )

    monthly_all = (
        pd.concat(monthly_frames, ignore_index=True)
        .sort_values(["ISO3", "date"])
        .reset_index(drop=True)
    )
    quarterly = aggregate_to_quarterly(monthly_all)

    OUTPUT_MONTHLY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_QUARTERLY.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_ISSUES.parent.mkdir(parents=True, exist_ok=True)

    monthly_export = monthly_all.copy()
    monthly_export["date"] = monthly_export["date"].dt.strftime("%Y-%m-%d")
    monthly_export.to_csv(OUTPUT_MONTHLY, index=False, encoding="utf-8")
    quarterly.to_csv(OUTPUT_QUARTERLY, index=False, encoding="utf-8")
    pd.DataFrame(issues, columns=["ISO3", "issue"]).to_csv(
        OUTPUT_ISSUES,
        index=False,
        encoding="utf-8",
    )

    print("\nSaved:")
    print(f"  Monthly:   {OUTPUT_MONTHLY}")
    print(f"  Quarterly: {OUTPUT_QUARTERLY}")
    print(f"  Issues:    {OUTPUT_ISSUES}")
    print(f"\nCountries downloaded: {monthly_all['ISO3'].nunique():,}")
    print(f"Quarterly observations: {len(quarterly):,}")
    print(
        "Incomplete quarters (<3 monthly observations): "
        f"{(quarterly['complete_exchange_rate_quarter'] == 0).sum():,}"
    )


if __name__ == "__main__":
    main()
