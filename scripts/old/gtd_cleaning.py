import pandas as pd
import country_converter as coco
from itertools import product


gtd = pd.read_excel("gtd.xlsx", usecols=["iyear", "country_txt", "doubtterr", "nkill", "nkillter", "nwound", "nwoundte", "propextent", "nhostkid"])
gtd.columns = ["year", "economy_label", "doubtterr", "nkill", "nkillter", "nwound", "nwoundte","propextent", "nhostkid"]
gtd["nhostkid"] = gtd["nhostkid"].replace(-99, 0)
gtd["propextent"] = gtd["propextent"].replace({4:0, 3:1, 2:2, 1:3})

print(gtd["doubtterr"].value_counts(dropna=False))
gtd = gtd[gtd["doubtterr"] == 0]

gtd_collapsed = gtd.groupby(["economy_label", "year"], as_index = False).agg(
    number_of_attacks=("economy_label", "count"),
    total_fatalities= ("nkill", "sum"),
    fatalities_ter = ("nkillter", "sum"),
    total_wounded = ("nwound", "sum"),
    wounded_ter = ("nwoundte", "sum"),
    propextent = ("propextent", "sum"),
    hostages = ("nhostkid", "sum")
    )


all_countries = gtd["economy_label"].unique()
print(all_countries)
all_years = gtd["year"].unique()
print(all_years)

country_year_grid = pd.DataFrame(list(product(all_countries, all_years)), columns=["economy_label", "year"])

full_data = country_year_grid.merge(gtd_collapsed, on=["economy_label", "year"], how="left")

full_data[["number_of_attacks", "total_fatalities", "fatalities_ter","total_wounded", "wounded_ter","propextent", "hostages"]] = \
    full_data[["number_of_attacks", "total_fatalities", "fatalities_ter","total_wounded", "wounded_ter","propextent", "hostages"]].fillna(0)

full_data['ISO3'] = coco.convert(names=full_data['economy_label'], to='ISO3')

full_data.to_csv('gtd.csv', index=False)
# Stata code that needs to be executed:
# rename iso3 ISO3
# drop if year < 1996
# drop if ISO3 == "not found"
# drop if economy == "Rhodesia"
# drop if economy == "Zaire"
# drop if econ == "Czechoslovakia"
# drop if econ == "New Hebrides"
# drop if econ =="North Yemen" | econ == "South Yemen"
# drop economy_label