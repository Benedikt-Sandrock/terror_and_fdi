*===============================================================================
* PROJECT:   Terrorism and FDI - Panel VAR Analysis (100+ countries, 1970-2020)
* APPROACH:  GMM-based PVAR (Abrigo & Love 2016)
* REQUIRES:  ssc install pvar xtwest moremata xtcd2
*===============================================================================
*
* ===================== VARIABLE MAPPING NOTES (READ FIRST) ===================
*
* 1) TERRORISM: your data already distinguishes business vs. non-business
*    targets and capital/top3-city vs. other locations. This is exactly the
*    FDI-relevant split the literature wants (attacks on foreign-investment-
*    relevant targets in economic centers) - far better than a generic count.
*    => PRIMARY treatment variable: cas_top3_business (casualties from attacks
*       on business targets in the 3 largest/most important cities).
*    => incidents_total / fatalities_total kept as conventional baseline
*       alternative for comparability with prior literature.
*
* 2) INSTITUTIONAL QUALITY - CRITICAL DATA ISSUE:
*    World Bank WGI (cc ge pv rl rq va) is only available from 1996 onward.
*    Using any of these as a baseline endogenous variable in a 1970-2020 PVAR
*    would silently drop ~half your sample (1970-1995). V-Dem variables
*    (v2x_* ) have full historical coverage back well before 1970.
*    => BASELINE institution variable: v2xcl_prpty (V-Dem property rights
*       protection) - most directly tied to FDI/expropriation-risk theory.
*    => WGI variables reserved for a POST-1996 ROBUSTNESS subsample only.
*
* 3) `pv` (WGI "Political Stability and Absence of Violence/Terrorism") is
*    PARTIALLY CONSTRUCTED FROM terrorism/violence event data. Never use it
*    as a control alongside your terrorism variable - this is a mechanical
*    "bad control" that will bias the terrorism coefficient toward zero by
*    construction, not because of any real economic relationship.
*
* 4) `finv_GDP` - unclear definition from the variable name alone (possibly
*    "financial investment" or total cross-border investment incl. portfolio).
*    NOT used until you confirm its construction; flagged with a TODO below.
*
* 5) No income-group or region classification variable exists in your list.
*    Section 11 below builds proxy groupings from natural_resources_rents
*    (oil-exporter-style split, cf. Aslan et al.) and gdp_per_capita terciles
*    (income-tier proxy) instead. For a real regional split (cf. Zhang et al.
*    East/Central/West), merge a country-region crosswalk by ISO3 first
*    (e.g. via -ssc install kountry- or a manual WB-region lookup table).
*
* 6) No population variable exists for a market-size control. If market-
*    seeking FDI theory matters to your argument, merge WDI population.
*
* 7) GMM instrument proliferation: with N>100 and several controls,
*    instlags(1/4) generates a very large instrument count relative to N.
*    Baseline below uses instlags(1/2); sensitivity to instlags(1/4) is
*    checked explicitly in the robustness section. Watch the Hansen/overid
*    p-value - implausibly high p-values (e.g. >0.25) often signal weak
*    test power from too many instruments rather than genuine validity.
*===============================================================================

clear all
set more off
cap log close
log using "terrorism_fdi_pvar_log.smcl", replace

*-------------------------------------------------------------------------------
* 0. PACKAGE INSTALLATION (run once)
*-------------------------------------------------------------------------------

cap ssc install pvar
cap ssc install xtwest
cap ssc install moremata
cap ssc install xtcd2
cap ssc install pescadf


*===============================================================================
* 1. DATA IMPORT AND PANEL STRUCTURE
*===============================================================================

use "final_data_terror_and_fdi.dta", clear

encode ISO3, gen(ccode)
xtset ccode year

* --- Diagnose panel structure ---
xtdescribe
*tab year, missing
* Check entry/exit countries to confirm unbalanced panel handling
bysort ccode (year): gen first_obs = (_n==1)
bysort ccode (year): gen last_obs  = (_n==_N)
*tab year if first_obs
*tab year if last_obs

*===============================================================================
* 2.0 COVERAGE DIAGNOSTICS
*===============================================================================
* Check for gaps in the FDI data
bysort ccode (year): egen first_data = min(cond(!missing(fdi_inflow_percent), year, .))
bysort ccode (year): egen last_data  = max(cond(!missing(fdi_inflow_percent), year, .))

gen gap_in_country = 0
bysort ccode: replace gap_in_country = 1 if missing(fdi_inflow_percent) & year > first_data & year < last_data
bysort ccode: egen has_gaps = sum(gap_in_country)

drop first_data last_data gap_in_country

*drop country-periods if there are too many gaps / not sufficient data to interpolate
drop if ISO3 == "BTN" & year < 2002
drop if ISO3 == "DJI" & year < 1987
drop if ISO3 == "ERI" & (year < 1996 | year > 2011)
drop if ISO3 == "GEO" & year < 1997
drop if ISO3 == "GNB" & year < 1984
drop if ISO3 == "KHM" & year < 1992
drop if ISO3 == "MAC" & year < 1985
drop if ISO3 == "NPL" & year <1996
drop if ISO3 == "SDN" & year <1972
drop if ISO3 == "TLS" & year <2005
drop if ISO3 == "SYR" & (year <1972 | year > 2011)
drop if ISO3 =="ALB" & year < 1992
drop if ISO3 == "BLZ" & year < 1984 

*interpolate countries
bysort ccode (year): ipolate fdi_inflow_percent year, gen(fdi_temp)
gen has_interpolation = 0
replace has_interpolation = 1 if missing(fdi_inflow_percent) & !missing(fdi_temp)
replace fdi_inflow_percent = fdi_temp if missing(fdi_inflow_percent)
bysort ccode: egen interpolation_num = sum(has_interpolation)
drop fdi_temp

*Countries with interpolation:
*Burundi (6), Guinea (1), Iraq (2), Libyen (1), French Polynesia (1), El Salvador (2)
*Remove observations where FDI data is still missing
drop if missing(fdi_inflow_percent)



* Several plausible controls have limited historical coverage. Check before
* committing to a baseline specification, or you will silently truncate the
* 1970-2020 sample.

foreach v of varlist cc ge pv rl rq va v2x_libdem v2x_rule v2xcl_prpty ///
                      stat_corp_tax_rate mobile_phone_subs telephone_subs ///
                      natural_resources_rents REER ltrate strate hc {
    quietly summarize year if !missing(`v')
    display "`v': covers " r(min) "-" r(max) ", N=" r(N)
}
* Expect: WGI vars (cc ge pv rl rq va) start ~1996; V-Dem vars (v2x_*) and
* natural_resources_rents should cover most/all of 1970-2020.


*===============================================================================
* 2. VARIABLE CONSTRUCTION
*===============================================================================

* --- 2.1 Terrorism: exploit the business/location split in your data ---

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

gen incidents_total_pc = incidents_total / population_total
gen fatalities_total_pc = fatalities_total / population_total
gen wounded_total_pc = wounded_total / population_total
gen casualties_total_pc = casualties_total / population_total
gen casualties_capital_pc = casualties_capital / population_total
gen casualties_no_capital_pc = casualties_no_capital / population_total
gen incidents_capital_pc = incidents_capital / population_total
gen casualties_top3_pc = casualties_top3 / population_total
gen casualties_no_top3_pc = casualties_no_top3 / population_total
gen incidents_top3_pc = incidents_top3 / population_total
gen cas_capital_business_pc = cas_capital_business / population_total
gen cas_capital_nonbusiness_pc = cas_capital_nonbusiness / population_total
gen cas_nocapital_business_pc = cas_nocapital_business / population_total
gen cas_nocapital_nonbusiness_pc = cas_nocapital_nonbusiness / population_total
gen inc_capital_business_pc = inc_capital_business / population_total
gen inc_capital_nonbusiness_pc = inc_capital_nonbusiness / population_total
gen cas_top3_business_pc = cas_top3_business / population_total
gen cas_top3_nonbusiness_pc = cas_top3_nonbusiness / population_total
gen cas_notop3_business_pc = cas_notop3_business / population_total
gen cas_notop3_nonbusiness_pc = cas_notop3_nonbusiness / population_total
gen inc_top3_business_pc = inc_top3_business / population_total
gen inc_top3_nonbusiness_pc = inc_top3_nonbusiness / population_total

label var incidents_total_pc "incidents_total per capita"
label var fatalities_total_pc "fatalities_total per capita"
label var wounded_total_pc "wounded_total per capita"
label var casualties_total_pc "casualties_total per capita"
label var casualties_capital_pc "casualties_capital per capita"
label var casualties_no_capital_pc "casualties_no_capital per capita"
label var incidents_capital_pc "incidents_capital per capita"
label var casualties_top3_pc "casualties_top3 per capita"
label var casualties_no_top3_pc "casualties_no_top3 per capita"
label var incidents_top3_pc "incidents_top3 per capita"
label var cas_capital_business_pc "cas_capital_business per capita"
label var cas_capital_nonbusiness_pc "cas_capital_nonbusiness per capita"
label var cas_nocapital_business_pc "cas_nocapital_business per capita"
label var cas_nocapital_nonbusiness_pc "cas_nocapital_nonbusiness per capita"
label var inc_capital_business_pc "inc_capital_business per capita"
label var inc_capital_nonbusiness_pc "inc_capital_nonbusiness per capita"
label var cas_top3_business_pc "cas_top3_business per capita"
label var cas_top3_nonbusiness_pc "cas_top3_nonbusiness per capita"
label var cas_notop3_business_pc "cas_notop3_business per capita"
label var cas_notop3_nonbusiness_pc "cas_notop3_nonbusiness per capita"
label var inc_top3_business_pc "inc_top3_business per capita"
label var inc_top3_nonbusiness_pc "inc_top3_nonbusiness per capita"




* PRIMARY FDI-relevant measure: casualties in the capital
* MAIN VARIABLE: ln_casualties_capital
* COMPARISON TO: ln_casualties_nocapital


* --- 2.2 FDI (sign-preserving IHS transform: values can be negative) ---
gen fdi_in_ihs  = ln(fdi_inflow_percent  + sqrt(fdi_inflow_percent^2  + 1))
gen fdi_out_ihs = ln(fdi_outflow_percent + sqrt(fdi_outflow_percent^2 + 1))

* Absolute-value versions for robustness (different scale/composition effects)
gen fdi_in_abs_ihs  = ln(fdi_inflow_abs  + sqrt(fdi_inflow_abs^2  + 1))
gen fdi_out_abs_ihs = ln(fdi_outflow_abs + sqrt(fdi_outflow_abs^2 + 1))


* --- 2.3 Controls ---

* GDP growth (constructed from GDP per capita in constant US$)
bysort ccode (year): gen gdp_growth = ///
    100*(ln(gdp_per_capita_constant) - ln(gdp_per_capita_constant[_n-1])) ///
    if ccode == ccode[_n-1]

* Trade openness - already provided directly; cross-check against components
* trade_share_gmd is taken from the WDI. trade_share_gmd is constructed from 
* single components by GMD.
gen trade_share_gmd = exports_GDP + imports_GDP
correlate trade_share trade_share_gmd


* Inflation (sign-preserving, since infl can be negative and occasionally
* extreme - hyperinflation episodes are heavy-tailed)
gen lninflation = ln(1 + abs(infl)) * sign(infl)

* Institutional quality - BASELINE: V-Dem property rights protection
* (full 1970-2020 coverage, theoretically closest to FDI/expropriation risk)
gen instit_baseline = v2xcl_prpty

* TODO: confirm definition of finv_GDP before using it as a control.
* finv_GDP = gross fixed capital formation in percent of GDP
gen finv = finv_GDP

* Conflict control: state-based armed conflict (UCDP-style indicator).
* Important confound - civil war affects both terrorism intensity and FDI
* through channels unrelated to "terrorism" per se.
tab sb_exist, missing


* --- 2.4 Grouping variables for heterogeneity analysis (Section 11) ---

* Resource-rich vs resource-poor (cf. Aslan et al.'s oil exporter/importer
* split), based on time-averaged natural resource rents per country
preserve
    collapse (mean) mean_nrr = natural_resources_rents, by(ccode)
    xtile nrr_tercile = mean_nrr, nq(3)
    gen resource_rich = (nrr_tercile == 3)
    tempfile nrr_groups
    save `nrr_groups'
restore
merge m:1 ccode using `nrr_groups', nogenerate

* Income-tier proxy (no WB classification variable available), based on
* time-averaged GDP per capita per country
*Income group variable has been added: Classification by World Bank in
* Low income, Lower middle income, Upper middle income, High income


* Terrorism exposure split (time-varying median, based on primary measure)
* Variable is now defined using exposure to general terror, not the specific
* "FDI-related" terror
egen terror_p50 = pctile(casualties_total), p(50)
gen highterror = (casualties_total > terror_p50)


*===============================================================================
* 3. DESCRIPTIVE STATISTICS
*===============================================================================
* count observations per country; drop Andorra and South Sudan with 2 and 4 
* observations, respectively.
bys ccode: egen T = count(fdi_in_ihs)
tab country_txt T if T < 10
drop if T < 10

xtsum casualties_capital casualties_no_capital fdi_inflow_percent
xtsum ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline
sum   ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline, detail

count if casualties_capital == 0
display "Share of country-years with zero casualties in the capital: " r(N)/_N

count if casualties_no_capital == 0
display "Share of country-years with zero casualties oztside the capital: " r(N)/_N

count if incidents_total == 0
display "Share of country-years with zero attacks (any type): " r(N)/_N

correlate ln_casualties_capital ln_casualties_no_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline

list ISO3 year gdp_per_capita_constant gdp_growth if abs(gdp_growth) > 50 & !missing(gdp_growth)

*===============================================================================
* 4. PANEL UNIT ROOT TESTS
*===============================================================================
* Test for cross-sectional-dependence first
xtcd2 ln_casualties_capital
xtcd2 fdi_in_ihs
xtcd2 gdp_growth
xtcd2 trade_share_gmd
xtcd2 lninflation
xtcd2 instit_baseline

xtcdf ln_casualties_capital ln_casualties_no_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline

foreach v in ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline {
    di "----------------──────────────────────────────────"
    di "CIPS Test (2nd Gen) für: `v'"
    di "----------------────────────────────────────────--"
    
    pescadf `v', lags(2)
}

*instit_baseline is non-stationary. Create first difference and test again
gen d_instit = D.instit_baseline

pescadf d_instit, lags(2)

*===============================================================================
* 5. PANEL COINTEGRATION TESTS  (only if levels are I(1) - requires Stata 16+)
*===============================================================================

xtcointtest pedroni fdi_in_ihs ln_casualties_capital gdp_growth trade_share_gmd lninflation instit_baseline, ardl
xtcointtest kao     fdi_in_ihs ln_casualties_capital gdp_growth trade_share_gmd lninflation instit_baseline
xtwest      fdi_in_ihs ln_casualties_capital gdp_growth trade_share_gmd lninflation instit_baseline, lags(2) leads(2) constant


*===============================================================================
* 6. LAG ORDER SELECTION
*===============================================================================

pvarsoc ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline, ///
    pvaropts(instlags(1/2) gmmstyle) maxlag(4)


*===============================================================================
* 7. BASELINE PVAR ESTIMATION (GMM, pooled)
*===============================================================================
* instlags(1/2) chosen deliberately conservative given N>100 - see note at
* top of file on instrument proliferation. Compare to instlags(1/4) in
* Section 12.7 as a robustness check.

xtabond2 fdi_in_ihs L.fdi_in_ihs L.ln_casualties_capital L.ln_casualties_no_capital gdp_growth, ///
    gmm(L.fdi_in_ihs L.ln_casualties_capital, lag(2 .)) ///
    iv(gdp_growth trade_share_gmd lninflation instit_baseline) ///
    twostep robust

pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline, ///
    lags(2) instlags(1/2) fod gmmstyle overid

estimates store pvar_baseline
ereturn list
* Check the overid (Hansen J) p-value: very low values reject instrument
* validity; implausibly high values may signal weak power from too many
* instruments rather than genuine support for the model.


*===============================================================================
* 8. STABILITY CHECK
*===============================================================================
pvarstable, graph


*===============================================================================
* 9. GRANGER CAUSALITY (PANEL WALD TESTS)
*===============================================================================
pvargranger


*===============================================================================
* 10. IMPULSE RESPONSE FUNCTIONS AND VARIANCE DECOMPOSITION
*===============================================================================
* Ordering: terrorism first (contemporaneous effect on FDI assumed; FDI/macro
* shocks affect terrorism only with a lag). Stress-tested in Section 12.2.

pvarirf, mc(200) level(95) ///
    impulse(ln_casualties_capital) response(fdi_in_ihs) ///
    figopts(title("IRF: Business-target terrorism shock {&rarr} FDI") ///
            xtitle("Years") ytitle(""))

pvarirf, mc(200) level(95) oirf table

pvarfevd, ///
    impulse(ln_casualties_capital) response(fdi_in_ihs) ///
    figopts(title("FEVD: Share of FDI variance from terrorism shocks"))


*===============================================================================
* 11. HETEROGENEITY / SUBGROUP ANALYSIS
*===============================================================================

* --- 11.1 Resource-rich vs resource-poor (cf. Aslan et al. oil split) ---
foreach r in 0 1 {
    display "=== PVAR for resource_rich = `r' ==="
    cap pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline ///
        if resource_rich == `r', lags(2) instlags(1/2) fod gmmstyle
    cap pvarirf, mc(200) level(95) impulse(ln_casualties_capital) response(fdi_in_ihs)
}

* --- 11.2 Income tier (proxy, no WB classification available) ---
foreach t in 1 2 3 {
    display "=== PVAR for income_tercile = `t' ==="
    cap pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline ///
        if income_tercile == `t', lags(2) instlags(1/2) fod gmmstyle
    cap pvarirf, mc(200) level(95) impulse(ln_casualties_capital) response(fdi_in_ihs)
}

* --- 11.3 Armed-conflict exposure (sb_exist) ---
foreach c in 0 1 {
    display "=== PVAR for sb_exist = `c' ==="
    cap pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline ///
        if sb_exist == `c', lags(2) instlags(1/2) fod gmmstyle
    cap pvarirf, mc(200) level(95) impulse(ln_casualties_capital) response(fdi_in_ihs)
}

* --- 11.4 High vs low terrorism exposure (median split) ---
foreach h in 0 1 {
    display "=== PVAR for highterror = `h' ==="
    cap pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline ///
        if highterror == `h', lags(2) instlags(1/2) fod gmmstyle
    cap pvarirf, mc(200) level(95) impulse(ln_casualties_capital) response(fdi_in_ihs)
}

* --- 11.5 Optional regional split - requires merging a region crosswalk first ---
* merge m:1 ISO3 using "region_crosswalk.dta", nogenerate
* levelsof region, local(regions)
* foreach r of local regions { ... }


*===============================================================================
* 12. ROBUSTNESS CHECKS
*===============================================================================

* --- 12.1 Alternative terrorism proxies (your richest robustness dimension) ---
foreach tvar in terror_incidents_ln terror_fatalities_ln terror_casualties_ln ///
                terror_econ_incidents_ln terror_cap_business_ln terror_cap_nonbus_ln ///
                terror_nocap_business_ln terror_top3_nonbus_ln terror_notop3_business_ln ///
                terror_capital_ln terror_top3_ln terror_nocapital_ln terror_notop3_ln {
    display "=== Robustness: terrorism proxy = `tvar' ==="
    cap pvar `tvar' fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline, ///
        lags(2) instlags(1/2) fod gmmstyle
    cap pvarirf, mc(200) level(95) impulse(`tvar') response(fdi_in_ihs)
}
* Compare business-target vs non-business-target, and capital/top3 vs
* elsewhere: if the FDI effect is concentrated in the business+top3 cells,
* that supports a genuine investment-risk channel rather than a generic
* "any violence reduces FDI" story.

* --- 12.2 Alternative Cholesky ordering ---
pvar fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline ln_casualties_capital, ///
    lags(2) instlags(1/2) fod gmmstyle
pvarirf, mc(200) level(95) impulse(ln_casualties_capital) response(fdi_in_ihs)

* --- 12.3 Alternative FDI measures ---
pvar ln_casualties_capital fdi_out_ihs gdp_growth trade_share_gmd lninflation instit_baseline, ///
    lags(2) instlags(1/2) fod gmmstyle
pvar ln_casualties_capital fdi_in_abs_ihs gdp_growth trade_share_gmd lninflation instit_baseline, ///
    lags(2) instlags(1/2) fod gmmstyle

* --- 12.4 Alternative institutional quality measures ---
foreach ivar in v2x_rule v2x_libdem v2x_accountability {
    display "=== Robustness: institution proxy = `ivar' (full sample, V-Dem) ==="
    cap pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation `ivar', ///
        lags(2) instlags(1/2) fod gmmstyle
}
* Post-1996 WGI subsample only (coverage constraint - see notes at top).
* Do NOT use `pv' here - it is mechanically contaminated by violence data.
foreach ivar in cc ge rl rq va {
    display "=== Robustness: institution proxy = `ivar' (WGI, post-1996 subsample) ==="
    cap pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation `ivar' ///
        if year >= 1996, lags(2) instlags(1/2) fod gmmstyle
}

* --- 12.5 Excluding active armed-conflict years ---
* Tests whether the terrorism-FDI effect survives once civil/interstate war
* years are dropped, i.e. is not purely picking up war effects.
pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline ///
    if sb_exist == 0, lags(2) instlags(1/2) fod gmmstyle

* --- 12.6 Excluding turbulent global periods ---
pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline ///
    if !inlist(year,1973,1974,2008,2009,2020), ///
    lags(2) instlags(1/2) fod gmmstyle

* --- 12.7 Sub-period split (structural break check) ---
pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline ///
    if year <= 1991, lags(2) instlags(1/2) fod gmmstyle
pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline ///
    if year > 1991 & year <= 2001, lags(2) instlags(1/2) fod gmmstyle
pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline ///
    if year > 2001, lags(2) instlags(1/2) fod gmmstyle

* --- 12.8 Lag length and instrument-count sensitivity ---
pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline, ///
    lags(1) instlags(1/2) fod gmmstyle
pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline, ///
    lags(3) instlags(1/2) fod gmmstyle
pvar ln_casualties_capital fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline, ///
    lags(2) instlags(1/4) fod gmmstyle      // compare overid p-value to baseline


*===============================================================================
* 13. EXPORT RESULTS
*===============================================================================
estimates restore pvar_baseline
esttab pvar_baseline using "pvar_baseline_results.rtf", replace ///
    se star(* 0.10 ** 0.05 *** 0.01) title("Baseline PVAR: Terrorism (business-target, top-3 cities) and FDI")

log close
*===============================================================================
* END OF FILE
*===============================================================================
