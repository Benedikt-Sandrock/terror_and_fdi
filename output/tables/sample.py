import pandas as pd


df = pd.read_csv("screen_stage2_grid_run1.csv")

df["fdivar"] = "inflow"

df.to_csv("screen_stage2_grid_run1.csv", index=False)