# from pathlib import Path
# import geopandas as gpd
#
# gpkg = Path(
#     r"C:\Users\Benedikt\PycharmProjects\terror_and_fdi"
#     r"\data\raw\ghs_ucdb\GHS_UCDB_MTUC_GLOBE_R2024A_V1_2\GHS_UCDB_MTUC_GLOBE_R2024A.gpkg"
# )
#
# print("Dateiname:", gpkg.name)
# print("Existiert:", gpkg.exists())
# print("Größe in MB:", round(gpkg.stat().st_size / 1024**2, 1))
# print("\nLayer:")
# print(gpd.list_layers(gpkg).to_string(index=False))
#
# import geopandas as gpd
#
# layer = "GHSL_UCDB_MTUC_1995_GLOBE_R2024"
#
# sample = gpd.read_file(
#     gpkg,
#     layer=layer,
#     rows=5,
# )
#
# print("CRS:", sample.crs)
# print("\nGeometrietypen:")
# print(sample.geometry.geom_type.value_counts(dropna=False))
#
# print("\nSpalten:")
# print(sample.columns.to_list())
#
# print("\nErste Zeilen:")
# print(sample.head())


import pandas as pd
from terror_and_fdi.config import RAW

df = pd.read_csv(RAW / "gtd" / "gtd_1993.csv")

df = df[df["iyear"] > 2018]

df.to_csv(RAW / "gtd" / "gtd_2018.csv")

