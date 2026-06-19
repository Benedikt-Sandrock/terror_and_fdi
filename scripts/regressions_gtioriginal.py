import pandas as pd
import statsmodels.api as sm
import matplotlib.pyplot as plt
from linearmodels.panel import PanelOLS

df = pd.read_csv("data_final.csv")

# natural resource share is dropped to get observations beyond 2021
controls = ["ln_gdp_per_capita", "trade_share", "mobile_subs_per_100", "taxes_percent_of_revenue", "exrate_volatility",
            "gdp_deflator", "avg_years_schooling", "forecast_gdpgrowth", "libdem", "internal_conflict", "cc", "ge"]

### Simple Regression - Cross-country
results_simple_cross = []
df_simple_cross = df.dropna(subset=["net_fdistock", "gti_score"])

for year, group in df_simple_cross.groupby("year"):
    group = group[group["fdi_restrictions"] == 0]
    if len(group) < 3:
        continue

    y = group["net_fdistock"]
    X = sm.add_constant(group["gti_score"])
    model = sm.OLS(y,X).fit()

    coef = model.params["gti_score"]
    ci_low, ci_high = model.conf_int().loc["gti_score"]

    results_simple_cross.append({
        "year": year,
        "coef": coef,
        "ci_low": ci_low,
        "ci_high": ci_high
    })

results_simple_cross_df = pd.DataFrame(results_simple_cross)
print(results_simple_cross_df)

##create plot
plt.figure(figsize = (10,6))
plt.errorbar(results_simple_cross_df["year"], results_simple_cross_df["coef"],
             yerr = [results_simple_cross_df["coef"] - results_simple_cross_df["ci_low"], results_simple_cross_df["ci_high"] - results_simple_cross_df["coef"]],
             fmt="o", capsize = 4, color = "blue")

plt.axhline(0, color = "gray", linestyle ="--")
plt.title("Yearly Regression Coefficients - Simple Regression - Restricted Sample")
plt.xlabel("Year")
plt.ylabel("Coefficient with 95 % CI")
#plt.grid(True)
years_int = results_simple_cross_df["year"].astype(int).tolist()
plt.xticks(years_int, labels=years_int)

plt.tight_layout()
#plt.savefig("Simple Regressions - Cross-country - Restricted Sample.png", dpi=300, bbox_inches='tight')
plt.show()


### Multiple Regression - Cross-country
results_multiple_cross = []
df_region = df.dropna(subset =["WBregion"])
region_dummies = pd.get_dummies(df_region["WBregion"], drop_first=True, dtype = float)
df_multiple_cross = pd.concat([df_region, region_dummies], axis = 1)
region_dummy_names = region_dummies.columns.tolist()

df_multiple_cross = df_multiple_cross.dropna(subset=["net_fdistock", "gti_score"] + controls + region_dummy_names)

for year, group in df_multiple_cross.groupby("year"):
    group = group[group["fdi_restrictions"] == 0] # filter out all the contries imposing restrictions on fdi

    if len(group) < 3:
        continue

    y = group["net_fdistock"]
    X = sm.add_constant(group[["gti_score"]+ controls + region_dummy_names])
    model = sm.OLS(y,X).fit()

    coef = model.params["gti_score"]
    ci_low, ci_high = model.conf_int().loc["gti_score"]

    results_multiple_cross.append({
        "year": year,
        "coef": coef,
        "ci_low": ci_low,
        "ci_high": ci_high
    })

results_multiple_cross_df = pd.DataFrame(results_multiple_cross)
print(results_multiple_cross_df)

plt.figure(figsize = (10,6))
plt.errorbar(results_multiple_cross_df["year"], results_multiple_cross_df["coef"],
             yerr = [results_multiple_cross_df["coef"] - results_multiple_cross_df["ci_low"],
                     results_multiple_cross_df["ci_high"] - results_multiple_cross_df["coef"]],
             fmt="o", capsize = 4, color = "blue")

plt.axhline(0, color = "gray", linestyle ="--")
plt.title("Yearly Regression Coefficients - Multiple Regression - Restricted Sample")
plt.xlabel("Year")
plt.ylabel("Coefficient with 95 % CI")
#plt.grid(True)
years_int = results_multiple_cross_df["year"].astype(int).tolist()
plt.xticks(years_int, labels=years_int)

plt.tight_layout()
# plt.savefig("Multiple Regressions - Cross-country.png", dpi=300, bbox_inches='tight')
#plt.savefig("Multiple Regressions - Cross-country - Restricted sample.png", dpi=300, bbox_inches='tight')
plt.show()


# ### Panel regressions
#
# df = df.set_index(["ISO3", "year"])
# panel_df = df[df["fdi_restrictions"] == 0]
#
# # controls = ["ln_gdp_per_capita", "trade_share", "mobile_subs_per_100", "taxes_percent_of_revenue", "exrate_volatility",
# #             "gdp_deflator", "avg_years_schooling", "forecast_gdpgrowth", "libdem", "internal_conflict", "cc", "ge",
# #             "natural_resource_share"]
#
#
# y = panel_df["net_fdistock"]
# X = panel_df[["gti_scaled"] + controls]
# X = sm.add_constant(X)
#
# model = PanelOLS(y,X, entity_effects=True, time_effects=True)
# results = model.fit(cov_type="clustered", cluster_entity = True)
#
# print(results.summary)
#
# # with open("panel_regression_output.tex", "w") as f:
# #     f.write(results.summary.as_latex())
