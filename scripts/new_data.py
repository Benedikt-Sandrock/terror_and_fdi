import pandas as pd
import unicodedata
import country_converter as coco
from itertools import product


def remove_accents(text):
    if pd.isnull(text):
        return text
    return ''.join(
        c for c in unicodedata.normalize('NFKD', text)
        if not unicodedata.combining(c)
    )

gtd = pd.read_csv("gtd_cities.csv")

### convert country names to ISO3 - already done
#gtd['ISO3'] = coco.convert(names=gtd['economy_label'], to='ISO3')
#gtd.to_csv("gtd_cities.csv", index = False)
gtd = gtd[gtd["doubtterr"] == 0]

gtd["city"] = gtd["city"].apply(remove_accents).str.lower().str.strip()

city_data = pd.read_csv("worldcities.csv", usecols =["city", "iso3", "capital", "population"])
city_data = city_data.rename(columns = {"iso3": "ISO3"})
city_data["city"] = city_data["city"].apply(remove_accents).str.lower().str.strip()

gtd = pd.merge(gtd, city_data, on = ["ISO3", "city"], how = "left", indicator = True)
print(gtd["_merge"].value_counts())

gtd["is_capital"] = (gtd["capital"] == "primary")

# Rank cities by population within each country
city_ranks = gtd[["ISO3", "city", "population"]].drop_duplicates()
city_ranks["population_rank"] = city_ranks.groupby("ISO3")["population"].rank(method="first", ascending = False)

gtd = pd.merge(gtd, city_ranks, on=["city", "ISO3"], how= "left")
#print(gtd["_merge"].value_counts())

# Create a dummy column for the top 3 most populous cities
gtd["top3_population_dummy"] = (gtd["population_rank"] <= 3).astype(int)
print(gtd[gtd["economy_label"] == "Afghanistan"])


gtd_cap = gtd[gtd["is_capital"] == 1].groupby(["ISO3", "year"], as_index=False).agg(
    incidents_cap=("economy_label", "count"),
    total_fatalities_cap=("nkill", "sum"),
    fatalities_ter_cap=("nkillter", "sum"),
    total_wounded_cap=("nwound", "sum"),
    wounded_ter_cap=("nwoundte", "sum"),
    total_success_cap=("success", "sum"),
)

# Group for non-capitals only
gtd_noncap = gtd[gtd["is_capital"] == 0].groupby(["ISO3", "year"], as_index=False).agg(
    incidents_noncap=("economy_label", "count"),
    total_fatalities_noncap=("nkill", "sum"),
    fatalities_ter_noncap=("nkillter", "sum"),
    total_wounded_noncap=("nwound", "sum"),
    wounded_ter_noncap=("nwoundte", "sum"),
    total_success_noncap=("success", "sum"),
)

#same for cities that are in the top 3 of the population

gtd_top3 = gtd[gtd["top3_population_dummy"] == 1].groupby(["ISO3", "year"], as_index=False).agg(
    incidents_top3=("economy_label", "count"),
    total_fatalities_top3=("nkill", "sum"),
    fatalities_ter_top3=("nkillter", "sum"),
    total_wounded_top3=("nwound", "sum"),
    wounded_ter_top3=("nwoundte", "sum"),
    total_success_top3=("success", "sum"),
)

gtd_nottop3 = gtd[gtd["top3_population_dummy"] == 0].groupby(["ISO3", "year"], as_index=False).agg(
    incidents_nottop3=("economy_label", "count"),
    total_fatalities_nottop3=("nkill", "sum"),
    fatalities_ter_nottop3=("nkillter", "sum"),
    total_wounded_nottop3=("nwound", "sum"),
    wounded_ter_nottop3=("nwoundte", "sum"),
    total_success_nottop3=("success", "sum"),
)

gtd_merged = (
    gtd_cap
    .merge(gtd_noncap, on=["ISO3", "year"], how="outer")
    .merge(gtd_top3, on=["ISO3", "year"], how="outer")
    .merge(gtd_nottop3, on=["ISO3", "year"], how="outer")
)

gtd["attack_category"] = gtd["targtype1"].apply(lambda x: "business" if x == 1 else "nonbusiness")

# Group by ISO3, year, capital status, and attack_category
gtd_grouped = (
    gtd.groupby(["ISO3", "year", "is_capital", "attack_category"], as_index=False)
       .agg(
           incidents=("economy_label", "count"),
           total_fatalities=("nkill", "sum"),
           total_wounded=("nwound", "sum")
       )
)

# Pivot to get separate columns for each combination
gtd_pivot = gtd_grouped.pivot_table(
    index=["ISO3", "year"],
    columns=["is_capital", "attack_category"],
    values=["incidents", "total_fatalities", "total_wounded"],
    fill_value=0
)

# Flatten MultiIndex columns with consistent naming
gtd_pivot.columns = [
    f"{var}_cap{int(cap)}_{cat}"
    for var, cap, cat in gtd_pivot.columns
]

# Reset index to merge
gtd_pivot = gtd_pivot.reset_index()

# Merge with your existing dataset
gtd_merged = gtd_merged.merge(gtd_pivot, on=["ISO3", "year"], how="outer")


gtd_grouped = (
    gtd.groupby(["ISO3", "year", "top3_population_dummy", "attack_category"], as_index=False)
       .agg(
           incidents=("economy_label", "count"),
           total_fatalities=("nkill", "sum"),
           total_wounded=("nwound", "sum")
       )
)

# Pivot to get separate columns for each combination
gtd_pivot = gtd_grouped.pivot_table(
    index=["ISO3", "year"],
    columns=["top3_population_dummy", "attack_category"],
    values=["incidents", "total_fatalities", "total_wounded"],
    fill_value=0
)

# Flatten MultiIndex columns with consistent naming
gtd_pivot.columns = [
    f"{var}_top3{int(top3)}_{cat}"
    for var, top3, cat in gtd_pivot.columns
]

# Reset index to merge
gtd_pivot = gtd_pivot.reset_index()

# Merge with your existing dataset
gtd_merged = gtd_merged.merge(gtd_pivot, on=["ISO3", "year"], how="outer")


all_countries = gtd_merged["ISO3"].unique()
print(all_countries)
all_years = gtd_merged["year"].unique()
print(all_years)

country_year_grid = pd.DataFrame(list(product(all_countries, all_years)), columns=["ISO3", "year"])

full_data = country_year_grid.merge(gtd_merged, on=["ISO3", "year"], how="left")

full_data= full_data.fillna(0)

# gtd_2 = gtd.groupby(["ISO3", "year"], as_index = False).agg(
#     incidents_cap =("economy_label", "count"),
#     total_fatalities_cap = ("nkill", "sum"),
#     fatalities_ter_cap  = ("nkillter", "sum"),
#     total_wounded_cap = ("nwound", "sum"),
#     wounded_ter_cap = ("nwoundte", "sum"),
#
#     incidents_noncap =("economy_label", "count"),
#     total_fatalities_noncap = ("nkill", "sum"),
#     fatalities_ter_noncap  = ("nkillter", "sum"),
#     total_wounded_noncap = ("nwound", "sum"),
#     wounded_ter_noncap = ("nwoundte", "sum"),
#     #weapon_type = ("weaptype1", "first"),
#     #attack_type = ("attacktype1", "first")
#     )

full_data.to_stata("gtd_stata2.dta")


vdem = pd.read_csv("vdem.csv", usecols = ["country_text_id", "year", "v2x_libdem",
                                          "v2x_accountability", "v2x_corr", "v2x_execorr", "v2x_pubcorr",
                                          "v2x_rule", "v2xcl_prpty","v2clkill","v2x_clphy"])

vdem.columns = ["ISO3", "year", "libdem","accountability", "political_corruption", "executive_corruption",
                "publicsector_corruption", "rule_of_law", "property_rights", "freedom_from_political_killings",
                "physical_violence_index"]

ucdpprio = pd.read_csv("ucdprio.csv")

ucdpprio = ucdpprio[ucdpprio["type_of_conflict"].isin([3])] # include 2 for interstate conflict and 4 for internationalized intrastate

ucdpprio = ucdpprio[["location", "year", "type_of_conflict"]]
ucdpprio["type_of_conflict"] = 1
ucdpprio.columns = ["economy_label", "year", "internal_conflict"]

ucdpprio["ISO3"] = coco.convert(names=ucdpprio["economy_label"], to = "ISO3")
ucdpprio.to_csv("ucdpprio2.csv")
#ucdpprio = ucdpprio.drop("economy_label", axis = 1)
ucdpprio= ucdpprio.groupby(["ISO3", "year"]).agg(internal_conflict = ("internal_conflict", "max"))

vdem = pd.merge(vdem, ucdpprio, on=["ISO3", "year"], how = "outer")

vdem = vdem[vdem["ISO3"] != "not found"]
vdem = vdem[vdem["year"] >= 1970]
vdem.to_stata("vdem.dta")