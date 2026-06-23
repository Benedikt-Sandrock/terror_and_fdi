"""
Loads and cleans all sources for the main analysis.
Always configure input and output path as well as needed variables.
"""
import pandas as pd
import country_converter as coco
import logging
import time
from terror_and_fdi.config import RAW, INTERIM

# ==============================================================
# CONFIGURATION
# ==============================================================
# Specify which sources need to be cleaned
CLEAN_V_DEM = False
CLEAN_PWT = False
CLEAN_TAX = False
CLEAN_UCDP = False
CLEAN_WORLD_BANK = False
CLEAN_WORLD_CITIES = False
CLEAN_GTD = True

logging.getLogger('country_converter').setLevel(logging.CRITICAL)
cc = coco.CountryConverter()

# ==============================================================
# V-DEM
# ==============================================================
if CLEAN_V_DEM:
    V_DEM_INPUT = RAW / "v_dem" / "v_dem_core_v16.csv"
    V_DEM_OUTPUT = INTERIM / "v_dem_processed.csv"

    V_DEM_VARS_DICT = [
        {
         "code": "country_name",
         "name": "",
         "definition": "",
         "scale": ""
        },
        {
         "code": "country_text_id",
         "name": "",
         "definition": "",
         "scale": ""
        },
        {
         "code": "year",
         "name": "",
         "definition": "",
         "scale": ""
        },
        {
         "code": "v2x_libdem",
         "name": "Liberal Democracy Index",
         "definition": "To what extent is the ideal of liberal democracy achieved?",
         "scale": "0-1"
        },
        {
         "code": "v2x_accountability",
         "name": "Accountability index",
         "definition": "To what extent is the ideal of government accountability achieved?",
         "scale": "0-1"
        },
        {
         "code": "v2x_rule",
         "name": "Rule of law index",
         "definition": " To what extent are laws transparently, independently, predictably, impartially, and equally enforced, and to what extent do the actions of government officials comply with the law?",
         "scale": "0-1"
        },
        {
         "code": "v2xcl_prpty",
         "name": "Property rights",
         "definition": "Do citizens enjoy the right to private property?",
         "scale": "0-1"
        },
        {
         "code": "v2x_clphy",
         "name": "Physical violence index",
         "definition": " To what extent is physical integrity respected? Average of 'freedom from torture' and 'freedom from political killings'",
         "scale": "0-1"
        },
        {
         "code": "v2cltort",
         "name": "Freedom from torture",
         "definition": "Is there freedom from torture?",
         "scale": "0-4"
        },
        {
         "code": "v2clkill",
         "name": "Freedom from political killings",
         "definition": "Is there freedom from political killings?",
         "scale": "0-4"
        },
    ]

    V_DEM_VARS = [item["code"] for item in V_DEM_VARS_DICT]

    v_dem_df = pd.read_csv(V_DEM_INPUT, usecols = V_DEM_VARS)

    v_dem_df = v_dem_df.drop(columns = ["country_name"]).rename(columns = {"country_text_id": "ISO3"})

    v_dem_df.to_csv(V_DEM_OUTPUT, index = False)


# ==============================================================
# PWT - HUMAN CAPITAL
# ==============================================================
if CLEAN_PWT:
    PWT_INPUT = RAW / "pwt" / "pwt110.xlsx"
    PWT_OUTPUT = INTERIM / "pwt_processed.csv"

    pwt_df = pd.read_excel(PWT_INPUT, sheet_name = 2, usecols = ["countrycode", "year", "hc"])
    pwt_df = pwt_df.rename(columns = {"countrycode": "ISO3"})
    pwt_df.to_csv(PWT_OUTPUT, index = False)


# ==============================================================
# TAX FOUNDATION
# ==============================================================
if CLEAN_TAX:
    TAX_INPUT = RAW / "tax_foundation" / "rates_final.csv"
    TAX_OUTPUT = INTERIM / "stat_tax_rate_processed.csv"

    tax_df = pd.read_csv(TAX_INPUT)

    tax_df = tax_df.drop(columns = ["iso_2", "continent", "country"])
    tax_df = pd.melt(
        tax_df, id_vars="iso_3", var_name = "year", value_name="stat_corp_tax_rate"
    )

    tax_df = tax_df.sort_values(by = "iso_3").rename(columns = {"iso_3": "ISO3"})
    tax_df.to_csv(TAX_OUTPUT, index = False)


# ==============================================================
# UCDP
# ==============================================================
if CLEAN_UCDP:
    UCDP_INPUT = RAW / "ucdpprio" / "OrganizedViolenceCYDataSet26_1.csv"
    UCDP_OUTPUT = INTERIM / "state_based_violence_processed.csv"
    UCDP_VARS = ["country", "year", "sb_exist", "sb_intrastate_exist", "sb_interstate_exist"]

    df = pd.read_csv(UCDP_INPUT, usecols = UCDP_VARS)
    df = df[~df["country"].str.contains("German Democratic Republic")]
    df["ISO3"] = cc.convert(names = df["country"], to = "ISO3")
    df = df.drop(columns = "country")

    df.to_csv(UCDP_OUTPUT, index = False)


# ==============================================================
# WORLD BANK
# ==============================================================
if CLEAN_WORLD_BANK:
    WORLD_BANK_INPUT = RAW / "world_bank" / "wb_data.csv"
    WORLD_BANK_OUTPUT = INTERIM / "wb_data_processed.csv"

    df = pd.read_csv(WORLD_BANK_INPUT)
    df["ISO3"] = cc.convert(names = df["country_code"], to = "ISO3")
    df = df.drop(columns= ["country", "country_code"])

    df.to_csv(WORLD_BANK_OUTPUT, index = False)


# ==============================================================
# WORLD CITIES
# ==============================================================
CITIES_OUTPUT_PATH = INTERIM / "cities_processed.csv"

if CLEAN_WORLD_CITIES:
    CITIES_INPUT_PATH = RAW / "worldcities.csv"
    COLS_CITIES = ["city_ascii", "iso3", "capital", "population"]

    df_cities = pd.read_csv(CITIES_INPUT_PATH, usecols = COLS_CITIES)

    df_cities["is_capital"] = (df_cities["capital"] == "primary").astype(int)
    df_cities["is_top3"] = (df_cities.groupby("iso3")["population"].rank(ascending = False, method = "first") <= 3).astype(int)
    df_cities = df_cities.drop(columns = ["capital", "population"]).rename(columns = {"city_ascii": "city", "iso3": "ISO3"})

    df_cities.to_csv(CITIES_OUTPUT_PATH, index = False)


# ==============================================================
# GTD
# ==============================================================
if CLEAN_GTD:
    start_time = time.perf_counter()
    GTD_INPUT_PATH = RAW / "gtd" / "gtd.csv"
    GTD_OUTPUT_PATH = INTERIM / "gtd_processed.cscv"

    VARS_GTD = [
        {
            "code": "doubtterr",
            "definition": "1 = 'Yes' There is doubt as to whether the incident is an act of terrorism. 0 = 'No' There is essentially no doubt as to whether the incident is an act of terrorism.",
        },
        {
            "code": "country_txt",
            "definition": "Country of the incident location.",
        },
        {
            "code": "iyear",
            "definition": "Year",
        },
        {
            "code": "city",
            "definition": "City of the incident location.",
        },
        {
            "code": "vicinity",
            "definition": "1: Incident in the immdiate vicinity of the city. 0: Incident in the city itself.",
        },
        {
            "code": "attacktype1",
            "definition": "General method of attack. 1-8 for different types, 9 = unknown.",
        },
        {
            "code": "success",
            "definition": "Attack successful or not.",
        },
        {
            "code": "suicide",
            "definition": "Suicide attack or not.",
        },
        {
            "code": "weaptype1",
            "definition": "Type of weapon used in the attack, 1-12, 13 = unknown.",
        },
        {
            "code": "targtype1",
            "definition": "Target type. 1 = Business.",
        },
        {
            "code": "targsubtype1",
            "definition": "More specific target category. 4 = MNC.",
        },
        {
            "code": "natlty1_txt",
            "definition": "Nationality of the target. Not necessarily the same as the country in which the incident occured.",
        },
        {
            "code": "nkill",
            "definition": "Total number of fatalities.",
        },
        {
            "code": "nkillus",
            "definition": "Total number of US fatalities.",
        },
        {
            "code": "nwound",
            "definition": "Total number of wounded.",
        },
        {
            "code": "nwoundus",
            "definition": "Total number of US wounded.",
        },
        {
            "code": "property",
            "definition": "Evidence of property damage. 1 = Yes, 0 = No, -9 = Unknown.",
        },
        {
            "code": "propextent",
            "definition": "Extent of property damage. 1 = > 1B, 2 > 1M, 3 < 1M, 4 = unknown.",
        },
        {
            "code": "propvalue",
            "definition": "Value of property damage.",
        },
    ]
    COLS_GTD = [item["code"] for item in VARS_GTD]

    df = pd.read_csv(GTD_INPUT_PATH, usecols = COLS_GTD)
    print("Creating variables and aggreating the dataset.")
    df['nkill'] = df['nkill'].fillna(0)
    df['nwound'] = df['nwound'].fillna(0)
    df['casualties'] = df['nkill'] + df['nwound']
    df["is_business"] = df["targtype1"] == 1

    if not CLEAN_WORLD_CITIES:
        df_cities = pd.read_csv(CITIES_OUTPUT_PATH)

    df = pd.merge(df, df_cities, on = "city", how = "left")


    # --- CAPITAL VS. PERIPHERY ---
    df['cas_capital'] = df['casualties'].where(df['is_capital'] == True, 0)
    df['cas_no_capital'] = df['casualties'].where(df['is_capital'] == False, 0)
    df['inc_capital'] = df['success'].where(df['is_capital'] == True, 0)  # Counting incidents
    df['fat_capital'] = df['nkill'].where(df['is_capital'] == True, 0)

    # --- TOP 3 VS. PERIPHERY ---
    df['cas_top3'] = df['casualties'].where(df['is_top3'] == True, 0)
    df['cas_no_top3'] = df['casualties'].where(df['is_top3'] == False, 0)
    df['inc_top3'] = df['success'].where(df['is_top3'] == True, 0)
    df['fat_top3'] = df['nkill'].where(df['is_top3'] == True, 0)

    # --- CAPITAL x TARGET TYPE ---
    df['cas_cap_biz'] = df['casualties'].where((df['is_capital'] == True) & (df['is_business'] == True), 0)
    df['cas_cap_nobiz'] = df['casualties'].where((df['is_capital'] == True) & (df['is_business'] == False), 0)

    # Casualties outside the capital separated by business / non-business
    df['cas_nocap_biz'] = df['casualties'].where((df['is_capital'] == False) & (df['is_business'] == True), 0)
    df['cas_nocap_nobiz'] = df['casualties'].where((df['is_capital'] == False) & (df['is_business'] == False), 0)

    # Incidents (successful) in the capital separated by business / non-business
    df['inc_cap_biz'] = df['success'].where((df['is_capital'] == True) & (df['is_business'] == True), 0)
    df['inc_cap_nobiz'] = df['success'].where((df['is_capital'] == True) & (df['is_business'] == False), 0)

    # --- TOP 3 x TARGET TYPE ---
    # Casualties in top 3 cities separated by business / non-business
    df['cas_top3_biz'] = df['casualties'].where((df['is_top3'] == True) & (df['is_business'] == True), 0)
    df['cas_top3_nobiz'] = df['casualties'].where((df['is_top3'] == True) & (df['is_business'] == False), 0)

    # Casualties outside the top 3 cities separated by business / non-business
    df['cas_notop3_biz'] = df['casualties'].where((df['is_top3'] == False) & (df['is_business'] == True), 0)
    df['cas_notop3_nobiz'] = df['casualties'].where((df['is_top3'] == False) & (df['is_business'] == False), 0)

    # Incidents in top-3 cities separated by business / non-business
    df['inc_top3_biz'] = df['success'].where((df['is_top3'] == True) & (df['is_business'] == True), 0)
    df['inc_top3_nobiz'] = df['success'].where((df['is_top3'] == True) & (df['is_business'] == False), 0)

    panel_df = df.groupby(['country_txt', 'iyear']).agg(
        # 1. Total per country-year
        incidents_total=('success', 'count'),
        fatalities_total=('nkill', 'sum'),
        wounded_total=('nwound', 'sum'),
        casualties_total=('casualties', 'sum'),

        # 2. Capital vs. rest
        casualties_capital=('cas_capital', 'sum'),
        casualties_no_capital=('cas_no_capital', 'sum'),
        incidents_capital=('inc_capital', 'count'),

        # 3. Top-3 vs. rest
        casualties_top3=('cas_top3', 'sum'),
        casualties_no_top3=('cas_no_top3', 'sum'),
        incidents_top3=('inc_top3', 'count'),

        # Capital x target type aggregation
        cas_capital_business = ('cas_cap_biz', 'sum'),
        cas_capital_nonbusiness = ('cas_cap_nobiz', 'sum'),
        cas_nocapital_business = ('cas_nocap_biz', 'sum'),
        cas_nocapital_nonbusiness = ('cas_nocap_nobiz', 'sum'),
        inc_capital_business = ('inc_cap_biz', 'count'),
        inc_capital_nonbusiness = ('inc_cap_nobiz', 'count'),

        # Top-3 x target type aggregation
        cas_top3_business = ('cas_top3_biz', 'sum'),
        cas_top3_nonbusiness = ('cas_top3_nobiz', 'sum'),
        cas_notop3_business = ('cas_notop3_biz', 'sum'),
        cas_notop3_nonbusiness = ('cas_notop3_nobiz', 'sum'),
        inc_top3_business = ('inc_top3_biz', 'count'),
        inc_top3_nonbusiness = ('inc_top3_nobiz', 'count')

    ).reset_index()

    panel_df = panel_df.rename(columns = {"iyear": "year"})
    all_years = range(panel_df["year"].min(), panel_df["year"].max() + 1)
    all_countries = panel_df["country_txt"].unique()

    full_index = pd.MultiIndex.from_product(
        [all_countries, all_years],
        names = ["country_txt", "year"]
    )
    panel_df = panel_df.set_index(["country_txt", "year"]).reindex(full_index).reset_index()

    print("Starting country conversion...")
    panel_df["ISO3"] = cc.convert(names=panel_df["country_txt"], to="ISO3")
    # panel_df["nationality"] = cc.convert(names=panel_df["natlty1_txt"], to="ISO3")
    # print("First conversion complete, starting second conversion...")

    num_cols = panel_df.columns.difference(["country_txt", "ISO3", "year"])
    panel_df[num_cols] = panel_df[num_cols].fillna(0)

    panel_df["country_id"] = panel_df["country_txt"].astype("category").cat.codes
    panel_df["cntry_id"] = panel_df["ISO3"].astype('category').cat.codes
    panel_df.to_csv(GTD_OUTPUT_PATH, index = False, encoding = "utf-8")
    end_time = time.perf_counter()
    duration = end_time - start_time
    print(f"GTD cleaning takes {duration} seconds to run.")