"""
Classify GTD events by whether their coordinates fall inside one of the three
largest GHS Urban Centres in the event's country and applicable GHS epoch.

This is a separate robustness specification. The capital classification may be
present in the input and is preserved, but it is never used to construct or
classify the TOP3 measure.

The script preserves every input row. It separates the factual spatial match
(`top3_match_status`) from the analytical specification
(`is_top3_ghs_urban_centre`). Change TOP3_STATUS_TREATMENT to include or exclude
individual status groups in robustness checks without repeating the spatial
matching.

Required data:
    RAW / "ghs_ucdb" / ... / one GHS_UCDB_MTUC_R2024A GeoPackage
    INTERIM / "cshapes_capital_classification" /
        "gtd_with_cshapes_capital.csv"

Typical use:
    python ghs_ucdb_classification.py

Optional explicit paths:
    python ghs_ucdb_classification.py \
        --ghs-dir path/to/ghs_ucdb \
        --gtd-input path/to/gtd.csv \
        --output-dir path/to/output
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import country_converter as coco
import geopandas as gpd
import pandas as pd

from terror_and_fdi.config import INTERIM, RAW


DEFAULT_START_YEAR = 1993
DEFAULT_END_YEAR = 2020
DEFAULT_EPOCHS = tuple(range(1995, 2021, 5))
DEFAULT_REVIEW_PER_STATUS = 100
DEFAULT_RANDOM_SEED = 42

DEFAULT_GHS_DIR = RAW / "ghs_ucdb"
DEFAULT_GTD_INPUT = (
    INTERIM
    / "cshapes_capital_classification"
    / "gtd_with_cshapes_capital.csv"
)
DEFAULT_OUTPUT_DIR = INTERIM / "ghs_ucdb_classification"

OUTPUT_FILENAME = "gtd_with_ghs_city_groups.csv"
REFERENCE_FILENAME = "ghs_top3_country_epoch.csv"
SUMMARY_FILENAME = "ghs_top3_classification_summary.txt"

REQUIRED_GTD_COLUMNS = {
    "ISO3",
    "iyear",
    "latitude",
    "longitude",
}

COUNTRY_OVERRIDES = {
    "Democratic Republic of the Congo": "COD",
    "Côte d'Ivoire": "CIV",
    "Kosovo": "XKX",
    "State of Palestine": "PSE",
}

# The factual spatial status is retained independently of this treatment.
# Every value may be changed to "top3", "outside", or "exclude".
TOP3_STATUS_TREATMENT: dict[str, str] = {
    "top3_polygon_match": "top3",
    "outside_top3_polygons": "outside",
    "missing_or_invalid_coordinates": "exclude",
    "no_top3_reference_for_country_epoch": "exclude",
    "unresolved_country": "exclude",
    "missing_event_year": "exclude",
    "event_year_outside_analysis_window": "exclude",
    "unclassified": "exclude",
}

ROBUSTNESS_STATUS_FLAGS = [
    "missing_or_invalid_coordinates",
    "no_top3_reference_for_country_epoch",
    "unresolved_country",
    "missing_event_year",
    "event_year_outside_analysis_window",
]

cc = coco.CountryConverter()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Classify GTD events using the three largest GHS Urban Centres "
            "per country and five-year epoch."
        )
    )
    parser.add_argument(
        "--ghs-dir",
        type=Path,
        default=DEFAULT_GHS_DIR,
        help="Directory containing exactly one GHS UCDB GeoPackage.",
    )
    parser.add_argument(
        "--gtd-input",
        type=Path,
        default=DEFAULT_GTD_INPUT,
        help="Event-level GTD CSV. A capital-classified file is allowed.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for the classified data and all diagnostics.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=DEFAULT_START_YEAR,
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=DEFAULT_END_YEAR,
    )
    parser.add_argument(
        "--review-per-status",
        type=int,
        default=DEFAULT_REVIEW_PER_STATUS,
        help="Maximum number of events sampled per match status.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.start_year > args.end_year:
        raise ValueError("--start-year must not exceed --end-year.")
    if args.review_per_status < 0:
        raise ValueError("--review-per-status must be non-negative.")
    if not args.gtd_input.exists():
        raise FileNotFoundError(f"GTD input not found: {args.gtd_input}")
    if not args.ghs_dir.exists():
        raise FileNotFoundError(f"GHS directory not found: {args.ghs_dir}")


def find_geopackage(ghs_dir: Path) -> Path:
    files = sorted(ghs_dir.rglob("*.gpkg"))
    if len(files) != 1:
        listed = "\n".join(f"  - {path}" for path in files) or "  (none)"
        raise FileNotFoundError(
            f"Expected exactly one .gpkg file below {ghs_dir}; "
            f"found {len(files)}:\n{listed}"
        )
    return files[0]


def year_from_layer(layer: str) -> int | None:
    """Return the single four-digit epoch encoded in a layer name."""
    years = [
        int(value)
        for value in re.findall(
            r"(?<![Rr\d])(19\d{2}|20\d{2})(?!\d)",
            layer,
        )
    ]
    unique_years = sorted(set(years))
    if len(unique_years) > 1:
        raise ValueError(
            f"Layer name contains more than one epoch year: {layer}"
        )
    return unique_years[0] if unique_years else None


def choose_column(
    columns,
    *,
    exact: tuple[str, ...] = (),
    prefix: tuple[str, ...] = (),
) -> str:
    upper = {str(column).upper(): column for column in columns}
    for name in exact:
        if name.upper() in upper:
            return upper[name.upper()]
    for start in prefix:
        matches = [
            column
            for column in columns
            if str(column).upper().startswith(start.upper())
        ]
        if matches:
            return sorted(matches, key=str)[-1]
    raise ValueError(
        f"No suitable column found. Searched exact={exact}, prefix={prefix}. "
        f"Available columns: {list(columns)}"
    )


def iso3_from_country(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip()
    result = cleaned.map(COUNTRY_OVERRIDES).astype("string")
    missing = result.isna() & cleaned.notna()
    if missing.any():
        converted = cc.convert(
            names=cleaned.loc[missing].tolist(),
            to="ISO3",
            not_found="not found",
        )
        result.loc[missing] = pd.Series(
            converted,
            index=result.index[missing],
            dtype="string",
        )
    return result.replace({"not found": pd.NA, "": pd.NA})


def repair_geometry(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    invalid = ~result.geometry.is_valid
    if invalid.any():
        if hasattr(result.geometry, "make_valid"):
            result.loc[invalid, "geometry"] = (
                result.loc[invalid, "geometry"].make_valid()
            )
        else:
            result.loc[invalid, "geometry"] = (
                result.loc[invalid, "geometry"].buffer(0)
            )
    return result.loc[
        result.geometry.notna() & ~result.geometry.is_empty
    ].copy()


def read_top3_by_epoch(
    gpkg: Path,
    epochs: tuple[int, ...],
) -> dict[int, gpd.GeoDataFrame]:
    layers = gpd.list_layers(gpkg)
    layer_names = layers["name"].astype(str).tolist()

    # The GeoPackage also contains epoch layers outside the requested analysis
    # window (for example 1975-1990 and 2025-2030). They must not be mistaken
    # for the single yearless layer containing the shared MTUC attributes.
    layer_years = {
        layer: year_from_layer(layer)
        for layer in layer_names
    }
    attribute_layers = [
        layer
        for layer, year in layer_years.items()
        if year is None
    ]
    if len(attribute_layers) != 1:
        raise ValueError(
            "Expected exactly one attribute layer without an epoch year. "
            f"Candidates: {attribute_layers}\n"
            f"All layers:\n{layers.to_string(index=False)}"
        )

    attributes = gpd.read_file(gpkg, layer=attribute_layers[0])
    id_col = choose_column(
        attributes.columns,
        exact=("ID_MTUC_G0", "ID_UC_G0", "ID_MTUC", "ID_UC"),
        prefix=("ID_MTUC_", "ID_UC_"),
    )
    country_col = choose_column(
        attributes.columns,
        exact=("ISO3", "CNTRY_ISO", "GADM_ISO3"),
        prefix=("GC_CNT_ISO_", "GC_CNT_GAD_"),
    )
    name_col = choose_column(
        attributes.columns,
        exact=("UC_NAME", "NAME"),
        prefix=("GC_UCN_MAI_",),
    )

    country = attributes[country_col].astype("string").str.strip()
    looks_like_iso3 = (
        country.str.fullmatch(r"[A-Z]{3}", na=False).mean() > 0.9
    )
    attributes["ISO3"] = (
        country.str.upper() if looks_like_iso3 else iso3_from_country(country)
    )
    attributes["ghs_uc_id"] = attributes[id_col].astype("string")
    attributes["ghs_uc_name"] = attributes[name_col].astype("string")

    duplicate_ids = attributes["ghs_uc_id"].duplicated(keep=False)
    if duplicate_ids.any():
        examples = (
            attributes.loc[duplicate_ids, "ghs_uc_id"]
            .dropna()
            .astype(str)
            .unique()[:10]
            .tolist()
        )
        raise ValueError(
            "Urban-centre IDs are not unique in the attribute layer. "
            f"Examples: {examples}"
        )

    candidates = {
        epoch: [
            layer
            for layer, year in layer_years.items()
            if year == epoch
        ]
        for epoch in epochs
    }
    invalid = {
        epoch: epoch_layers
        for epoch, epoch_layers in candidates.items()
        if len(epoch_layers) != 1
    }
    if invalid:
        raise ValueError(
            "Expected exactly one polygon layer for every epoch. "
            f"Problematic assignments: {invalid}\n"
            f"All layers:\n{layers.to_string(index=False)}"
        )

    top3_by_epoch: dict[int, gpd.GeoDataFrame] = {}
    for epoch in epochs:
        population_col = choose_column(
            attributes.columns,
            exact=(f"MT_POP_TOT_{epoch}",),
        )
        epoch_attributes = attributes[
            ["ghs_uc_id", "ISO3", "ghs_uc_name", population_col]
        ].copy()
        epoch_attributes["ghs_population"] = pd.to_numeric(
            epoch_attributes.pop(population_col),
            errors="coerce",
        )
        epoch_attributes = epoch_attributes.loc[
            epoch_attributes["ISO3"].notna()
            & epoch_attributes["ghs_population"].gt(0)
        ].copy()
        epoch_attributes = epoch_attributes.sort_values(
            ["ISO3", "ghs_population", "ghs_uc_id"],
            ascending=[True, False, True],
        )
        epoch_attributes["ghs_rank"] = (
            epoch_attributes.groupby("ISO3").cumcount() + 1
        )
        top3_attributes = epoch_attributes.loc[
            epoch_attributes["ghs_rank"].le(3)
        ].copy()

        layer = candidates[epoch][0]
        polygons = gpd.read_file(gpkg, layer=layer)
        if polygons.crs is None:
            raise ValueError(f"Polygon layer has no CRS: {layer}")
        polygon_id_col = choose_column(
            polygons.columns,
            exact=("ID_MTUC_G0", "ID_UC_G0", "ID_MTUC", "ID_UC"),
            prefix=("ID_MTUC_", "ID_UC_"),
        )
        polygons["ghs_uc_id"] = polygons[polygon_id_col].astype("string")
        polygons = polygons.loc[
            polygons["ghs_uc_id"].isin(top3_attributes["ghs_uc_id"]),
            ["ghs_uc_id", "geometry"],
        ]
        polygons = repair_geometry(polygons)
        polygons = polygons.dissolve(by="ghs_uc_id", as_index=False)

        cities = polygons.merge(
            top3_attributes,
            on="ghs_uc_id",
            how="right",
            validate="one_to_one",
        )
        missing_geometry = cities["geometry"].isna()
        if missing_geometry.any():
            examples = cities.loc[
                missing_geometry,
                ["ISO3", "ghs_uc_id", "ghs_uc_name"],
            ].head(10)
            raise ValueError(
                f"{missing_geometry.sum()} TOP3 centres in epoch {epoch} "
                "have no polygon geometry. Examples:\n"
                f"{examples.to_string(index=False)}"
            )
        cities = gpd.GeoDataFrame(
            cities,
            geometry="geometry",
            crs=polygons.crs,
        )
        cities["ghs_epoch"] = epoch
        top3_by_epoch[epoch] = cities[
            [
                "ISO3",
                "ghs_epoch",
                "ghs_rank",
                "ghs_uc_id",
                "ghs_uc_name",
                "ghs_population",
                "geometry",
            ]
        ].copy()

    return top3_by_epoch


def nearest_epoch(
    year: pd.Series,
    epochs: tuple[int, ...],
) -> pd.Series:
    numeric_year = pd.to_numeric(year, errors="coerce")
    epoch_frame = pd.DataFrame(
        {
            epoch: (numeric_year - epoch).abs()
            for epoch in epochs
        }
    )
    nearest = pd.Series(pd.NA, index=year.index, dtype="Int64")
    valid_year = numeric_year.notna()
    nearest.loc[valid_year] = (
        epoch_frame.loc[valid_year].idxmin(axis=1).astype("Int64")
    )
    return pd.to_numeric(nearest, errors="coerce").astype("Int64")


def apply_top3_specification(
    frame: pd.DataFrame,
    treatments: dict[str, str] | None = None,
) -> pd.DataFrame:
    result = frame.copy()
    treatments = (
        TOP3_STATUS_TREATMENT if treatments is None else treatments
    )
    allowed = {"top3", "outside", "exclude"}
    invalid = {
        status: treatment
        for status, treatment in treatments.items()
        if treatment not in allowed
    }
    if invalid:
        raise ValueError(
            f"Invalid TOP3 treatments: {invalid}. Allowed: {sorted(allowed)}"
        )

    observed = set(
        result["top3_match_status"].dropna().astype(str).unique()
    )
    missing = observed - set(treatments)
    if missing:
        raise ValueError(
            "No TOP3 treatment defined for statuses: "
            f"{sorted(missing)}"
        )

    treatment = (
        result["top3_match_status"].map(treatments).astype("string")
    )
    result["top3_spec_treatment"] = treatment
    result["is_top3_ghs_urban_centre"] = (
        treatment.map({"top3": 1, "outside": 0}).astype("Int8")
    )
    result["top3_spec_included"] = treatment.ne("exclude").astype("Int8")
    result["top3_spec_exclusion_reason"] = (
        result["top3_match_status"].where(treatment.eq("exclude"))
    )
    for status in ROBUSTNESS_STATUS_FLAGS:
        result[f"top3_status_{status}"] = (
            result["top3_match_status"].eq(status).astype("Int8")
        )
    return result


def classify_events(
    gtd: pd.DataFrame,
    top3_by_epoch: dict[int, gpd.GeoDataFrame],
    *,
    start_year: int,
    end_year: int,
    epochs: tuple[int, ...],
) -> pd.DataFrame:
    missing = REQUIRED_GTD_COLUMNS - set(gtd.columns)
    if missing:
        raise ValueError(f"Missing GTD input columns: {sorted(missing)}")

    result = gtd.copy().reset_index(drop=True)
    result["_top3_row"] = result.index

    year = pd.to_numeric(result["iyear"], errors="coerce")
    iso3 = result["ISO3"].astype("string").str.strip().str.upper()
    iso3 = iso3.mask(iso3.eq(""))
    lon = pd.to_numeric(result["longitude"], errors="coerce")
    lat = pd.to_numeric(result["latitude"], errors="coerce")
    valid_coordinates = (
        lon.between(-180, 180)
        & lat.between(-90, 90)
        & ~(lon.eq(0) & lat.eq(0))
    )
    in_window = year.between(start_year, end_year)

    result["ISO3"] = iso3
    result["ghs_epoch"] = nearest_epoch(year, epochs)
    result["ghs_coordinate_usable"] = valid_coordinates.astype("boolean")
    result["top3_reference_available"] = False
    result["top3_reference_city_count"] = pd.Series(
        pd.NA,
        index=result.index,
        dtype="Int8",
    )
    result["top3_match_status"] = "unclassified"
    result["top3_match_count"] = pd.Series(
        0,
        index=result.index,
        dtype="Int8",
    )
    result["ghs_uc_id"] = pd.Series(
        pd.NA,
        index=result.index,
        dtype="string",
    )
    result["ghs_uc_name"] = pd.Series(
        pd.NA,
        index=result.index,
        dtype="string",
    )
    result["ghs_rank"] = pd.Series(
        pd.NA,
        index=result.index,
        dtype="Int8",
    )
    result["ghs_population"] = pd.Series(
        pd.NA,
        index=result.index,
        dtype="Float64",
    )

    result.loc[year.isna(), "top3_match_status"] = "missing_event_year"
    result.loc[
        year.notna() & ~in_window,
        "top3_match_status",
    ] = "event_year_outside_analysis_window"
    result.loc[
        in_window & iso3.isna(),
        "top3_match_status",
    ] = "unresolved_country"
    result.loc[
        in_window & iso3.notna() & ~valid_coordinates,
        "top3_match_status",
    ] = "missing_or_invalid_coordinates"

    reference_counts = pd.concat(
        [
            top3[["ISO3", "ghs_epoch"]]
            .groupby(["ISO3", "ghs_epoch"])
            .size()
            .rename("reference_city_count")
            .reset_index()
            for top3 in top3_by_epoch.values()
        ],
        ignore_index=True,
    )
    reference_count_lookup = {
        (str(row.ISO3), int(row.ghs_epoch)): int(row.reference_city_count)
        for row in reference_counts.itertuples(index=False)
    }
    keys = list(zip(iso3, result["ghs_epoch"]))
    counts = pd.Series(
        [
            reference_count_lookup.get(
                (
                    str(country),
                    int(epoch),
                )
            )
            if pd.notna(country) and pd.notna(epoch)
            else None
            for country, epoch in keys
        ],
        index=result.index,
        dtype="Int8",
    )
    result["top3_reference_city_count"] = counts
    result["top3_reference_available"] = counts.fillna(0).gt(0)

    candidate_for_reference = (
        in_window & iso3.notna() & valid_coordinates
    )
    result.loc[
        candidate_for_reference
        & ~result["top3_reference_available"],
        "top3_match_status",
    ] = "no_top3_reference_for_country_epoch"

    for epoch, top3 in sorted(top3_by_epoch.items()):
        eligible = (
            in_window
            & valid_coordinates
            & result["ghs_epoch"].eq(epoch)
            & iso3.isin(top3["ISO3"])
        )
        result.loc[
            eligible,
            "top3_match_status",
        ] = "outside_top3_polygons"
        if not eligible.any():
            continue

        points = gpd.GeoDataFrame(
            result.loc[eligible, ["_top3_row", "ISO3"]],
            geometry=gpd.points_from_xy(
                lon.loc[eligible],
                lat.loc[eligible],
            ),
            crs="EPSG:4326",
        ).to_crs(top3.crs)

        matches = gpd.sjoin(
            points,
            top3,
            how="inner",
            predicate="intersects",
            lsuffix="event",
            rsuffix="ghs",
        )
        if matches.empty:
            continue
        matches = matches.loc[
            matches["ISO3_event"].eq(matches["ISO3_ghs"])
        ].copy()
        if matches.empty:
            continue

        match_counts = matches.groupby("_top3_row").size()
        result.loc[
            match_counts.index,
            "top3_match_count",
        ] = match_counts.clip(upper=127).astype("Int8").to_numpy()

        selected = (
            matches.sort_values(
                ["_top3_row", "ghs_rank", "ghs_population"],
                ascending=[True, True, False],
            )
            .drop_duplicates("_top3_row")
        )
        matched_rows = selected["_top3_row"].astype(int).to_numpy()
        result.loc[
            matched_rows,
            "top3_match_status",
        ] = "top3_polygon_match"
        for column in (
            "ghs_uc_id",
            "ghs_uc_name",
            "ghs_rank",
            "ghs_population",
        ):
            result.loc[matched_rows, column] = selected[column].to_numpy()

    if result["top3_match_status"].eq("unclassified").any():
        examples = result.loc[
            result["top3_match_status"].eq("unclassified"),
            ["ISO3", "iyear", "latitude", "longitude"],
        ].head(10)
        raise RuntimeError(
            "Some rows remained unclassified. Examples:\n"
            f"{examples.to_string(index=False)}"
        )

    result = apply_top3_specification(result)
    return result.sort_values("_top3_row").drop(columns="_top3_row")


def build_reference_table(
    top3_by_epoch: dict[int, gpd.GeoDataFrame],
) -> pd.DataFrame:
    reference = pd.concat(
        [
            top3.drop(columns="geometry").copy()
            for top3 in top3_by_epoch.values()
        ],
        ignore_index=True,
    )
    return reference.sort_values(
        ["ISO3", "ghs_epoch", "ghs_rank"]
    ).reset_index(drop=True)


def status_overview(classified: pd.DataFrame) -> pd.DataFrame:
    overview = (
        classified.groupby(
            ["top3_match_status", "top3_spec_treatment"],
            dropna=False,
        )
        .size()
        .rename("events")
        .reset_index()
        .sort_values("events", ascending=False)
    )
    overview["share_all_events"] = (
        overview["events"] / len(classified)
    )
    return overview


def grouped_overview(
    classified: pd.DataFrame,
    group_columns: list[str],
) -> pd.DataFrame:
    work = classified.copy()
    work["_top3"] = work["is_top3_ghs_urban_centre"].eq(1)
    work["_outside"] = work["is_top3_ghs_urban_centre"].eq(0)
    work["_excluded"] = work["is_top3_ghs_urban_centre"].isna()
    overview = (
        work.groupby(group_columns, dropna=False)
        .agg(
            events=("top3_match_status", "size"),
            top3_events=("_top3", "sum"),
            outside_top3_events=("_outside", "sum"),
            excluded_events=("_excluded", "sum"),
            coordinate_usable=("ghs_coordinate_usable", "sum"),
            reference_available=("top3_reference_available", "sum"),
        )
        .reset_index()
    )
    overview["top3_share_included"] = (
        overview["top3_events"]
        / (overview["top3_events"] + overview["outside_top3_events"])
    )
    overview["excluded_share"] = (
        overview["excluded_events"] / overview["events"]
    )
    overview["coordinate_coverage"] = (
        overview["coordinate_usable"] / overview["events"]
    )
    return overview


def reference_coverage(
    classified: pd.DataFrame,
    reference: pd.DataFrame,
) -> pd.DataFrame:
    event_counts = (
        classified.groupby(["ISO3", "ghs_epoch"], dropna=False)
        .agg(
            events=("top3_match_status", "size"),
            coordinate_usable=("ghs_coordinate_usable", "sum"),
            classified_top3=("is_top3_ghs_urban_centre", lambda s: s.eq(1).sum()),
            classified_outside=("is_top3_ghs_urban_centre", lambda s: s.eq(0).sum()),
            excluded=("is_top3_ghs_urban_centre", lambda s: s.isna().sum()),
        )
        .reset_index()
    )
    reference_counts = (
        reference.groupby(["ISO3", "ghs_epoch"])
        .agg(
            reference_city_count=("ghs_uc_id", "nunique"),
            rank_1_present=("ghs_rank", lambda s: s.eq(1).any()),
            rank_2_present=("ghs_rank", lambda s: s.eq(2).any()),
            rank_3_present=("ghs_rank", lambda s: s.eq(3).any()),
        )
        .reset_index()
    )
    coverage = event_counts.merge(
        reference_counts,
        on=["ISO3", "ghs_epoch"],
        how="left",
        validate="many_to_one",
    )
    coverage["reference_city_count"] = (
        coverage["reference_city_count"].fillna(0).astype("Int8")
    )
    for column in ("rank_1_present", "rank_2_present", "rank_3_present"):
        coverage[column] = coverage[column].fillna(False).astype(bool)
    coverage["complete_top3_reference"] = (
        coverage["reference_city_count"].eq(3)
    )
    return coverage.sort_values(
        ["ISO3", "ghs_epoch"],
        na_position="last",
    )


def manual_validation_sample(
    classified: pd.DataFrame,
    *,
    per_status: int,
    random_seed: int,
) -> pd.DataFrame:
    if per_status == 0:
        return classified.iloc[0:0].copy()

    samples = []
    statuses = sorted(classified["top3_match_status"].dropna().unique())
    for number, status in enumerate(statuses):
        group = classified.loc[
            classified["top3_match_status"].eq(status)
        ]
        samples.append(
            group.sample(
                n=min(per_status, len(group)),
                random_state=random_seed + number,
            )
        )
    sample = pd.concat(samples, ignore_index=True)
    preferred = [
        "eventid",
        "iyear",
        "imonth",
        "iday",
        "country_txt",
        "ISO3",
        "region_txt",
        "provstate",
        "city",
        "latitude",
        "longitude",
        "specificity",
        "ghs_epoch",
        "top3_match_status",
        "top3_spec_treatment",
        "is_top3_ghs_urban_centre",
        "top3_reference_available",
        "top3_reference_city_count",
        "top3_match_count",
        "ghs_uc_id",
        "ghs_uc_name",
        "ghs_rank",
        "ghs_population",
        "is_capital_dynamic",
        "capital_match_status",
    ]
    return sample[
        [column for column in preferred if column in sample.columns]
    ].sort_values(
        ["top3_match_status", "ISO3", "iyear"],
        na_position="last",
    )


def validate_results(
    original: pd.DataFrame,
    classified: pd.DataFrame,
    reference: pd.DataFrame,
) -> list[str]:
    checks: list[tuple[str, bool]] = [
        ("All input rows preserved", len(original) == len(classified)),
        (
            "Output order preserved",
            classified.index.equals(pd.RangeIndex(len(classified))),
        ),
        (
            "No missing TOP3 status",
            classified["top3_match_status"].notna().all(),
        ),
        (
            "Analytical variable contains only 0, 1, or NA",
            classified["is_top3_ghs_urban_centre"]
            .dropna()
            .isin([0, 1])
            .all(),
        ),
        (
            "All TOP3 matches carry centre metadata",
            classified.loc[
                classified["is_top3_ghs_urban_centre"].eq(1),
                ["ghs_uc_id", "ghs_uc_name", "ghs_rank", "ghs_population"],
            ]
            .notna()
            .all()
            .all(),
        ),
        (
            "All matched ranks are between 1 and 3",
            classified.loc[
                classified["is_top3_ghs_urban_centre"].eq(1),
                "ghs_rank",
            ]
            .between(1, 3)
            .all(),
        ),
        (
            "Reference keys and ranks are unique",
            ~reference.duplicated(["ISO3", "ghs_epoch", "ghs_rank"]).any(),
        ),
        (
            "At most three reference centres per country-epoch",
            reference.groupby(["ISO3", "ghs_epoch"]).size().le(3).all(),
        ),
        (
            "Reference population decreases with rank",
            reference.sort_values(["ISO3", "ghs_epoch", "ghs_rank"])
            .groupby(["ISO3", "ghs_epoch"])["ghs_population"]
            .apply(lambda values: values.is_monotonic_decreasing)
            .all(),
        ),
    ]
    failed = [name for name, passed in checks if not passed]
    if failed:
        raise AssertionError(
            "TOP3 validation failed:\n- " + "\n- ".join(failed)
        )
    return [f"PASS: {name}" for name, _ in checks]


def write_outputs(
    *,
    original: pd.DataFrame,
    classified: pd.DataFrame,
    reference: pd.DataFrame,
    output_dir: Path,
    gpkg: Path,
    start_year: int,
    end_year: int,
    review_per_status: int,
    random_seed: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / OUTPUT_FILENAME
    reference_path = output_dir / REFERENCE_FILENAME
    status_path = output_dir / "ghs_top3_status_overview.csv"
    country_path = output_dir / "ghs_top3_country_overview.csv"
    year_path = output_dir / "ghs_top3_year_overview.csv"
    epoch_path = output_dir / "ghs_top3_epoch_overview.csv"
    coverage_path = output_dir / "ghs_top3_reference_coverage.csv"
    missing_reference_path = (
        output_dir / "ghs_top3_countries_without_reference.csv"
    )
    matched_centres_path = (
        output_dir / "ghs_top3_matched_urban_centres.csv"
    )
    sample_path = output_dir / "ghs_top3_manual_validation_sample.csv"
    multiple_match_path = (
        output_dir / "ghs_top3_multiple_polygon_matches.csv"
    )
    summary_path = output_dir / SUMMARY_FILENAME

    checks = validate_results(original, classified, reference)
    status = status_overview(classified)
    country = grouped_overview(classified, ["ISO3"])
    year = grouped_overview(classified, ["iyear"])
    epoch = grouped_overview(classified, ["ghs_epoch"])
    coverage = reference_coverage(classified, reference)
    missing_reference = coverage.loc[
        coverage["coordinate_usable"].gt(0)
        & coverage["reference_city_count"].eq(0)
    ].copy()
    matched_centres = (
        classified.loc[
            classified["top3_match_status"].eq("top3_polygon_match")
        ]
        .groupby(
            [
                "ISO3",
                "ghs_epoch",
                "ghs_rank",
                "ghs_uc_id",
                "ghs_uc_name",
                "ghs_population",
            ],
            dropna=False,
        )
        .size()
        .rename("matched_events")
        .reset_index()
        .sort_values(
            ["ISO3", "ghs_epoch", "ghs_rank"],
            na_position="last",
        )
    )
    sample = manual_validation_sample(
        classified,
        per_status=review_per_status,
        random_seed=random_seed,
    )
    multiple_columns = [
        "eventid",
        "iyear",
        "country_txt",
        "ISO3",
        "city",
        "latitude",
        "longitude",
        "ghs_epoch",
        "top3_match_count",
        "ghs_uc_id",
        "ghs_uc_name",
        "ghs_rank",
    ]
    multiple_matches = classified.loc[
        classified["top3_match_count"].gt(1),
        [
            column
            for column in multiple_columns
            if column in classified.columns
        ],
    ].copy()

    classified.to_csv(output_path, index=False, encoding="utf-8")
    reference.to_csv(reference_path, index=False, encoding="utf-8")
    status.to_csv(status_path, index=False, encoding="utf-8")
    country.to_csv(country_path, index=False, encoding="utf-8")
    year.to_csv(year_path, index=False, encoding="utf-8")
    epoch.to_csv(epoch_path, index=False, encoding="utf-8")
    coverage.to_csv(coverage_path, index=False, encoding="utf-8")
    missing_reference.to_csv(
        missing_reference_path,
        index=False,
        encoding="utf-8",
    )
    matched_centres.to_csv(
        matched_centres_path,
        index=False,
        encoding="utf-8",
    )
    sample.to_csv(sample_path, index=False, encoding="utf-8")
    multiple_matches.to_csv(
        multiple_match_path,
        index=False,
        encoding="utf-8",
    )

    counts = classified["is_top3_ghs_urban_centre"].value_counts(
        dropna=False
    )
    included = classified["is_top3_ghs_urban_centre"].notna().sum()
    top3 = int(counts.get(1, 0))
    outside = int(counts.get(0, 0))
    excluded = int(
        classified["is_top3_ghs_urban_centre"].isna().sum()
    )
    top3_share = top3 / included if included else float("nan")
    summary_lines = [
        "GHS TOP3 CLASSIFICATION SUMMARY",
        "=" * 31,
        f"GHS GeoPackage: {gpkg}",
        f"Analysis period: {start_year}-{end_year}",
        f"Input events: {len(original):,}",
        f"Output events: {len(classified):,}",
        f"Included in standard TOP3 specification: {included:,}",
        f"TOP3 Urban Centre: {top3:,}",
        f"Outside TOP3 Urban Centres: {outside:,}",
        f"Excluded / NA: {excluded:,}",
        f"TOP3 share among included events: {top3_share:.4%}",
        (
            "Events with missing TOP3 reference despite usable coordinates: "
            f"{int(missing_reference['events'].sum()) if not missing_reference.empty else 0:,}"
        ),
        (
            "Country-epoch combinations without reference: "
            f"{len(missing_reference):,}"
        ),
        f"Events intersecting multiple TOP3 polygons: {len(multiple_matches):,}",
        "",
        "MATCH STATUS",
        status.to_string(index=False),
        "",
        "VALIDATION",
        *checks,
        "",
        "IMPORTANT",
        (
            "The TOP3 classification is independent of is_capital_dynamic. "
            "Capital columns are only carried through from the input."
        ),
        (
            "Change TOP3_STATUS_TREATMENT for robustness checks; all factual "
            "top3_match_status values remain in the event-level output."
        ),
        "",
        f"Event-level output: {output_path}",
    ]
    summary = "\n".join(summary_lines) + "\n"
    summary_path.write_text(summary, encoding="utf-8")
    print(summary)


def main() -> None:
    args = parse_args()
    validate_args(args)
    epochs = tuple(
        epoch
        for epoch in DEFAULT_EPOCHS
        if epoch >= args.start_year - 2 and epoch <= args.end_year + 2
    )
    if not epochs:
        raise ValueError(
            "No GHS epochs are available for the requested analysis period."
        )

    gpkg = find_geopackage(args.ghs_dir)
    print(f"Reading GHS TOP3 reference from: {gpkg}")
    top3_by_epoch = read_top3_by_epoch(gpkg, epochs)

    print(f"Reading GTD events from: {args.gtd_input}")
    gtd = pd.read_csv(args.gtd_input, low_memory=False)
    classified = classify_events(
        gtd,
        top3_by_epoch,
        start_year=args.start_year,
        end_year=args.end_year,
        epochs=epochs,
    )
    reference = build_reference_table(top3_by_epoch)
    write_outputs(
        original=gtd,
        classified=classified,
        reference=reference,
        output_dir=args.output_dir,
        gpkg=gpkg,
        start_year=args.start_year,
        end_year=args.end_year,
        review_per_status=args.review_per_status,
        random_seed=args.random_seed,
    )


if __name__ == "__main__":
    main()
