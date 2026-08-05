import geopandas as gpd
import pandas as pd
from terror_and_fdi.config import RAW, INTERIM

gpkg = (
    RAW
    / "ghs_ucdb"
    / "GHS_UCDB_MTUC_GLOBE_R2024A_V1_2"
    / "GHS_UCDB_MTUC_GLOBE_R2024A.gpkg"
)

layer = "GHSL_UCDB_MTUC_GLOBE_R2024"

ghs = gpd.read_file(
    gpkg,
    layer=layer,
)

country_col = "GC_CNT_GAD_2025"
name_col = "GC_UCN_MAI_2025"

eswatini = ghs.loc[
    ghs[country_col]
    .astype("string")
    .str.contains(
        r"eswatini|swazi",
        case=False,
        na=False,
    )
].copy()

cols = [
    "ID_MTUC_G0",
    country_col,
    name_col,
    "MT_POP_TOT_1995",
    "MT_POP_TOT_2000",
    "MT_POP_TOT_2005",
    "MT_POP_TOT_2010",
    "MT_POP_TOT_2015",
    "MT_POP_TOT_2020",
]

print(eswatini[cols].to_string(index=False))

GPKG_FILE = (
    RAW
    / "ghs_ucdb"
    / "GHS_UCDB_MTUC_GLOBE_R2024A_V1_2"
    / "GHS_UCDB_MTUC_GLOBE_R2024A.gpkg"
)

LAYER = "GHSL_UCDB_MTUC_GLOBE_R2024"


# GHS-Basis-Layer einlesen
ghs = gpd.read_file(
    GPKG_FILE,
    layer=LAYER,
)

# Für Längen- und Breitengrade nach WGS84 umprojizieren
ghs_wgs84 = ghs.to_crs("EPSG:4326").copy()

# Der Basis-Layer enthält Punktgeometrien
ghs_wgs84["longitude"] = ghs_wgs84.geometry.x
ghs_wgs84["latitude"] = ghs_wgs84.geometry.y

# Großzügiger geografischer Ausschnitt rund um Hongkong
hongkong_area = ghs_wgs84.loc[
    ghs_wgs84["longitude"].between(113.8, 114.5)
    & ghs_wgs84["latitude"].between(22.1, 22.6)
].copy()

output_columns = [
    "ID_MTUC_G0",
    "GC_CNT_GAD_2025",
    "GC_UCN_MAI_2025",
    "longitude",
    "latitude",
    "MT_POP_TOT_1995",
    "MT_POP_TOT_2000",
    "MT_POP_TOT_2005",
    "MT_POP_TOT_2010",
    "MT_POP_TOT_2015",
    "MT_POP_TOT_2020",
]

print(
    hongkong_area[output_columns]
    .sort_values("MT_POP_TOT_2020", ascending=False)
    .to_string(index=False)
)