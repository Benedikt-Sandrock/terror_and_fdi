"""
Loads and cleans all sources for the main analysis.
Always configure input and output path as well as needed variables.
"""

import pandas as pd
from terror_and_fdi.config import RAW, INTERIM

# ==============================================================
# CONFIGURATION
# ==============================================================
# Specify which sources need to be cleaned
CLEAN_V_DEM = False
CLEAN_PWT = False
CLEAN_GTD = False


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

TAX_INPUT = RAW / "tax_foundation" / "rates_final.csv"
TAX_OUTPUT = INTERIM / "stat_tax_rate_processed.csv"

tax_df = pd.read_csv(TAX_INPUT)

tax_df = tax_df.drop(columns = ["iso_2", "continent", "country"])
tax_df = pd.melt(
    tax_df, id_vars="iso_3", var_name = "year", value_name="stat_corp_tax_rate"
)
tax_df = tax_df.sort_values(by = "iso_3")
tax_df.to_csv(TAX_OUTPUT, index = False)
print(tax_df)