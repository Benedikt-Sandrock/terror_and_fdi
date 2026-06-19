import pandas as pd
import matplotlib.pyplot as plt
import os

output_folder = r"C:\Users\bene-\OneDrive\Uni\Replication plus\replication_files\success rates"
# Example: unique countries
df = pd.read_stata("gtd_capital.dta")
countries = df['economy_label'].unique()

for c in countries:
    # Filter for country
    df_c = df[df['economy_label'] == c].sort_values('year')

    fig, ax1 = plt.subplots(figsize=(10, 6))

    # Plot success rates (solid lines)
    for capital_status, color, label in [(1, 'red', 'Capital Success Rate'), (0, 'blue', 'Non-Capital Success Rate')]:
        subset = df_c[df_c['is_capital'] == capital_status]
        ax1.plot(subset['year'], subset['success_rate'], color=color, linestyle='-', label=label)

    #ax1.set_ylim(bottom = 0, top=1.1)
    ax1.set_xlabel('Year')
    ax1.set_ylabel('Success Rate')

    # Secondary y-axis for number_of_attacks
    ax2 = ax1.twinx()

    # Plot number_of_attacks (x markers), same colors as success rates
    for capital_status, color, label in [(1, 'red', 'Capital # Attacks'), (0, 'blue', 'Non-Capital # Attacks')]:
        subset = df_c[df_c['is_capital'] == capital_status]
        ax2.scatter(subset['year'], subset['number_of_attacks'], color=color, marker='x', label=label)


    ymin, ymax = ax2.get_ylim()
    ax2.set_ylim(bottom=0, top=ymax)
    ax2.set_ylabel('Number of Attacks')

    ax1.spines['top'].set_visible(False)
    ax2.spines['top'].set_visible(False)
    # Combine legends from both axes
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper center',
           bbox_to_anchor=(0.5, -0.15),
           ncol=2,  # number of columns
           frameon=False)

    plt.xticks(df_c['year'].unique())
    ax1.set_title(c)
    plt.tight_layout()
    save_path = os.path.join(output_folder, f"Graph_{c}.png")
    plt.savefig(save_path)
    plt.close()
