import pandas as pd
import unicodedata
import country_converter as coco

def remove_accents(text):
    if pd.isnull(text):
        return text
    return ''.join(
        c for c in unicodedata.normalize('NFKD', text)
        if not unicodedata.combining(c)
    )

gtd = pd.read_csv("gtd_cities.csv")

### convert country names to ISO3 - already done
gtd['ISO3'] = coco.convert(names=gtd['economy_label'], to='ISO3')
gtd.to_csv("gtd_cities.csv", index = False)
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

### group by capital/non-capital

gtd_1 = gtd.groupby(["economy_label", "year", "is_capital"], as_index = False).agg(
    number_of_attacks=("economy_label", "count"),
    total_fatalities= ("nkill", "sum"),
    fatalities_ter = ("nkillter", "sum"),
    total_wounded = ("nwound", "sum"),
    wounded_ter = ("nwoundte", "sum"),
    propextent = ("propextent", "sum"),
    hostages = ("nhostkid", "sum"),
    is_capital = ("is_capital", "first"),
    #top3_population= ("top3_population_dummy", "first")
    total_success = ("success", "sum"),
    ISO3 = ("ISO3", "first"),
    #weapon_type = ("weaptype1", "first"),
    #attack_type = ("attacktype1", "first")
    )

gtd_2 = gtd.groupby(["economy_label", "year"], as_index = False).agg(
    number_of_attacks=("economy_label", "count"),
    total_fatalities= ("nkill", "sum"),
    fatalities_ter = ("nkillter", "sum"),
    total_wounded = ("nwound", "sum"),
    wounded_ter = ("nwoundte", "sum"),
    propextent = ("propextent", "sum"),
    hostages = ("nhostkid", "sum"),
    is_capital = ("is_capital", "sum"),
    top3_population= ("top3_population_dummy", "sum"),
    total_success = ("success", "sum"),
    ISO3 = ("ISO3", "first"),
    #weapon_type = ("weaptype1", "first"),
    #attack_type = ("attacktype1", "first")
    )
# gtd = gtd.pivot(
#     index=["economy_label", "year", "ISO3"],
#     columns="is_capital"
# )


gtd_1["success_rate"] = gtd_1["total_success"] / gtd_1["number_of_attacks"]
print(gtd_1["success_rate"].describe())
gtd_2["success_rate"] = gtd_2["total_success"] / gtd_2["number_of_attacks"]


gtd_1.to_stata("gtd_capital.dta")
gtd_2.to_stata("gtd_stata.dta")
