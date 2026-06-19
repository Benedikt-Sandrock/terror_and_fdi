from itertools import combinations

# List of governance indicators
indicators = [
    "rq",
    "rl",
    "ge",
    "cc",
    "va"
]

# Generate all non-empty combinations (1 to 5 elements)
combo_list = []
for i in range(1, len(indicators) + 1):
    for combo in combinations(indicators, i):
        combo_list.append(" ".join(combo))

# Print for Stata local macro (ready to paste)
print("local combos \"")
for c in combo_list:
    print(f"{c}")
print("\"")