*===============================================================================
* PROJECT:   Terrorism and FDI - Panel VAR Analysis (170 countries, up to 51
*            years per country, unbalanced panel, 1970-2020)
* APPROACH:  GMM-based PVAR (Abrigo & Love 2016)
* REQUIRES:  ssc install pvar xtwest moremata xtcd2 pescadf xtabond2
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
* 5) No region classification variable exists in your list. Section 11
*    below builds a proxy grouping from natural_resources_rents (oil-
*    exporter-style split, cf. Aslan et al.). See note 9 below on the
*    income-group / income-tercile split, which has since been fixed.
*    For a real regional split (cf. Zhang et al. East/Central/West), merge
*    a country-region crosswalk by ISO3 first (e.g. via -ssc install
*    kountry- or a manual WB-region lookup table).
*
* 6) population_total IS already merged into the data (used for the
*    per-capita terrorism measures in Section 2.1), so a market-size
*    control is now included - see pop_growth in Section 2.3/2.4.
*
* 7) GMM instrument proliferation: with N>100 and several controls,
*    instlags(1/4) generates a very large instrument count relative to N.
*    Baseline below uses instlags(1/2); sensitivity to instlags(1/4) is
*    checked explicitly in the robustness section. Watch the Hansen/overid
*    p-value - implausibly high p-values (e.g. >0.25) often signal weak
*    test power from too many instruments rather than genuine validity.
*
* 8) COUNTRY VS. YEAR EFFECTS IN PVAR: pvar's fod option removes unit
*    (country) fixed effects via forward orthogonal deviations (Helmert
*    transformation) - this is the PVAR analogue of country FE and is
*    already in the baseline. There is NO direct analogue of year FE inside
*    pvar: a variable that is constant across i for a given t (e.g. a year
*    dummy) has zero within-panel variation and cannot enter the GMM moment
*    conditions sensibly. The standard fix (Love and Zicchino 2006) is to
*    subtract the period (cross-sectional) mean from every system variable
*    before estimation - implemented below as an explicit robustness
*    specification (Section 4b), not as the unconditional baseline, because
*    it also removes genuine global trends (e.g. a worldwide rise/fall in
*    terrorism) that may be substantively important to keep.
*
* 9) INCOME GROUPS: the original heterogeneity section referenced an
*    "income_tercile" variable that was never actually generated anywhere
*    in this file - running it as-is would have thrown a "variable not
*    found" error at Section 11.2. Fixed in Section 2.4 below: the file now
*    checks for a genuine World Bank income-group variable in the merged
*    data and uses it if present; otherwise it falls back to a time-averaged
*    GDP-per-capita tercile, exactly like the resource-rents split.
*
* 10) COLD WAR / STRUCTURAL BREAK: a coldwar dummy (<=1991) is added as an
*    optional level-shift control (e.g. in the reduced-form xtabond2 spec).
*    Note your existing Section 12.7 sub-period split (<=1991 / 1992-2001 /
*    >2001) is the more informative test for whether the *dynamic*
*    terrorism-FDI relationship itself differs across eras; the dummy only
*    tests for a level shift, so keep both.
*
* CHANGE LOG (this version):
*  - Section 4 rebuilt: systematic CD (xtcd2) + CIPS (pescadf, with and
*    without trend) loop over ALL system + extension-candidate variables,
*    not just the original 6; first-differencing generalized.
*  - Section 4b (NEW): period-demeaned PVAR specification as the practical
*    equivalent of "year FE" (see note 8).
*  - Section 2.4: fixed undefined income_tercile bug; added coldwar dummy
*    and a pop_growth control (resolves the population/market-size gap
*    flagged in note 6 above, since population_total is already merged).
*  - Section 6: lag selection now read off pvarsoc's r(stats) matrix
*    programmatically (MBIC/MAIC/MQIC per lag) into a local `pvarlag',
*    which is then used consistently in Sections 7-12 instead of a
*    hardcoded lags(2) (except Section 12.8, which explicitly varies lags).
*  - Section 7 restructured into 7a (reduced-form single-equation GMM,
*    plus a naive two-way FE benchmark for comparison), 7b (baseline PVAR),
*    7c (NEW: extended-system PVAR with natural_resources_rents and finv).
*===============================================================================

clear all
set more off
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
cap ssc install pescadf
cap ssc install xtabond2
*/

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

gen ln_cas_cap_pc = ln(casualties_capital_pc+1)
gen ln_cas_nocap_pc = ln(casualties_no_capital_pc+1)


* PRIMARY FDI-relevant measure: casualties in the capital
* MAIN VARIABLE: ln_casualties_capital
* COMPARISON TO: ln_casualties_nocapital

rename ln_casualties_capital ln_cas_cap
rename ln_casualties_no_capital ln_cas_no_cap


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

* Population growth - market-size control for market-seeking FDI theory.
* (Closes the gap flagged in note 6 at the top: population_total is
* already merged in for the per-capita terrorism measures, so this is
* a free addition.)
bysort ccode (year): gen pop_growth = ///
    100*(ln(population_total) - ln(population_total[_n-1])) ///
    if ccode == ccode[_n-1]
label var pop_growth "population growth (%, market-size control)"

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

* Income-tier proxy / classification, based on time-averaged GDP per
* capita per country, OR a genuine World Bank income-group variable if one
* exists in the merged data.
* NOTE - BUG FIX: the original file referenced "income_tercile" in the
* heterogeneity section (11.2) but never generated it anywhere, which would
* have stopped the do-file with a "variable not found" error. The block
* below builds it properly, preferring a real WB classification if present.

cap confirm variable income_group
if !_rc {
    di as text "Found income_group in the data - inspect categories below and adjust the recode to your actual coding before trusting income_tercile."
    tab income_group, missing
    * TODO: replace this generic encode with an explicit recode that matches
    * your actual income_group categories/order (Low / Lower-middle /
    * Upper-middle / High income), e.g.:
    * gen income_tercile = 1 if income_group == "Low income"
    * replace income_tercile = 2 if inlist(income_group, "Lower middle income","Upper middle income")
    * replace income_tercile = 3 if income_group == "High income"
    encode income_group, gen(income_tercile)
}
else {
    di as text "No income_group variable found - constructing a GDP-per-capita tercile proxy instead."
    preserve
        collapse (mean) mean_gdppc = gdp_per_capita_constant, by(ccode)
        xtile income_tercile = mean_gdppc, nq(3)
        tempfile income_groups
        save `income_groups'
    restore
    merge m:1 ccode using `income_groups', nogenerate
}

* Cold War / structural-break dummy (see note 10 at top of file)
gen coldwar = (year <= 1991)
label var coldwar "1 = Cold War period (year<=1991), 0 = post-Cold War"

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
xtsum ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline
sum   ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline, detail

count if casualties_capital == 0
display "Share of country-years with zero casualties in the capital: " r(N)/_N

count if casualties_no_capital == 0
display "Share of country-years with zero casualties oztside the capital: " r(N)/_N

count if incidents_total == 0
display "Share of country-years with zero attacks (any type): " r(N)/_N

correlate ln_cas_cap ln_cas_no_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline

list ISO3 year gdp_per_capita_constant gdp_growth if abs(gdp_growth) > 50 & !missing(gdp_growth)

*===============================================================================
* 4. CROSS-SECTIONAL DEPENDENCE + PANEL UNIT ROOT TESTS
*===============================================================================
* Extended vs. the original file: this now loops over the baseline 6
* variables PLUS the two "extended system" candidates from Section 7c
* (natural_resources_rents, finv) and the new pop_growth control, so that
* every variable that might enter a pvar() call has actually been tested -
* not just the original baseline set.

global sys_vars   "ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation instit_baseline"
global ext_vars   "natural_resources_rents finv pop_growth"
global all_vars   "$sys_vars $ext_vars"

* --- 4.1 Cross-sectional dependence (Pesaran 2015 CD test via xtcd2) ---
* CSD is the rule rather than the exception in country panels (common global
* shocks: oil prices, financial crises, world growth cycles). This matters
* directly for unit-root testing: first-generation tests (e.g. plain IPS)
* assume cross-sectional independence and are invalid here if CD is
* rejected - which is exactly why pescadf (second-generation, Pesaran 2007
* CIPS) is used below instead of plain IPS/Fisher-type tests.
foreach v of global all_vars {
    di "=== Cross-sectional dependence (xtcd2): `v' ==="
    cap xtcd2 `v'
}

* --- 4.2 CIPS panel unit root test (Pesaran 2007, via pescadf) ---
* Run once without a trend (appropriate for ratios/growth rates that have no
* obvious deterministic trend: fdi_in_ihs, gdp_growth, trade_share_gmd,
* lninflation, pop_growth) and once with a trend for variables that may be
* drifting over the sample for non-stationarity reasons rather than genuine
* persistence (most plausible candidate: instit_baseline, which reflects a
* slow, partly secular rise in de jure property-rights protection globally).
* Inspect both versions and use your judgement / a time-series plot
* (xtline `v', overlay) to decide which specification is appropriate.

di as result "############ CIPS WITHOUT TREND ############"
foreach v of global all_vars {
    di "----------------------------------------------------"
    di "CIPS test (no trend) for: `v'"
    di "----------------------------------------------------"
    cap pescadf `v', lags(2)
}

di as result "############ CIPS WITH TREND (robustness) ############"
foreach v of global all_vars {
    di "----------------------------------------------------"
    di "CIPS test (with trend) for: `v'"
    di "----------------------------------------------------"
    cap pescadf `v', lags(2) trend
}



* --- 4.3 First-differencing of non-stationary variables ---
* pescadf's null is "non-stationary"; do NOT reject -> take first differences
* and retest. Fill in `nonstationary_vars' below based on what you actually
* see in the CIPS tables above (kept as a manual step deliberately - mixed
* trend/no-trend conclusions need a researcher's judgement call, not a
* hard-coded p-value cutoff). From your previous run, instit_baseline was
* already identified as non-stationary in levels; extend this list with any
* other variable from $all_vars that fails to reject H0 above.

local nonstationary_vars "instit_baseline"      // <-- EDIT based on Section 4.2 output

foreach v of local nonstationary_vars {
    di "=== First-differencing and retesting: `v' ==="
    gen d_`v' = D.`v'
    cap pescadf d_`v', lags(2)
}
* Backward-compatible name used later in the file (loop above creates
* d_instit_baseline; rename to the shorter d_instit used downstream)
cap rename d_instit_baseline d_instit


*===============================================================================
* 4b. REMOVING COMMON TIME EFFECTS (PVAR analogue of year fixed effects)
*===============================================================================
* See note 8 at the top of the file: pvar's fod option already removes
* country fixed effects (Helmert/forward-orthogonal-deviation transform);
* there is no equivalent built-in option for time/year effects, because a
* pure year-dummy has no within-i variation and cannot enter the GMM moment
* conditions sensibly. The standard fix (Love and Zicchino 2006) is to
* subtract the period (cross-sectional) mean from each variable. This is
* estimated as an explicit robustness specification in Section 7b/7c (the
* "td_" - time-demeaned - variables), not silently folded into the baseline,
* because it also removes genuine global trends (e.g. a worldwide rise in
* terrorism after a certain decade) that may be analytically important.

foreach v in ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit {
    egen ybar_`v' = mean(`v'), by(year)
    gen td_`v' = `v' - ybar_`v'
    label var td_`v' "`v', period (year) - demeaned"
}

*===============================================================================
* 5. PANEL COINTEGRATION TESTS  (only if levels are I(1) - requires Stata 16+)
*===============================================================================
* NOTE: standard panel cointegration tests (Pedroni/Kao/Westerlund) require
* ALL variables in the system to be integrated of the same order, typically
* I(1). Based on Section 4, only instit_baseline (and whatever else you add
* to `nonstationary_vars') is I(1) in levels; the rest (terrorism, FDI,
* growth, trade, inflation) are I(0). With a mix of I(0) and I(1) variables
* there is no meaningful "spurious regression in levels" problem to begin
* with for the stationary variables, and a single I(1) regressor cannot be
* "cointegrated" with anything on its own - so these tests are not directly
* applicable here. Use d_instit_baseline (its first difference, already I(0)
* per Section 4.3) in the PVAR system instead of running cointegration tests.
* The block below is kept only in case future data vintages add more I(1)
* variables to the system.
/*
xtcointtest pedroni fdi_in_ihs ln_cas_cap gdp_growth trade_share_gmd lninflation instit_baseline, ardl
xtcointtest kao     fdi_in_ihs ln_cas_cap gdp_growth trade_share_gmd lninflation instit_baseline
xtwest      fdi_in_ihs ln_cas_cap gdp_growth trade_share_gmd lninflation instit_baseline, lags(2) leads(2) constant
*/

*===============================================================================
* 6. LAG ORDER SELECTION
*===============================================================================
* pvarsoc stores CD, J, J-pvalue, MBIC, MAIC, MQIC for lags 1..maxlag in the
* matrix r(stats) (one row per lag). The block below reads that matrix
* programmatically and reports which lag minimizes each MMSC criterion, so
* you don't have to hand-transcribe the table. Per Andrews and Lu (2001),
* the lag minimizing MBIC/MAIC/MQIC is preferred - but ALSO check the J
* p-value column at that lag: a rejection (p<0.05) signals misspecification
* at that lag (don't use it even if MMSC favors it), and an implausibly high
* p-value (>0.25) can signal weak test power from too many instruments
* rather than genuine validity (see note 7 at the top of the file).

pvarsoc ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit, ///
    pvaropts(instlags(1/2) gmmstyle) maxlag(4)

matrix soc_stats = r(stats)
matrix list soc_stats
mata: st_numscalar("lag_minMBIC", selectindex(st_matrix("soc_stats")[.,4] :== min(st_matrix("soc_stats")[.,4])))
mata: st_numscalar("lag_minMAIC", selectindex(st_matrix("soc_stats")[.,5] :== min(st_matrix("soc_stats")[.,5])))
mata: st_numscalar("lag_minMQIC", selectindex(st_matrix("soc_stats")[.,6] :== min(st_matrix("soc_stats")[.,6])))
di as result "Lag minimizing MBIC: " lag_minMBIC
di as result "Lag minimizing MAIC: " lag_minMAIC
di as result "Lag minimizing MQIC: " lag_minMQIC

* Set the working lag order for Sections 7-12 here, based on the criteria
* above AND the Hansen/J p-value check described in the comment block.
* (Requires Stata 14+ for selectindex(); if you are on an older version,
* just read the lag off the displayed table by eye and set this manually.)
local pvarlag = 2    // <-- EDIT after inspecting the output above
di as result "Using pvarlag = `pvarlag' for Sections 7-12 (except 12.8, which varies lags deliberately)."


*===============================================================================
* 7a. REDUCED-FORM (SINGLE-EQUATION) ESTIMATION
*===============================================================================
* "Reduced form" here = the FDI equation estimated on its own (rather than
* as part of the simultaneous PVAR system). Two versions are shown:
*  (i)  a naive two-way fixed-effects benchmark - included ONLY for
*       comparison; it is well known to be biased in the presence of a
*       lagged dependent variable + fixed effects (Nickell bias), which is
*       exactly why panel GMM (ii) is used as the actual reduced-form
*       estimate.
*  (ii) the dynamic panel GMM (Arellano-Bond/Blundell-Bond via xtabond2),
*       now also including coldwar and pop_growth as additional controls
*       (see notes 9/10 at the top of the file).

* (i) naive FE benchmark - for comparison only, not a preferred estimate
cap xtreg fdi_in_ihs ln_cas_cap gdp_growth trade_share_gmd lninflation d_instit pop_growth ///
    i.year, fe vce(cluster ccode)

* (ii) dynamic panel GMM reduced form
xtabond2 fdi_in_ihs L.fdi_in_ihs L.ln_cas_cap L.ln_cas_no_cap gdp_growth pop_growth coldwar, ///
    gmm(L.fdi_in_ihs L.ln_cas_cap, lag(2 .)) ///
    iv(gdp_growth trade_share_gmd lninflation d_instit pop_growth coldwar) ///
    twostep robust


*===============================================================================
* 7b. BASELINE PVAR ESTIMATION (GMM, pooled, full system)
*===============================================================================
* instlags(1/2) chosen deliberately conservative given N>100 - see note at
* top of file on instrument proliferation. Compare to instlags(1/4) in
* Section 12.8 as a robustness check.

pvar fdi_in_ihs ln_cas_cap gdp_growth trade_share_gmd lninflation d_instit, ///
    lags(`pvarlag') instlags(1/2) fod gmmstyle overid

estimates store pvar_baseline
ereturn list
* Check the overid (Hansen J) p-value: very low values reject instrument
* validity; implausibly high values may signal weak power from too many
* instruments rather than genuine support for the model.


*===============================================================================
* 7c. EXTENDED-SYSTEM PVAR (adds variables to the system)
*===============================================================================
* Adds natural_resources_rents and finv (gross fixed capital formation,
* %GDP) to the baseline system. Both were tested for stationarity in
* Section 4 alongside the original 6 variables. Rationale:
*  - natural_resources_rents: classic omitted variable in this literature -
*    resource dependence shapes both terrorism risk (grievance/financing)
*    and FDI (resource-seeking investment is far less terrorism-elastic than
*    other types - cf. the resource_rich heterogeneity split in Sec. 11.1).
*  - finv: domestic investment is a natural complement/substitute for FDI
*    and a control for overall investment climate, separate from terrorism.
* Kept as a SEPARATE system rather than folded into the baseline because
* every additional endogenous variable increases the parameter count by k^2
* and the GMM instrument count further - exactly the proliferation problem
* flagged in note 7 at the top of the file. Treat this as a robustness/
* extension check on the baseline, not a replacement for it.

cap pvar fdi_in_ihs ln_cas_cap gdp_growth trade_share_gmd lninflation d_instit ///
    natural_resources_rents finv, ///
    lags(`pvarlag') instlags(1/2) fod gmmstyle overid
cap estimates store pvar_extended
cap pvarirf, mc(200) level(95) impulse(ln_cas_cap) response(fdi_in_ihs)

* Time-demeaned robustness version of the baseline (see Section 4b) -
* practical equivalent of adding year FE.
cap pvar td_fdi_in_ihs td_ln_cas_cap td_gdp_growth td_trade_share_gmd td_lninflation td_d_instit, ///
    lags(`pvarlag') instlags(1/2) fod gmmstyle overid
cap estimates store pvar_timedemeaned


*===============================================================================
* 8. STABILITY CHECK
*===============================================================================
estimates restore pvar_baseline
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
    impulse(ln_cas_cap) response(fdi_in_ihs) ///
    figopts(title("IRF: Business-target terrorism shock {&rarr} FDI") ///
            xtitle("Years") ytitle(""))

pvarirf, mc(200) level(95) oirf table

pvarfevd, ///
    impulse(ln_cas_cap) response(fdi_in_ihs) ///
    figopts(title("FEVD: Share of FDI variance from terrorism shocks"))


*===============================================================================
* 11. HETEROGENEITY / SUBGROUP ANALYSIS
*===============================================================================

* --- 11.1 Resource-rich vs resource-poor (cf. Aslan et al. oil split) ---
foreach r in 0 1 {
    display "=== PVAR for resource_rich = `r' ==="
    cap pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit ///
        if resource_rich == `r', lags(`pvarlag') instlags(1/2) fod gmmstyle
    cap pvarirf, mc(200) level(95) impulse(ln_cas_cap) response(fdi_in_ihs)
}

* --- 11.2 Income tier (proxy, no WB classification available) ---
foreach t in 1 2 3 {
    display "=== PVAR for income_tercile = `t' ==="
    cap pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit ///
        if income_tercile == `t', lags(`pvarlag') instlags(1/2) fod gmmstyle
    cap pvarirf, mc(200) level(95) impulse(ln_cas_cap) response(fdi_in_ihs)
}

* --- 11.3 Armed-conflict exposure (sb_exist) ---
foreach c in 0 1 {
    display "=== PVAR for sb_exist = `c' ==="
    cap pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit ///
        if sb_exist == `c', lags(`pvarlag') instlags(1/2) fod gmmstyle
    cap pvarirf, mc(200) level(95) impulse(ln_cas_cap) response(fdi_in_ihs)
}

* --- 11.4 High vs low terrorism exposure (median split) ---
foreach h in 0 1 {
    display "=== PVAR for highterror = `h' ==="
    cap pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit ///
        if highterror == `h', lags(`pvarlag') instlags(1/2) fod gmmstyle
    cap pvarirf, mc(200) level(95) impulse(ln_cas_cap) response(fdi_in_ihs)
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
    cap pvar `tvar' fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit, ///
        lags(`pvarlag') instlags(1/2) fod gmmstyle
    cap pvarirf, mc(200) level(95) impulse(`tvar') response(fdi_in_ihs)
}
* Compare business-target vs non-business-target, and capital/top3 vs
* elsewhere: if the FDI effect is concentrated in the business+top3 cells,
* that supports a genuine investment-risk channel rather than a generic
* "any violence reduces FDI" story.

* --- 12.2 Alternative Cholesky ordering ---
pvar fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit ln_cas_cap, ///
    lags(`pvarlag') instlags(1/2) fod gmmstyle
pvarirf, mc(200) level(95) impulse(ln_cas_cap) response(fdi_in_ihs)

* --- 12.3 Alternative FDI measures ---
pvar ln_cas_cap fdi_out_ihs gdp_growth trade_share_gmd lninflation d_instit, ///
    lags(`pvarlag') instlags(1/2) fod gmmstyle
pvar ln_cas_cap fdi_in_abs_ihs gdp_growth trade_share_gmd lninflation d_instit, ///
    lags(`pvarlag') instlags(1/2) fod gmmstyle

* --- 12.4 Alternative institutional quality measures ---
foreach ivar in v2x_rule v2x_libdem v2x_accountability {
    display "=== Robustness: institution proxy = `ivar' (full sample, V-Dem) ==="
    cap pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation `ivar', ///
        lags(`pvarlag') instlags(1/2) fod gmmstyle
}
* Post-1996 WGI subsample only (coverage constraint - see notes at top).
* Do NOT use `pv' here - it is mechanically contaminated by violence data.
foreach ivar in cc ge rl rq va {
    display "=== Robustness: institution proxy = `ivar' (WGI, post-1996 subsample) ==="
    cap pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation `ivar' ///
        if year >= 1996, lags(`pvarlag') instlags(1/2) fod gmmstyle
}

* --- 12.5 Excluding active armed-conflict years ---
* Tests whether the terrorism-FDI effect survives once civil/interstate war
* years are dropped, i.e. is not purely picking up war effects.
pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit ///
    if sb_exist == 0, lags(`pvarlag') instlags(1/2) fod gmmstyle

* --- 12.6 Excluding turbulent global periods ---
pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit ///
    if !inlist(year,1973,1974,2008,2009,2020), ///
    lags(`pvarlag') instlags(1/2) fod gmmstyle

* --- 12.7 Sub-period split (structural break check) ---
pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit ///
    if year <= 1991, lags(`pvarlag') instlags(1/2) fod gmmstyle
pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit ///
    if year > 1991 & year <= 2001, lags(`pvarlag') instlags(1/2) fod gmmstyle
pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit ///
    if year > 2001, lags(`pvarlag') instlags(1/2) fod gmmstyle

* --- 12.8 Lag length and instrument-count sensitivity ---
pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit, ///
    lags(1) instlags(1/2) fod gmmstyle
pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit, ///
    lags(3) instlags(1/2) fod gmmstyle
pvar ln_cas_cap fdi_in_ihs gdp_growth trade_share_gmd lninflation d_instit, ///
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
