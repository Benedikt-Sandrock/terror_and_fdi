import pandas as pd
#import country_converter as coco

gtd = pd.read_excel("gtd.xlsx",
                    engine = "openpyxl", usecols=["iyear", "doubtterr","country_txt", "city",
                                                #"attacktype1", "attacktype2","attacktype3",
                                                "targtype1", "success", #"weaptype1", "weaptype2", "weaptype3",
                                                "nkill", "nkillter", "nwound", "nwoundte",
                                                "propextent", "nhostkid"])
gtd =gtd.rename(columns={"iyear": "year", "country_txt": "economy_label"})
print(f"hostages:{gtd["nhostkid"].value_counts()}")
#gtd["nhostkid"] = gtd["nhostkid"].replace(-99, 0)
print(f"doubt:{gtd["doubtterr"].value_counts(dropna=False)}")
#gtd = gtd[gtd["doubtterr"] == 0]
print(f"years:{gtd["year"].unique()}")
#gtd = gtd[gtd["year"] > 1999]

gtd.to_csv("gtd_cities2.csv", index = False)