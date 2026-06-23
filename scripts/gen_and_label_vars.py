"""Takes varlist from stata as input and generates stata code to generate logged variables and label variables"""

var_list = "incidents_total fatalities_total wounded_total casualties_total casualties_capital casualties_no_capital incidents_capital casualties_top3 casualties_no_top3 incidents_top3 cas_capital_business cas_capital_nonbusiness cas_nocapital_business cas_nocapital_nonbusiness inc_capital_business inc_capital_nonbusiness cas_top3_business cas_top3_nonbusiness cas_notop3_business cas_notop3_nonbusiness inc_top3_business inc_top3_nonbusiness"
var_list = var_list.split()

ln_vars = "ln_incidents_total ln_fatalities_total ln_wounded_total ln_casualties_total ln_casualties_capital ln_casualties_no_capital ln_incidents_capital ln_casualties_top3 ln_casualties_no_top3 ln_incidents_top3 ln_cas_capital_business ln_cas_capital_nonbusiness ln_cas_nocapital_business ln_cas_nocapital_nonbusiness ln_inc_capital_business ln_inc_capital_nonbusiness ln_cas_top3_business ln_cas_top3_nonbusiness ln_cas_notop3_business ln_cas_notop3_nonbusiness ln_inc_top3_business ln_inc_top3_nonbusiness"
ln_vars = ln_vars.split()

pc_vars = "incidents_total_pc fatalities_total_pc wounded_total_pc casualties_total_pc casualties_capital_pc casualties_no_capital_pc incidents_capital_pc casualties_top3_pc casualties_no_top3_pc incidents_top3_pc cas_capital_business_pc cas_capital_nonbusiness_pc cas_nocapital_business_pc cas_nocapital_nonbusiness_pc inc_capital_business_pc inc_capital_nonbusiness_pc cas_top3_business_pc cas_top3_nonbusiness_pc cas_notop3_business_pc cas_notop3_nonbusiness_pc inc_top3_business_pc inc_top3_nonbusiness_pc"
pc_vars = pc_vars.split()

with open("gen_vars.txt", "w") as f:
    # gen ln vars
    for var in var_list:
        f.write(f"gen ln_{var} = ln({var} +1)\n")

    # label vars
    for ln_var, var in zip(ln_vars, var_list):
        f.write(f'label var {ln_var} "ln({var})"\n')

    # gen terror per capita
    for var in var_list:
        f.write(f"gen {var}_pc = {var} / population_total\n")

    for pc_var, var in zip(pc_vars, var_list):
        f.write(f'label var {pc_var} "{var} per capita"\n')



