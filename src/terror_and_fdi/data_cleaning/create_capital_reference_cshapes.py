"""
Create a dynamic capital reference table from CShapes 2.1.

The script downloads the official CShapes CSV when the raw file is missing,
keeps independent states, converts country names to ISO3 where possible, and
combines consecutive CShapes rows that describe the same capital spell.

Install dependencies once:
    pip install pandas country_converter

Examples:
    python create_capital_reference_cshapes.py

    python create_capital_reference_cshapes.py \
        --start-date 1993-01-01 \
        --end-date 2020-12-31

By default, the script uses RAW and INTERIM from terror_and_fdi.config:
    RAW / "cshapes" / "CShapes-2.1.csv"
    INTERIM / "capital_reference_manual.csv"
    INTERIM / "capital_reference_dynamic.csv"

    python create_capital_reference_cshapes.py --refresh-download
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd

from terror_and_fdi.config import INTERIM, RAW

try:
    import country_converter as coco
except ImportError as exc:
    raise ImportError(
        "The package 'country_converter' is required. "
        "Install it with: pip install country_converter"
    ) from exc


CSHAPES_VERSION = "2.1"
CSHAPES_URL = (
    "https://icr.ethz.ch/data/cshapes/CShapes-2.1.csv"
)

DEFAULT_INPUT = RAW / "cshapes" / "CShapes-2.1.csv"
DEFAULT_MANUAL_REFERENCE = INTERIM / "capital_reference_manual.csv"
DEFAULT_OUTPUT = INTERIM / "capital_reference_dynamic.csv"

REQUIRED_COLUMNS = {
    "cntry_name",
    "capname",
    "caplong",
    "caplat",
    "gwcode",
    "status",
    "gwsdate",
    "gwedate",
}

REQUIRED_MANUAL_COLUMNS = {
    "iso3",
    "country_name",
    "capital_name",
    "valid_from",
    "valid_until",
    "capital_longitude",
    "capital_latitude",
    "reference_source",
    "source_url",
    "methodological_note",
}

# country_converter does not resolve all historical CShapes entities.
# Current states use current ISO3 codes. Deleted historical ISO3 codes are
# retained where they are useful and unambiguous for the GTD period.
ISO3_NAME_OVERRIDES: dict[str, str | None] = {
    "Austria-Hungary": None,
    "German Democratic Republic": "DDR",
    "German Federal Republic": "DEU",
    "Germany (Prussia)": "DEU",
    "Orange Free State": None,
    "Tibet": None,
    "Transvaal": None,
    "Vietnam (Annam/Cochin China/Tonkin)": "VNM",
    "Vietnam, Democratic Republic of": "VNM",
    "Vietnam, Republic of": "VNM",
    "Yugoslavia": "YUG",
    "Zanzibar": None,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a date-valid dynamic capital table from CShapes 2.1."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=(
            "Raw CShapes CSV. If it is missing, the official file is "
            "downloaded automatically."
        ),
    )
    parser.add_argument(
        "--manual-reference",
        type=Path,
        default=DEFAULT_MANUAL_REFERENCE,
        help=(
            "Optional CSV with manually documented capital periods. "
            "If the default file does not exist, only CShapes is used."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination of the derived capital reference CSV.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Optional first date to retain, in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Optional last date to retain, in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--refresh-download",
        action="store_true",
        help="Download CShapes again even if the raw CSV already exists.",
    )
    parser.add_argument(
        "--fail-on-missing-iso3",
        action="store_true",
        help=(
            "Stop if an included historical entity has no ISO3 assignment."
        ),
    )
    return parser.parse_args()


def download_cshapes(destination: Path, refresh: bool = False) -> None:
    if destination.exists() and not refresh:
        print(f"Using existing raw file: {destination}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")

    print(f"Downloading CShapes {CSHAPES_VERSION} from the official source...")
    try:
        urllib.request.urlretrieve(CSHAPES_URL, temporary)
        if temporary.stat().st_size == 0:
            raise RuntimeError("The downloaded file is empty.")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    print(f"Saved raw file: {destination}")


def normalize_text(value: object) -> str | pd.NA:
    if pd.isna(value):
        return pd.NA

    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def add_iso3(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    converter = coco.CountryConverter()

    names_to_convert = sorted(
        set(result["country_name"]) - set(ISO3_NAME_OVERRIDES)
    )
    converted = converter.convert(
        names=names_to_convert,
        to="ISO3",
        not_found=None,
    )
    if isinstance(converted, str):
        converted = [converted]

    mapping = dict(zip(names_to_convert, converted))
    mapping.update(ISO3_NAME_OVERRIDES)

    result["iso3"] = result["country_name"].map(mapping)

    # country_converter returns the original input for unresolved names.
    unresolved = result["iso3"].eq(result["country_name"])
    result.loc[unresolved, "iso3"] = pd.NA

    result["iso3_source"] = "country_converter"
    override_names = result["country_name"].isin(ISO3_NAME_OVERRIDES)
    result.loc[override_names, "iso3_source"] = "manual_override"
    result.loc[result["iso3"].isna(), "iso3_source"] = "unresolved_historical"

    return result


def same_capital(left: pd.Series, right: pd.Series) -> bool:
    same_identity = (
        left["gwcode"] == right["gwcode"]
        and left["country_name"] == right["country_name"]
        and left["capital_name_normalized"]
        == right["capital_name_normalized"]
    )
    same_coordinates = (
        abs(left["capital_longitude"] - right["capital_longitude"]) <= 1e-6
        and abs(left["capital_latitude"] - right["capital_latitude"]) <= 1e-6
    )
    consecutive = (
        right["valid_from"] == left["valid_until"] + pd.Timedelta(days=1)
    )
    return bool(same_identity and same_coordinates and consecutive)


def combine_consecutive_periods(df: pd.DataFrame) -> pd.DataFrame:
    sort_columns = ["gwcode", "valid_from", "valid_until"]
    ordered = df.sort_values(sort_columns).reset_index(drop=True)

    combined: list[dict[str, object]] = []
    for _, row in ordered.iterrows():
        row_dict = row.to_dict()
        row_dict["source_rows_merged"] = 1

        if not combined:
            combined.append(row_dict)
            continue

        previous = pd.Series(combined[-1])
        if same_capital(previous, row):
            combined[-1]["valid_until"] = row["valid_until"]
            combined[-1]["source_rows_merged"] += 1
        else:
            combined.append(row_dict)

    return pd.DataFrame(combined)


def restrict_date_window(
    df: pd.DataFrame,
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    start = (
        pd.Timestamp(start_date)
        if start_date is not None
        else df["valid_from"].min()
    )
    end = (
        pd.Timestamp(end_date)
        if end_date is not None
        else df["valid_until"].max()
    )

    if start > end:
        raise ValueError("start_date must not be after end_date.")

    result = df.loc[
        df["valid_until"].ge(start) & df["valid_from"].le(end)
    ].copy()
    result["valid_from"] = result["valid_from"].clip(lower=start)
    result["valid_until"] = result["valid_until"].clip(upper=end)
    return result


def validate_reference(df: pd.DataFrame) -> None:
    if df.empty:
        raise ValueError("No CShapes periods remain after filtering.")

    if df["valid_from"].isna().any() or df["valid_until"].isna().any():
        raise ValueError("At least one validity date is missing or invalid.")

    if (df["valid_from"] > df["valid_until"]).any():
        raise ValueError("At least one validity period has a negative length.")

    if df[["capital_name", "capital_latitude", "capital_longitude"]].isna().any(
    ).any():
        raise ValueError("At least one retained capital has missing data.")

    invalid_latitude = ~df["capital_latitude"].between(-90, 90)
    invalid_longitude = ~df["capital_longitude"].between(-180, 180)
    if invalid_latitude.any() or invalid_longitude.any():
        raise ValueError("At least one capital coordinate is invalid.")

    # CShapes may contain simultaneous historical entities mapped to the same
    # modern ISO3. Keep its authoritative GW identity; use ISO3 only for
    # manual entities that intentionally have no GW code.
    entity_key = df["gwcode"].astype("string")
    entity_key = entity_key.fillna("MANUAL:" + df["iso3"].astype("string"))
    ordered = (
        df.assign(_validation_entity=entity_key)
        .sort_values(["_validation_entity", "valid_from"])
    )
    previous_end = ordered.groupby(
        "_validation_entity", dropna=False
    )["valid_until"].shift()
    overlaps = ordered["valid_from"].le(previous_end)
    if overlaps.any():
        problem_rows = ordered.loc[
            overlaps,
            ["iso3", "gwcode", "country_name", "valid_from", "valid_until"],
        ]
        raise ValueError(
            "Overlapping capital periods detected:\n"
            + problem_rows.to_string(index=False)
        )


def load_manual_reference(
    path: Path | None,
    start_date: str | None,
    end_date: str | None,
) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()

    manual = pd.read_csv(path)
    missing = REQUIRED_MANUAL_COLUMNS - set(manual.columns)
    if missing:
        raise ValueError(
            f"Manual capital reference is missing columns: {sorted(missing)}"
        )

    manual = manual.copy()
    manual["iso3"] = manual["iso3"].astype("string").str.strip().str.upper()
    invalid_iso3 = ~manual["iso3"].str.fullmatch(r"[A-Z]{3}", na=False)
    if invalid_iso3.any():
        raise ValueError(
            "Manual capital reference contains invalid ISO3 values:\n"
            + manual.loc[invalid_iso3, ["iso3", "country_name"]].to_string(
                index=False
            )
        )

    manual["valid_from"] = pd.to_datetime(
        manual["valid_from"], errors="raise"
    )
    manual["valid_until"] = pd.to_datetime(
        manual["valid_until"], errors="raise"
    )
    manual["capital_longitude"] = pd.to_numeric(
        manual["capital_longitude"], errors="raise"
    )
    manual["capital_latitude"] = pd.to_numeric(
        manual["capital_latitude"], errors="raise"
    )
    manual["capital_name_normalized"] = manual["capital_name"].map(
        normalize_text
    )
    manual = restrict_date_window(manual, start_date, end_date)

    # These entities are outside CShapes' independent-state universe.
    manual["gwcode"] = pd.NA
    manual["iso3_source"] = "manual_reference"
    manual["source_rows_merged"] = 1
    manual["cshapes_status"] = "not_in_cshapes_independent_states"
    manual["cshapes_version"] = CSHAPES_VERSION
    manual["source_file_sha256"] = pd.NA
    return manual


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_reference(
    input_path: Path,
    manual_reference_path: Path | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    raw = pd.read_csv(
        input_path,
        usecols=lambda column: column in REQUIRED_COLUMNS,
        encoding="utf-8",
    )

    missing = REQUIRED_COLUMNS - set(raw.columns)
    if missing:
        raise ValueError(
            f"Missing CShapes columns: {sorted(missing)}"
        )

    independent = raw.loc[raw["status"].eq("independent")].copy()
    independent = independent.rename(
        columns={
            "cntry_name": "country_name",
            "capname": "capital_name",
            "caplong": "capital_longitude",
            "caplat": "capital_latitude",
            "gwsdate": "valid_from",
            "gwedate": "valid_until",
        }
    )

    independent["valid_from"] = pd.to_datetime(
        independent["valid_from"], errors="raise"
    )
    independent["valid_until"] = pd.to_datetime(
        independent["valid_until"], errors="raise"
    )
    independent["gwcode"] = independent["gwcode"].astype("int64")
    independent["capital_name_normalized"] = independent[
        "capital_name"
    ].map(normalize_text)

    keep = [
        "gwcode",
        "country_name",
        "capital_name",
        "capital_name_normalized",
        "capital_longitude",
        "capital_latitude",
        "valid_from",
        "valid_until",
    ]
    reference = combine_consecutive_periods(independent[keep])
    reference = restrict_date_window(reference, start_date, end_date)
    reference = add_iso3(reference)

    reference["cshapes_status"] = "independent"
    reference["cshapes_version"] = CSHAPES_VERSION
    reference["reference_source"] = "cshapes_2_1"
    reference["source_url"] = CSHAPES_URL
    reference["methodological_note"] = (
        "Independent-state capital period from CShapes 2.1."
    )
    reference["source_file_sha256"] = file_sha256(input_path)

    manual = load_manual_reference(
        manual_reference_path,
        start_date=start_date,
        end_date=end_date,
    )
    if not manual.empty:
        duplicate_iso3 = sorted(
            set(manual["iso3"]).intersection(reference["iso3"].dropna())
        )
        if duplicate_iso3:
            raise ValueError(
                "Manual capital reference duplicates CShapes ISO3 entities: "
                + ", ".join(duplicate_iso3)
            )
        reference = pd.concat([reference, manual], ignore_index=True)

    output_columns = [
        "iso3",
        "gwcode",
        "country_name",
        "capital_name",
        "capital_name_normalized",
        "valid_from",
        "valid_until",
        "capital_longitude",
        "capital_latitude",
        "iso3_source",
        "source_rows_merged",
        "cshapes_status",
        "cshapes_version",
        "reference_source",
        "source_url",
        "methodological_note",
        "source_file_sha256",
    ]
    reference = reference[output_columns].sort_values(
        ["iso3", "valid_from"]
    )
    reference = reference.reset_index(drop=True)

    validate_reference(reference)
    return reference


def main() -> None:
    logging.getLogger("country_converter").setLevel(logging.ERROR)
    args = parse_args()

    download_cshapes(args.input, refresh=args.refresh_download)
    reference = build_reference(
        args.input,
        manual_reference_path=args.manual_reference,
        start_date="1993-01-01",
        end_date="2020-12-31",
    )

    missing_iso3 = (
        reference.loc[reference["iso3"].isna(), "country_name"]
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    if missing_iso3 and args.fail_on_missing_iso3:
        raise ValueError(
            "No ISO3 mapping for included historical entities: "
            + ", ".join(missing_iso3)
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    reference.to_csv(
        args.output,
        index=False,
        encoding="utf-8",
        date_format="%Y-%m-%d",
    )

    print()
    print("Dynamic capital reference created")
    print(f"Output:                 {args.output}")
    print(f"Rows:                   {len(reference):,}")
    print(f"ISO3 entities:          {reference['iso3'].nunique():,}")
    print(
        "Manual reference rows:  "
        f"{int(reference['reference_source'].ne('cshapes_2_1').sum()):,}"
    )
    print(
        "Date coverage:          "
        f"{reference['valid_from'].min().date()} to "
        f"{reference['valid_until'].max().date()}"
    )
    print(
        "Rows without ISO3:      "
        f"{int(reference['iso3'].isna().sum()):,}"
    )
    if missing_iso3:
        print(
            "Historical entities without ISO3: "
            + ", ".join(missing_iso3)
        )


if __name__ == "__main__":
    main()
