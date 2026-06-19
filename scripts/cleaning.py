import pandas as pd
import country_converter as coco
from global_macro_data import gmd

df_standardized = pd.read_csv("data_python.csv")
df_standardized.loc[df_standardized["economy_label"].isin(["TÃ¼rkiye", "TÃ¼rkiye, Republic of"]), "economy_label"] = "Turkey"
df_standardized.loc[df_standardized["economy_label"] == "Aruba, Kingdom of the Netherlands", "economy_label"] = "Aruba"
df_standardized.loc[df_standardized["economy_label"] == "China, Taiwan Province of", "economy_label"] = "Taiwan"

vdem = pd.read_csv("vdem.csv", usecols = ["country_name", "year", "v2x_libdem",
                                          "v2x_accountability", "v2x_corr", "v2x_execorr", "v2x_pubcorr",
                                          "v2x_rule", "v2xcl_prpty"])
vdem = vdem[vdem["year"] > 1999]
vdem.columns = ["economy_label", "year", "libdem","accountability", "political_corruption", "executive_corruption",
                "publicsector_corruption", "rule_of_law", "property_rights"]

df_standardized = pd.merge(df_standardized, vdem, on=["economy_label", "year"], how="outer")

ucdpprio = pd.read_csv("ucdprio.csv")

ucdpprio = ucdpprio[ucdpprio["type_of_conflict"].isin([3])] # include 2 for interstate conflict and 4 for internationalized intrastate

ucdpprio = ucdpprio[["location", "year", "type_of_conflict"]]
ucdpprio["type_of_conflict"] = 1
ucdpprio.columns = ["economy_label", "year", "internal_conflict"]
df_standardized = pd.merge(df_standardized, ucdpprio, on=["economy_label", "year"], how = "outer")

df_gmd = gmd(variables=["inv_GDP", "strate", "ltrate", "unemp"])
df_gmd = df_gmd[df_gmd["year"] > 1999]
df_gmd = df_gmd.drop("ISO3", axis = 1)
df_gmd =df_gmd.rename(columns={"countryname":"economy_label"})

df_standardized = pd.merge(df_standardized, df_gmd, on=["economy_label", "year"], how ="outer")

df_standardized["economy_label"] = df_standardized["economy_label"].replace({"Anguilla, United Kingdom-British Overseas Territory": "Anguilla",
                                                                    "Curaçao, Kingdom of the Netherlands":"Curaçao",
                                                                    "Montserrat, United Kingdom-British Overseas Territory": "Montserrat",
                                                                    "Sint Maarten, Kingdom of the Netherlands": "Sint Maarten"
                                                                    })

df_standardized['ISO3'] = coco.convert(names=df_standardized['economy_label'], to='ISO3')

#df_standardized["ISO3"] = df_standardized["ISO3"].replace({"['CHN', 'TWN']": "TWN"})
df_standardized["ISO3"] = df_standardized["ISO3"].replace({"['ABW', 'NLD']": "ABW"})
df_standardized["ISO3"] = df_standardized["ISO3"].replace({"['CUW', 'NLD']": "CUW"})

#check what couldn't be assigned
missing_iso3 = df_standardized[df_standardized['ISO3'] == "not found"]
unique_missing = missing_iso3.drop_duplicates(subset='economy_label')
print(unique_missing)

df_standardized = df_standardized[df_standardized["ISO3"] != "not found"]


df_standardized['ISO3'] = df_standardized['ISO3'].astype(str).replace('nan', '')

#df_standardized = pd.merge(df_standardized, df_gmd, on=["ISO3", "year"], how ="outer")
df_standardized["UNregion"] = coco.convert(names=df_standardized["ISO3"], to ="UNregion")


df_map = pd.read_excel("country_metadata.xlsx", sheet_name = "Country - Metadata") #requires installation of openpyxl
df_map = df_map[["Code", "Region"]]
df_map.columns = ["ISO3", "WBregion"]

df_standardized = df_standardized.merge(df_map, on='ISO3', how='left')

agg_dict = {
    'economy_label': 'first',
    'net_fdi': 'max',
    "stock_inflow": "max",
    "stock_outflow": "max",
    "inward_stock_abs": "max",
    "outward_stock_abs": "max",
    'GDP_per_capita': 'max',
    'population_above_65': 'max',
    'population_below_14': 'max',
    'population_total': 'max',
    'economic_freedom': 'first',
    'investmentfreedom': 'first',
    'government_cons_exp': 'max',
    'gdp': 'max',
    'gdp_growth': 'max',
    'reer': 'max',
    'UNregion': 'first',
    'WBregion': 'first',
    #'in_186_sample': 'max',
    #'in_110_sample': 'max',
    #'in_98_sample': 'max',
    "libdem": "first",
    "accountability": "first",
    "political_corruption": "first",
    "executive_corruption": "first",
    "publicsector_corruption": "first",
    "rule_of_law": "max",
    "property_rights": "first",
    "internal_conflict": "max",
    "exrate_volatility": "max",
    "fdi_restrictions": "first",
    "inv_GDP": "max",
    "ltrate": "max",
    "strate": "max",
    "unemp": "max",
    "avg_monthly_earning1": "max",
    "avg_monthly_earning2": "max",
    "avg_monthly_earning3": "max"

#'_merge': 'first'
}

df_collapsed = df_standardized.groupby(['ISO3', 'year']).agg(agg_dict).reset_index()

df_collapsed.to_stata('output_file.dta')

