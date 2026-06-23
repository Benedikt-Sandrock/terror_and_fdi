*===============================================================================
* PROJECT:   Terrorism and FDI - Panel VAR Analysis (100+ countries, 1970-2020)
* APPROACH:  GMM-based PVAR (Abrigo & Love 2016), following the structure of
*            Aslan et al. (2022), Zhang et al. (2023), Caraiani et al. (2023),
*            and Rünstler (2024)
* REQUIRES:  ssc install pvar       (Abrigo & Love PVAR suite)
*            ssc install xtunitroot (if not built in to your Stata version)
*            ssc install xtwest     (Westerlund panel cointegration)
*            ssc install xtcd2 / pescadf  (optional cross-sectional dependence)
*===============================================================================

clear all
set more off
*version 17
cap log close
log using "terrorism_fdi_pvar_log.smcl", replace

*-------------------------------------------------------------------------------
* 0. PACKAGE INSTALLATION (run once)
*-------------------------------------------------------------------------------
/*
cap ssc install pvar
cap ssc install xtwest
cap ssc install moremata
cap ssc install xtcd2
*/

*===============================================================================
* 1. DATA IMPORT AND PANEL STRUCTURE
*===============================================================================

use "final_data_terror_and_fdi.dta", clear

* --- Country/year identifiers ---
* Use a fixed numeric country code (NOT the raw GTD/WB string code, which is
* recycled across historical entities). Where a country changed identity
* (USSR -> RU + 14 states; Yugoslavia -> 6+ states; German reunification),
* decide explicitly and document the rule, e.g.:
*   - treat USSR (1970-1991) and Russia (1992-2020) as ONE panel unit "Russia"
*     for continuity, but flag a structural-break dummy at 1991/1992
*   - treat newly independent post-1991/1992 states as separate units starting
*     only at independence (do NOT backfill pre-independence years)
* This must be coded explicitly in the country-code crosswalk, e.g.:
*   gen cowcode = ...   // Correlates of War code is more stable than ISO3 for this

encode ISO3, gen(ccode)
xtset ccode year

* --- Diagnose panel structure ---
xtdescribe
tab year, missing
* Check entry/exit countries to confirm unbalanced panel handling
bysort ccode (year): gen first_obs = (_n==1)
bysort ccode (year): gen last_obs  = (_n==_N)
tab year if first_obs
tab year if last_obs


*===============================================================================
* 2. VARIABLE CONSTRUCTION
*===============================================================================

* --- 2.1 Terrorism intensity (GTD) ---
* Raw counts are zero-inflated. Use a log(1+x) transform rather than raw counts.
* Gen and label vars

gen ln_incidents_total = ln(incidents_total +1)
gen ln_fatalities_total = ln(fatalities_total +1)
gen ln_wounded_total = ln(wounded_total +1)
gen ln_casualties_total = ln(casualties_total +1)
gen ln_casualties_capital = ln(casualties_capital +1)
gen ln_casualties_no_capital = ln(casualties_no_capital +1)
gen ln_incidents_capital = ln(incidents_capital +1)
gen ln_casualties_top3 = ln(casualties_top3 +1)
gen ln_casualties_no_top3 = ln(casualties_no_top3 +1)
gen ln_incidents_top3 = ln(incidents_top3 +1)
gen ln_cas_capital_business = ln(cas_capital_business +1)
gen ln_cas_capital_nonbusiness = ln(cas_capital_nonbusiness +1)
gen ln_cas_nocapital_business = ln(cas_nocapital_business +1)
gen ln_cas_nocapital_nonbusiness = ln(cas_nocapital_nonbusiness +1)
gen ln_inc_capital_business = ln(inc_capital_business +1)
gen ln_inc_capital_nonbusiness = ln(inc_capital_nonbusiness +1)
gen ln_cas_top3_business = ln(cas_top3_business +1)
gen ln_cas_top3_nonbusiness = ln(cas_top3_nonbusiness +1)
gen ln_cas_notop3_business = ln(cas_notop3_business +1)
gen ln_cas_notop3_nonbusiness = ln(cas_notop3_nonbusiness +1)
gen ln_inc_top3_business = ln(inc_top3_business +1)
gen ln_inc_top3_nonbusiness = ln(inc_top3_nonbusiness +1)

label var ln_incidents_total "ln(incidents_total)"
label var ln_fatalities_total "ln(fatalities_total)"
label var ln_wounded_total "ln(wounded_total)"
label var ln_casualties_total "ln(casualties_total)"
label var ln_casualties_capital "ln(casualties_capital)"
label var ln_casualties_no_capital "ln(casualties_no_capital)"
label var ln_incidents_capital "ln(incidents_capital)"
label var ln_casualties_top3 "ln(casualties_top3)"
label var ln_casualties_no_top3 "ln(casualties_no_top3)"
label var ln_incidents_top3 "ln(incidents_top3)"
label var ln_cas_capital_business "ln(cas_capital_business)"
label var ln_cas_capital_nonbusiness "ln(cas_capital_nonbusiness)"
label var ln_cas_nocapital_business "ln(cas_nocapital_business)"
label var ln_cas_nocapital_nonbusiness "ln(cas_nocapital_nonbusiness)"
label var ln_inc_capital_business "ln(inc_capital_business)"
label var ln_inc_capital_nonbusiness "ln(inc_capital_nonbusiness)"
label var ln_cas_top3_business "ln(cas_top3_business)"
label var ln_cas_top3_nonbusiness "ln(cas_top3_nonbusiness)"
label var ln_cas_notop3_business "ln(cas_notop3_business)"
label var ln_cas_notop3_nonbusiness "ln(cas_notop3_nonbusiness)"
label var ln_inc_top3_business "ln(inc_top3_business)"
label var ln_inc_top3_nonbusiness "ln(inc_top3_nonbusiness)"



* --- 2.2 FDI ---
* FDI net inflows, % of GDP (WDI). Highly skewed incl. negative values
* (divestment).
* Sign-preserving log transform (used widely for FDI/financial flows)
gen ihs_fdi_inflow_percent = ln(fdi_inflow_percent + sqrt(fdi_inflow_percent^2 + 1))   // inverse hyperbolic sine


* --- 2.3 Controls ---
gen gdp_growth   = gdp_growth_pct
gen trade_open   = (exports_pctgdp + imports_pctgdp)
gen lninflation  = ln(1 + abs(inflation_pct)) * sign(inflation_pct)
gen polity       = polity2                       // Polity5 institutional score
gen lnpop        = ln(population)

* Country grouping variables for heterogeneity analysis (Section 6)
gen incomegrp    = wb_income_group               // WB classification
gen region       = wb_region
egen polity_med  = median(polity)
gen highinstit   = (polity > polity_med)
egen terror_p50  = pctile(terror_index), p(50)
gen highterror   = (terror_index > terror_p50)


*===============================================================================
* 3. DESCRIPTIVE STATISTICS
*===============================================================================

xtsum terror_index terror_attacks_ln fdi_ihs gdp_growth trade_open lninflation polity
sum terror_index terror_attacks_ln fdi_ihs gdp_growth trade_open lninflation polity, detail

* Share of zero-attack country-years (document the excess-zero problem)
count if n_attacks == 0
display "Share of zero-attack country-years: " r(N)/_N

correlate terror_index fdi_ihs gdp_growth trade_open lninflation polity


*===============================================================================
* 4. PANEL UNIT ROOT TESTS
*===============================================================================
* Following Zhang et al. (2023): LLC, IPS, Fisher-type ADF on levels and
* first differences. With T~50 these tests have reasonable power.

foreach v in terror_index fdi_ihs gdp_growth trade_open lninflation polity {
    display "=== Unit root tests for `v' (levels) ==="
    xtunitroot llc `v'
    xtunitroot ips `v'
    xtunitroot fisher `v', dfuller lags(2)
}

* First differences (in case levels are non-stationary)
foreach v in terror_index fdi_ihs gdp_growth trade_open lninflation polity {
    bysort ccode (year): gen d_`v' = `v' - `v'[_n-1] if ccode == ccode[_n-1]
}

foreach v in d_terror_index d_fdi_ihs d_gdp_growth d_trade_open d_lninflation d_polity {
    display "=== Unit root tests for `v' (first difference) ==="
    xtunitroot ips `v'
}


*===============================================================================
* 5. PANEL COINTEGRATION TESTS  (only if levels are I(1))
*===============================================================================
* Westerlund (2007) - requires xtwest; Pedroni/Kao via xtcointtest in recent
* Stata versions (xtcointtest provides Pedroni, Kao, Westerlund directly).

xtcointtest pedroni fdi_ihs terror_index gdp_growth trade_open lninflation polity, ardl
xtcointtest kao     fdi_ihs terror_index gdp_growth trade_open lninflation polity
xtwest      fdi_ihs terror_index gdp_growth trade_open lninflation polity, lags(2) leads(2) constant


*===============================================================================
* 6. LAG ORDER SELECTION
*===============================================================================
* Andrews-Lu (2001) MBIC/MAIC/MQIC, as in Aslan et al. (2022).
* pvarsoc is part of the Abrigo & Love pvar suite.

pvarsoc terror_index fdi_ihs gdp_growth trade_open lninflation polity, ///
    pvaropts(instlags(1/4) gmmstyle) maxlag(4)


*===============================================================================
* 7. BASELINE PVAR ESTIMATION (GMM, pooled)
*===============================================================================
* Forward Orthogonal Deviations (Helmert transform) to preserve degrees of
* freedom in the unbalanced panel - this is the key advantage of Abrigo &
* Love's implementation over naive within-transformation.

pvar terror_index fdi_ihs gdp_growth trade_open lninflation polity, ///
    lags(2) instlags(1/4) fod gmmstyle overid

* Inspect coefficients / overidentification test
estimates store pvar_baseline
ereturn list


*===============================================================================
* 8. STABILITY CHECK
*===============================================================================
pvarstable, graph
* All eigenvalues of the companion matrix must lie inside the unit circle


*===============================================================================
* 9. GRANGER CAUSALITY (PANEL WALD TESTS)
*===============================================================================
pvargranger


*===============================================================================
* 10. IMPULSE RESPONSE FUNCTIONS AND VARIANCE DECOMPOSITION
*===============================================================================
* CRITICAL DECISION: Cholesky ordering.
* Terrorism is plausibly endogenous to economic conditions (reverse causality:
* weak institutions/growth -> terrorism risk, AND attractive FDI targets ->
* attack targets). Baseline ordering assumption: terrorism shocks affect FDI
* contemporaneously, but FDI/macro shocks affect terrorism only with a lag.
* => order terror_index FIRST.
* This assumption MUST be stress-tested (see Section 12.2).

pvarirf, mc(200) level(95) ///
    impulse(terror_index) response(fdi_ihs) ///
    figopts(title("IRF: Terrorism shock {&rarr} FDI") xtitle("Years") ytitle(""))

pvarirf, mc(200) level(95) oirf table

pvarfevd, ///
    impulse(terror_index) response(fdi_ihs) ///
    figopts(title("FEVD: Share of FDI variance from terrorism shocks"))


*===============================================================================
* 11. HETEROGENEITY / SUBGROUP ANALYSIS
*===============================================================================
* Pooling 100+ structurally different countries is the biggest risk to
* interpretability (cf. Aslan et al.'s oil-export/import split and Zhang
* et al.'s East/Central/West split). Re-estimate the baseline PVAR for each
* subgroup.

* --- 11.1 By income group ---
foreach g in "High income" "Upper middle income" "Lower middle income" "Low income" {
    display "=== PVAR for income group: `g' ==="
    pvar terror_index fdi_ihs gdp_growth trade_open lninflation polity ///
        if incomegrp == "`g'", lags(2) instlags(1/4) fod gmmstyle
    pvarirf, mc(200) level(95) impulse(terror_index) response(fdi_ihs)
}

* --- 11.2 By region ---
levelsof region, local(regions)
foreach r of local regions {
    display "=== PVAR for region: `r' ==="
    cap pvar terror_index fdi_ihs gdp_growth trade_open lninflation polity ///
        if region == "`r'", lags(2) instlags(1/4) fod gmmstyle
    cap pvarirf, mc(200) level(95) impulse(terror_index) response(fdi_ihs)
}

* --- 11.3 By institutional quality (median split) ---
foreach h in 0 1 {
    display "=== PVAR for highinstit = `h' ==="
    pvar terror_index fdi_ihs gdp_growth trade_open lninflation polity ///
        if highinstit == `h', lags(2) instlags(1/4) fod gmmstyle
    pvarirf, mc(200) level(95) impulse(terror_index) response(fdi_ihs)
}

* --- 11.4 By terrorism exposure (median split) ---
foreach h in 0 1 {
    display "=== PVAR for highterror = `h' ==="
    pvar terror_index fdi_ihs gdp_growth trade_open lninflation polity ///
        if highterror == `h', lags(2) instlags(1/4) fod gmmstyle
    pvarirf, mc(200) level(95) impulse(terror_index) response(fdi_ihs)
}

* --- 11.5 Optional: state dependence on global business cycle ---
* (cf. Rünstler 2024). Construct a global recession/expansion indicator
* (e.g. world GDP growth below/above its long-run trend) and split events.
* gen global_low_state = (world_gdp_growth < world_gdp_growth_trend)
* pvar ... if global_low_state == 0, ...
* pvar ... if global_low_state == 1, ...


*===============================================================================
* 12. ROBUSTNESS CHECKS
*===============================================================================

* --- 12.1 Alternative terrorism proxies ---
foreach tvar in terror_attacks_ln terror_killed_ln terror_domestic_ln ///
                terror_transnational_ln major_attack {
    display "=== Robustness: terrorism proxy = `tvar' ==="
    pvar `tvar' fdi_ihs gdp_growth trade_open lninflation polity, ///
        lags(2) instlags(1/4) fod gmmstyle
    pvarirf, mc(200) level(95) impulse(`tvar') response(fdi_ihs)
}

* --- 12.2 Alternative Cholesky ordering ---
* Reverse plausible ordering: macro variables first, terrorism last
* (treats terrorism as the most "exogenous-reacting" variable last in the chain)
pvar fdi_ihs gdp_growth trade_open lninflation polity terror_index, ///
    lags(2) instlags(1/4) fod gmmstyle
pvarirf, mc(200) level(95) impulse(terror_index) response(fdi_ihs)

* --- 12.3 Alternative FDI measure (stock instead of flow) ---
pvar terror_index fdi_stock_ihs gdp_growth trade_open lninflation polity, ///
    lags(2) instlags(1/4) fod gmmstyle

* --- 12.4 Excluding turbulent global periods ---
* (1973-74 oil crisis, 2008-09 GFC, 2020 COVID) - cf. Rünstler's exclusion of
* 2010-13 turbulence and Caraiani et al.'s discussion of the GFC/COVID period.
pvar terror_index fdi_ihs gdp_growth trade_open lninflation polity ///
    if !inlist(year,1973,1974,2008,2009,2020), ///
    lags(2) instlags(1/4) fod gmmstyle

* --- 12.5 Sub-period split (structural break check) ---
* Cold War vs. post-Cold War vs. post-9/11 era
pvar terror_index fdi_ihs gdp_growth trade_open lninflation polity ///
    if year <= 1991, lags(2) instlags(1/4) fod gmmstyle
pvar terror_index fdi_ihs gdp_growth trade_open lninflation polity ///
    if year > 1991 & year <= 2001, lags(2) instlags(1/4) fod gmmstyle
pvar terror_index fdi_ihs gdp_growth trade_open lninflation polity ///
    if year > 2001, lags(2) instlags(1/4) fod gmmstyle

* --- 12.6 Different lag length ---
pvar terror_index fdi_ihs gdp_growth trade_open lninflation polity, ///
    lags(1) instlags(1/4) fod gmmstyle
pvar terror_index fdi_ihs gdp_growth trade_open lninflation polity, ///
    lags(3) instlags(1/4) fod gmmstyle


*===============================================================================
* 13. EXPORT RESULTS
*===============================================================================
estimates restore pvar_baseline
esttab pvar_baseline using "pvar_baseline_results.rtf", replace ///
    se star(* 0.10 ** 0.05 *** 0.01) title("Baseline PVAR: Terrorism and FDI")

log close
*===============================================================================
* END OF FILE
*===============================================================================
