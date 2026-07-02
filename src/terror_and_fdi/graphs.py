import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from terror_and_fdi.config import PROCESSED, INTERIM
import country_converter as coco
import numpy as np

manual_iso3 = {
    "Aruba, Kingdom of the Netherlands": "ABW",
    "Sint Maarten, Kingdom of the Netherlands": "SXM",
    "Netherlands Antilles": "ANT",  # historisch; ggf. nicht in class_df vorhanden
    "Euro Area (EA)": np.nan,       # kein Land
    "São Tomé and Príncipe, Democratic Republic of": "STP",
    "SÃ£o TomÃ© and PrÃ­ncipe, Democratic Republic of": "STP",
    "Türkiye, Republic of": "TUR",
    "TÃ¼rkiye, Republic of": "TUR",
}


cc = coco.CountryConverter()

df = pd.read_csv(INTERIM / "fdi_imf_processed.csv")


START_PERIODS = [
    "1993-Q1",
    "2000-Q1",
    "2003-Q1",
    "2005-Q1",
    "2010-Q1",
    "2015-Q1",
    "2016-Q1",
]
START_PERIOD = "2010-Q1"
END_PERIOD = "2020-Q4"

def countries_with_continuous_data_between(df: pd.DataFrame, start_period: str, end_period: str,
    value_col: str = "net_fdi_imf", country_col: str = "country", time_col: str = "time_period",
    output_path=None,):
    data = df.copy()

    data[time_col] = pd.PeriodIndex(data[time_col], freq="Q")
    start_period = pd.Period(start_period, freq="Q")
    end_period = pd.Period(end_period, freq="Q")

    required_periods = pd.period_range(start=start_period, end=end_period, freq="Q")

    data = data[data[time_col].between(start_period, end_period)]

    availability = (
        data.assign(available=data[value_col].notna())
        .pivot_table(
            index=country_col,
            columns=time_col,
            values="available",
            aggfunc="max",
            fill_value=False
        )
        .reindex(columns=required_periods, fill_value=False)
    )

    continuous_mask = availability.all(axis=1)
    countries = availability.index[continuous_mask].tolist()

    result_df = pd.DataFrame({
        country_col: countries,
        "start_period": str(start_period),
        "end_period": str(end_period),
        "n_required_quarters": len(required_periods),
    })

    if output_path is not None:
        output_path = str(output_path)

        if output_path.endswith(".xlsx"):
            result_df.to_excel(output_path, index=False)
        else:
            result_df.to_csv(output_path, index=False)

    return {
        "n_countries": len(countries),
        "countries": countries,
        "start_period": str(start_period),
        "end_period": str(end_period),
        "n_required_quarters": len(required_periods),
        "result_df": result_df,
    }


def country_continuous_availability_by_start_period(df: pd.DataFrame, start_periods: list[str], end_period: str,
    value_col: str = "net_fdi_imf", country_col: str = "country", time_col: str = "time_period",
    output_path=None,) -> pd.DataFrame:
    """
    Erstellt eine Tabelle mit Ländern als Zeilen und Startperioden als Spalten.
    Für jede Startperiode steht True/False darin, ob das Land von dieser
    Startperiode bis end_period durchgängige Daten in value_col hat.

    Beispiel:
        country | continuous_from_2008_Q1 | continuous_from_2010_Q1 | ...
        Germany | True                    | True                    |
        France  | False                   | True                    |

    Parameters
    ----------
    df : pd.DataFrame
        Input-Datensatz.
    start_periods : list[str]
        Liste von Startquartalen, z. B. ["2008-Q1", "2010-Q1", "2012-Q1"].
    end_period : str
        Fixes Endquartal, z. B. "2020-Q4".
    value_col : str
        Spalte, deren Verfügbarkeit geprüft wird.
    country_col : str
        Länder-Spalte.
    time_col : str
        Zeit-Spalte.
    output_path : str or pathlib.Path, optional
        Speicherpfad für CSV/XLSX.

    Returns
    -------
    pd.DataFrame
        Tabelle mit einem Land pro Zeile und einer Spalte pro Startperiode.
    """

    data = df.copy()

    data[time_col] = pd.PeriodIndex(data[time_col], freq="Q")
    start_periods_period = [pd.Period(p, freq="Q") for p in start_periods]
    end_period_period = pd.Period(end_period, freq="Q")

    min_start_period = min(start_periods_period)

    all_required_periods = pd.period_range(
        start=min_start_period,
        end=end_period_period,
        freq="Q"
    )

    # Availability-Matrix: Land x Quartal
    availability = (
        data[data[time_col].between(min_start_period, end_period_period)]
        .assign(available=data[value_col].notna())
        .pivot_table(
            index=country_col,
            columns=time_col,
            values="available",
            aggfunc="max",
            fill_value=False
        )
        .reindex(columns=all_required_periods, fill_value=False)
        .astype(bool)
    )

    result_df = pd.DataFrame(index=availability.index)

    for start_period in start_periods_period:
        required_periods = pd.period_range(
            start=start_period,
            end=end_period_period,
            freq="Q"
        )

        col_name = f"from_{str(start_period).replace('-', '_')}"
        result_df[col_name] = availability[required_periods].all(axis=1)

    result_df = result_df.reset_index()

    # Optional: zusätzliche Summary-Zeile nicht einfügen, sondern separat printen
    if output_path is not None:
        output_path = str(output_path)

        if output_path.endswith(".xlsx"):
            result_df.to_excel(output_path, index=False)
        else:
            result_df.to_csv(output_path, index=False)

    return result_df


def safe_country_to_iso3(country):
    if pd.isna(country):
        return np.nan

    if country in manual_iso3:
        return manual_iso3[country]

    iso = cc.convert(
        names=country,
        to="ISO3",
        not_found=None
    )

    # country_converter kann bei Mehrfachtreffern eine Liste zurückgeben
    if isinstance(iso, list):
        if len(iso) == 1:
            return iso[0]
        return np.nan

    # Falls nichts gefunden wurde
    if iso is None or iso == "not found":
        return np.nan

    return iso



plot_df = df.copy()

# time_period wie "2008-Q2" in Quartalsperioden umwandeln
plot_df["time_period"] = pd.PeriodIndex(plot_df["time_period"], freq="Q")

# Verfügbarkeit markieren
plot_df["available"] = plot_df["net_fdi_imf"].notna().astype(int)

# Matrix: Länder x Quartale
availability = (
    plot_df
    .pivot_table(
        index="country",
        columns="time_period",
        values="available",
        aggfunc="max",
        fill_value=0
    )
)

# Früheste Verfügbarkeit pro Land bestimmen
first_available = (
    plot_df[plot_df["net_fdi_imf"].notna()]
    .groupby("country")["time_period"]
    .min()
)

# Länder aufsteigend nach frühester Verfügbarkeit sortieren
# Bedeutet: Länder, deren Daten am frühesten beginnen, stehen oben
country_order = first_available.sort_values(ascending=True).index

# Optional: Länder ohne verfügbare Werte ans Ende hängen
countries_without_data = availability.index.difference(country_order)
country_order = list(country_order) + list(countries_without_data)

availability = availability.loc[country_order]

# Spalten chronologisch sortieren und als Strings anzeigen
availability = availability.sort_index(axis=1)
availability.columns = availability.columns.astype(str)

fig, ax = plt.subplots(figsize=(16, max(6, len(availability) * 0.25)))

sns.heatmap(
    availability,
    cmap=["#f0f0f0", "#1f77b4"],
    cbar=False,
    linewidths=0.2,
    linecolor="white",
    ax=ax
)

ax.set_xlabel("Time period")
ax.set_ylabel("Country")
ax.set_title("Availability of net FDI inflow data by country and time period", pad=20)

step = max(1, len(availability.columns) // 20)
tick_positions = range(0, len(availability.columns), step)
tick_labels = availability.columns[::step]

# Untere x-Achse
ax.set_xticks(tick_positions)
ax.set_xticklabels(tick_labels, rotation=45, ha="right")

# Obere x-Achse zusätzlich
ax_top = ax.secondary_xaxis("top")
ax_top.set_xticks(tick_positions)
ax_top.set_xticklabels(tick_labels, rotation=45, ha="left")
ax_top.set_xlabel("Time period")

plt.tight_layout()
plt.savefig(PROCESSED / "fdi_quarterly.pdf", dpi=600)
#plt.show()


# result = countries_with_continuous_data_between(
#     df=df,
#     start_period=START_PERIOD,
#     end_period=END_PERIOD,
#     output_path=PROCESSED / f"countries_continuous_fdi_{START_PERIOD}_to_{END_PERIOD}.csv"
# )
# print(f"{result['n_countries']} Länder haben durchgängige Daten.")
# print(result["countries"])


continuous_by_country = country_continuous_availability_by_start_period(
    df=df,
    start_periods=START_PERIODS,
    end_period=END_PERIOD,
    output_path=PROCESSED / f"countries_continuous_fdi_by_start_to_{END_PERIOD}.csv"
)

print(continuous_by_country.head())

summary = (
    continuous_by_country
    .drop(columns="country")
    .sum()
    .reset_index()
)

summary.columns = ["start_period", "n_countries"]

print(summary)

class_df = pd.read_csv(INTERIM / "country_metadata_processed.csv")

df_continuous = pd.read_csv(
    PROCESSED / f"countries_continuous_fdi_by_start_to_{END_PERIOD}.csv"
)

df_continuous["ISO3"] = df_continuous["country"].apply(safe_country_to_iso3)

# Optional: prüfen, welche Länder nicht gematcht wurden
unmatched = df_continuous[df_continuous["ISO3"].isna()]["country"].tolist()
print("Unmatched countries:")
print(unmatched)

# Sicherstellen, dass ISO3 in beiden DataFrames Strings sind
df_continuous["ISO3"] = df_continuous["ISO3"].astype("string")
class_df["ISO3"] = class_df["ISO3"].astype("string")

df_continuous = pd.merge(
    df_continuous,
    class_df,
    on="ISO3",
    how="left"
)
income_col = "income_group"  # ggf. anpassen, z. B. "income_group"

period_cols = [
    col for col in df_continuous.columns
    if col.startswith("from_")
]

summary = []

for period_col in period_cols:
    available_total = df_continuous[period_col].sum()

    available_without_high_income = df_continuous.loc[
        df_continuous[income_col] != "High income",
        period_col
    ].sum()

    summary.append({
        "start_period": period_col,
        "n_countries_total": int(available_total),
        "n_countries_excluding_high_income": int(available_without_high_income),
    })

summary_df = pd.DataFrame(summary)

summary_df.to_csv(
    PROCESSED / f"summary_continuous_fdi_by_start_to_{END_PERIOD}.csv",
    index=False
)

print(summary_df)
df_continuous.to_csv(
    PROCESSED / f"countries_continuous_fdi_by_start_to_{END_PERIOD}_with_metadata.csv",
    index=False
)


