import pandas as pd

ucdpprio = pd.read_csv("ucdprio.csv")
print(ucdpprio.head())
print(ucdpprio.columns)

ucdpprio = ucdpprio[ucdpprio["type_of_conflict"].isin([3])]

ucdpprio = ucdpprio[["location", "year", "type_of_conflict"]]
ucdpprio["type_of_conflict"] = 1
ucdpprio.columns = ["economy_label", "year", "internal_conflict"]
print(ucdpprio.head())

#occurs = ucdpprio[ucdpprio["location"].str.contains("Sudan", na=False)]
#print(occurs[["conflict_id", "location", "year"]])

ucdpprio.to_csv('ucdpprio.csv', index=False)

