import country_converter as coco
import pandas as pd

df = pd.read_csv("unctad_fdi_inflow_perc.csv")

df.loc[df["economy_label"].isin(["TÃ¼rkiye", "TÃ¼rkiye, Republic of"]), "economy_label"] = "Turkey"
df.loc[df["economy_label"] == "Aruba, Kingdom of the Netherlands", "economy_label"] = "Aruba"
df.loc[df["economy_label"] == "China, Taiwan Province of", "economy_label"] = "Taiwan"

df["ISO3"] = coco.convert(names=df["economy_label"], to="ISO3")

df.to_csv("unctad_fdi_inflow_perc.csv")


