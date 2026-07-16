import pandas as pd
from terror_and_fdi.config import RAW, INTERIM
import country_converter as coco

QUARTERLY_PATH = INTERIM / "quarterly"

cc = coco.CountryConverter()


def clean_imf_fdi(input_path, output_path):
    df = pd.read_csv(input_path)
    df = df.drop(columns = ["BOP_ACCOUNTING_ENTRY", "UNIT", "FREQUENCY", "SCALE", "INDICATOR"]).rename(
    columns = {"OBS_VALUE": "net_fdi_imf", "COUNTRY": "country", "TIME_PERIOD": "time_period"}
    )

    df.to_stata(output_path)


def clean_gtd_quarterly(input_path, output_path):
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
            "code": "imonth",
            "definition": "Month",
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

    df = pd.read_csv(input_path, usecols=COLS_GTD)
    print("Creating variables and aggreating the dataset.")
    df['nkill'] = df['nkill'].fillna(0)
    df['nwound'] = df['nwound'].fillna(0)
    df['casualties'] = df['nkill'] + df['nwound']
    df["is_business"] = df["targtype1"] == 1

    df_cities = pd.read_csv(INTERIM / "cities_processed.csv")
    df = pd.merge(df, df_cities, on="city", how="left")

    # --- CAPITAL VS. PERIPHERY ---
    df['cas_cap'] = df['casualties'].where(df['is_capital'] == True, 0)
    df['cas_nocap'] = df['casualties'].where(df['is_capital'] == False, 0)
    df['inc_cap'] = df['success'].where(df['is_capital'] == True, 0)  # Counting incidents
    df['fat_cap'] = df['nkill'].where(df['is_capital'] == True, 0)

    # --- TOP 3 VS. PERIPHERY ---
    df['cas_top3'] = df['casualties'].where(df['is_top3'] == True, 0)
    df['cas_notop3'] = df['casualties'].where(df['is_top3'] == False, 0)
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
    df = df[df["month"] != 0]
    df["quarter"] = (df["imonth"] -1) // 3 + 1

    quarter_df = df.groupby(['country_txt', 'iyear', 'quarter']).agg(
        # 1. Total per country-quarter
        incidents_total=('success', 'size'),
        fatalities_total=('nkill', 'sum'),
        wounded_total=('nwound', 'sum'),
        casualties_total=('casualties', 'sum'),

        # 2. Capital vs. rest
        casualties_capital=('cas_cap', 'sum'),
        casualties_no_capital=('cas_nocap', 'sum'),
        incidents_capital=('inc_cap', 'sum'),

        # 3. Top-3 vs. rest
        casualties_top3=('cas_top3', 'sum'),
        casualties_no_top3=('cas_notop3', 'sum'),
        incidents_top3=('inc_top3', 'sum'),

        # Capital x target type aggregation
        cas_capital_business=('cas_cap_biz', 'sum'),
        cas_capital_nonbusiness=('cas_cap_nobiz', 'sum'),
        cas_nocapital_business=('cas_nocap_biz', 'sum'),
        cas_nocapital_nonbusiness=('cas_nocap_nobiz', 'sum'),
        inc_capital_business=('inc_cap_biz', 'sum'),
        inc_capital_nonbusiness=('inc_cap_nobiz', 'sum'),

        # Top-3 x target type aggregation
        cas_top3_business=('cas_top3_biz', 'sum'),
        cas_top3_nonbusiness=('cas_top3_nobiz', 'sum'),
        cas_notop3_business=('cas_notop3_biz', 'sum'),
        cas_notop3_nonbusiness=('cas_notop3_nobiz', 'sum'),
        inc_top3_business=('inc_top3_biz', 'sum'),
        inc_top3_nonbusiness=('inc_top3_nobiz', 'sum')

    ).reset_index()

    quarter_df = quarter_df.rename(columns={"iyear": "year"})

    all_years = range(quarter_df["year"].min(), quarter_df["year"].max() + 1)
    all_countries = quarter_df["country_txt"].unique()

    full_index = pd.MultiIndex.from_product(
        [all_countries, all_years, range(1,5)],
        names=["country_txt", "year", "quarter"]
    )

    quarter_df = quarter_df.set_index(["country_txt", "year", "quarter"]).reindex(full_index).reset_index()

    print("Starting country conversion...")
    quarter_df["ISO3"] = cc.convert(names=quarter_df["country_txt"], to="ISO3")
    # panel_df["nationality"] = cc.convert(names=panel_df["natlty1_txt"], to="ISO3")
    # print("First conversion complete, starting second conversion...")

    num_cols = quarter_df.columns.difference(["country_txt", "ISO3", "quarter"])
    quarter_df[num_cols] = quarter_df[num_cols].fillna(0)

    quarter_df["country_id"] = quarter_df["country_txt"].astype("category").cat.codes
    quarter_df["cntry_id"] = quarter_df["ISO3"].astype('category').cat.codes
    quarter_df.to_stata(output_path)


clean_imf_fdi(RAW/ "imf"/ "net_fdi_quarterly_imf.csv", QUARTERLY_PATH / "fdi_imf_processed.dta")

clean_gtd_quarterly(RAW / "gtd" / "gtd.csv", QUARTERLY_PATH / "gtd_processed.dta")