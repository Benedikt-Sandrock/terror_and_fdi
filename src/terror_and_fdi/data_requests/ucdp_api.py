import requests
import pandas as pd

# API-Endpoint für das ucdpprioconflict Dataset (Beispiel Version 26.1)
url = "https://ucdpapi.pcr.uu.se/api/ucdpprioconflict/26.1"
headers = {
    "Authorization": "Bearer DEIN_API_TOKEN"  # Ersetze DEIN_API_TOKEN mit deinem echten Token
}

params = {
    "pagesize": 1000,
    "page": 1
}

all_data = []

while True:
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"Fehler beim Abruf: {response.status_code}")
        break

    data = response.json()
    # Ergänze die Liste mit den Zeilen der aktuellen Seite
    all_data.extend(data.get("results", []))

    # Prüfen, ob es eine weitere Seite gibt
    if "next" in data and data["next"]:
        params["page"] += 1
    else:
        break

# Als CSV speichern für Stata
df = pd.DataFrame(all_data)
df.to_csv("ucdp_prio_conflict_raw.csv", index=False)
print("Download erfolgreich abgeschlossen!")