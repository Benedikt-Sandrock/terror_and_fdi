from global_macro_data import gmd
import pandas as pd
from terror_and_fdi.config import RAW

OUTPUT_FILE = RAW / "gmd" / "gmd.csv"

VARIABLES = [
    "deflator", "exports_GDP", "imports_GDP", "finv_GDP", "infl",
    "REER", "ltrate", "strate",
]

df = gmd(version = "2026_03", fast = "yes", variables=VARIABLES)
print(df.head())
print(df.columns)

start_year = 1960
end_year = 2025

df_filtered = df[(df['year'] >= start_year) & (df['year'] <= end_year)]

df_filtered = df_filtered.sort_values(by=['ISO3', 'year']).reset_index(drop=True)
df_filtered["year"] = df_filtered["year"].astype(int)
df_filtered = df_filtered.drop(columns="id")

df_filtered.to_csv(OUTPUT_FILE, index = False)