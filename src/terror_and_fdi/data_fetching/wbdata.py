from datetime import datetime
import pandas as pd
import requests
from terror_and_fdi.config import RAW

# ==========================================
# CONFIGURATION
# ==========================================

OUTPUT_FILE = RAW / "world_bank" / "wb_data.csv"

vars_wdi = {
    # --- GDP & Macroeconomics ---
    "gdp_per_capita_constant": "NY.GDP.PCAP.KD",  # GDP per capita (constant 2015 US$)
    "gdp_per_capita_current": "NY.GDP.PCAP.CD",  # GDP per capita (current US$)
    "gdp_deflator": "NY.GDP.DEFL.KD.ZG",  # Annual GDP deflator (inflation, GDP deflator annual %)
    "gfkf_percent": "NE.GDI.FTOT.ZS",  # Gross fixed capital formation (% of GDP)
    "natural_resources_rents": "NY.GDP.TOTL.RT.ZS",  # Total natural resources rents (% of GDP)
    # --- Trade & FDI ---
    "fdi_inflow_percent": "BX.KLT.DINV.WD.GD.ZS",  # Foreign direct investment, net inflows (% of GDP)
    "fdi_inflow_abs": "BX.KLT.DINV.CD.WD",  # Foreign direct investment, net inflows (BoP, current US$)
    "fdi_outflow_percent": "BM.KLT.DINV.WD.GD.ZS",  # Foreign direct investment, net outflows (% of GDP)
    "fdi_outflow_abs": "BM.KLT.DINV.CD.WD",  # Foreign direct investment, net outflows (BoP, current US$)
    "trade_share": "NE.TRD.GNFS.ZS",  # Trade (% of GDP) [Imports + Exports]
    # --- Taxes & Revenue ---
    "tax_as_perc_of_revenue": "GC.TAX.YPKG.ZS",  # Taxes on income, profits and capital gains (% of revenue)
    "tax_of_gdp": "GC.TAX.TOTL.GD.ZS",  # Tax revenue (% of GDP)
    # --- Infrastructure / Telecom ---
    "mobile_phone_subs": "IT.CEL.SETS.P2",  # Mobile cellular subscriptions (per 100 people)
    "telephone_subs": "IT.MLT.MAIN.P2",  # Fixed telephone subscriptions (per 100 people)
    # --- Education (UNESCO via World Bank) ---
    "prim_netenrol": "SE.PRM.NENR",  # Net enrolment rate, primary, both sexes (%)
    "lowsec_netenrol": "SE.SEC.UNER.LO.ZS",  # Net enrolment rate, lower secondary, both sexes (%)
    "upsec_netenrol": "SE.SEC.ENRL.TC.ZS",  # Net enrolment rate, upper secondary, both sexes (%)
    }

vars_wgi = {
    "cc": "GOV_WGI_CC.EST",  # Corruption Control
    "ge": "GOV_WGI_GE.EST",  # Government Effectiveness
    "pv": "GOV_WGI_PV.EST",  # Absence of Political Violence
    "rl": "GOV_WGI_RL.EST",  # Rule of Law
    "rq": "GOV_WGI_RQ.EST",  # Regulatory Quality
    "va": "GOV_WGI_VA.EST",  # Voice and Accountability
}

# ==========================================
# FUNCTION
# ==========================================

def fetch_bulk_world_bank_data(indicators_dict, source = 2):
    """
    Downloads a list of indicators for all countries and all years since 1960.
    Merges the data and formats in a wide DF with one observation per country-year.
    """
    current_year = datetime.now().year
    period = f"1960:{current_year}"

    all_dataframes = []

    for column_name, code in indicators_dict.items():
        print(
            f"Downloading '{column_name}' ({code}) for all countries..."
        )

        url = f"https://api.worldbank.org/v2/country/all/indicator/{code}"
        # per_page=30000 ensures that all countries and years (ca. 16.000 data points)
        # are fetched from one page without pagination.
        params = {"format": "json", "date": period, "per_page": 30000, "source": source}

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            res_json = response.json()

            # check whether data is available
            if len(res_json) < 2 or not res_json[1]:
                print(f"-> Warning: No data found for {column_name}.")
                continue

            # Extract data
            records = []
            for item in res_json[1]:
                # Statistical aggregates (e.g., "world") are not filtered out.
                records.append(
                    {
                        "country_code": item["country"]["id"],
                        "country": item["country"]["value"],
                        "year": int(item["date"]),
                        column_name: item[
                            "value"
                        ],  # dynamic column name (e.g. "gdp_per_capita")
                    }
                )

            df_indicator = pd.DataFrame(records)
            all_dataframes.append(df_indicator)

        except Exception as e:
            print(f"-> Error when loading {column_name}: {e}")

    if not all_dataframes:
        print("No data found at all.")
        return None

    # --- Merging data ---
    final_df = all_dataframes[0]

    for next_df in all_dataframes[1:]:
        final_df = pd.merge(
            final_df, next_df, on=["country_code", "country", "year"], how="outer"
        )
    final_df = final_df.sort_values(by=["country", "year"]).reset_index(drop=True)

    return final_df


# ==========================================
# MAIN
# ==========================================

if __name__ == "__main__":
    df_wdi = fetch_bulk_world_bank_data(vars_wdi)
    df_wgi = fetch_bulk_world_bank_data(vars_wgi, source = 3)


    df_final = pd.merge(df_wdi, df_wgi, on = ["country_code", "country", "year"], how = "outer")
    df_final = df_final.sort_values(by=["country", "year"]).reset_index(drop = True)

    print("\n--- Done! ---")
    print(f"Structure of the final dataset: {df_final.shape} (rows, columns)")

    df_final.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"\nFile saves as '{OUTPUT_FILE}'")

