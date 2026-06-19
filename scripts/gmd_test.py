from global_macro_data import gmd

df_gmd = gmd(variables=["inv_GDP", "strate", "ltrate", "unemp"])
df_gmd = df_gmd[df_gmd["year"] > 1999]
print(df_gmd.head())
df_gmd = df_gmd.drop("countryname", axis = 1)
print(df_gmd.head())
