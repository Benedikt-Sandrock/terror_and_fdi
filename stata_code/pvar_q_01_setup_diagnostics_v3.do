*==============================================================================*
* pvar_q_01_setup_diagnostics.do      VERSION 3
*
* Terrorism and FDI - quarterly Panel VAR
* PART 1 of 4: setup, switch architecture, sample definitions, panel diagnostics
*
* Changes against version 2:
*   - fixed: current xtcd2 (Ditzen) returns its results as MATRICES, not
*            scalars, so "local cd = r(CD)" raised a type mismatch (r 109).
*            Every returned result is now read through a type-agnostic
*            helper block that handles scalars and matrices alike.
*   - added:  the CD table now stores all four variants that xtcd2 reports
*            (CD, CDw, CDw+, CD*), because they can disagree and the
*            defactored CD* is the informative one.
*   - added:  same type-agnostic reading applied to xtunitroot and pescadf.
*
* Input : data/processed/fdi_gtd_quarterly_scaled.dta
* Output: output/logs/pvar_q_01_<tag>.log
*         output/tables/diag_coverage_<tag>.csv
*         output/tables/diag_cd_<tag>.csv
*         output/tables/diag_unitroot_<tag>.csv
*         data/processed/pvar_q_work.dta
*
* Stata 18. Required user packages: xtcd2, pescadf
*==============================================================================*

clear all
set more off
set linesize 200
version 18

*------------------------------------------------------------------------------*
* 0. PATHS
*------------------------------------------------------------------------------*
global ROOT     "C:/Users/Benedikt/PycharmProjects/terror_and_fdi"
global DATA     "$ROOT/data/processed"
global OUT      "$ROOT/output"
global LOGS     "$OUT/logs"
global TABLES   "$OUT/tables"

cap mkdir "$OUT"
cap mkdir "$LOGS"
cap mkdir "$TABLES"


*==============================================================================*
* 1. SWITCHES
*==============================================================================*

*--- 0. Run diagnostics ------------------------------------------------------*
* CSD and Unit-Root-Tests are only conducdet if RUN_DIAGNOSTICS == 1
global RUN_DIAGNOSTICS 0

*--- 1a. FDI variable --------------------------------------------------------*
* fdi_in_pct_qgdp | fdi_net_pct_qgdp | fdi_in_pc_usd
global FDIRAW      "fdi_in_pct_qgdp"

*--- 1b. Terror variable -----------------------------------------------------*
* attacks_total attacks_capital attacks_outside_capital
* attacks_top3 attacks_outside_top3
* business_target_total business_target_capital business_target_top3
* successful_total fatalities_total fatalities_top3 casualties_total
global TERRORRAW   "attacks_total"

*--- 1c. Terror scaling: raw | permil ----------------------------------------*
global TERRORSCALE "raw"

*--- 1d. Terror smoothing: none | ma4 ----------------------------------------*
global TERRORSMOOTH "none"

*--- 1e. Sample: full | nospe | core | terror --------------------------------*
global SAMPLE      "terror"

*--- 1f. Minimum series length per country -----------------------------------*
global MINOBS      20

*--- 1g. Winsorising of the FDI ratio (percent per tail; 0 = off) ------------*
global WINSOR      1

*--- 1h. Unit-root options ---------------------------------------------------*
global URLAGS      4
global URTREND     "trend"

*--- 1i. Run tag -------------------------------------------------------------*
global TAG "${TERRORRAW}_${FDIRAW}_${SAMPLE}"
if "$TERRORSMOOTH" != "none" global TAG "${TAG}_$TERRORSMOOTH"
if "$TERRORSCALE"  != "raw"  global TAG "${TAG}_$TERRORSCALE"

cap log close _all
log using "$LOGS/pvar_q_01_${TAG}.log", replace text


*==============================================================================*
* 2. LOAD AND SET THE PANEL
*==============================================================================*
use "$DATA/fdi_gtd_quarterly_scaled.dta", clear

capture confirm string variable ISO3
if _rc {
    di as error "ISO3 is not a string variable - check the import."
    exit 459
}
encode ISO3, gen(id)
label var id "Country (encoded ISO3)"

gen t = yq(year, quarter)
format t %tq
label var t "Quarter"

xtset id t
isid id t

qui levelsof id, local(allids)
qui sum t
di as txt _n "Panel grid after xtset:"
di as txt "  countries : " wordcount("`allids'")
di as txt "  quarters  : " %tq r(min) " to " %tq r(max)
di as txt "  rows      : " %9.0fc _N


*==============================================================================*
* 3. SAMPLE DEFINITIONS
*==============================================================================*
gen byte s_full  = (has_fdi_observation == 1 & has_gdp_lag == 1)
gen byte s_nospe = s_full & flag_spe_economy == 0
gen byte s_core  = s_full & flag_spe_economy == 0 & flag_distorted_fx == 0

bysort id: egen double _terrsum = total($TERRORRAW) if s_core
bysort id: egen double terrsum  = max(_terrsum)
drop _terrsum
gen byte s_terror = s_core & terrsum > 0 & !missing(terrsum)

gen byte insample = s_$SAMPLE
label var insample "Selected estimation sample"

bysort id: egen int n_insample = total(insample)
replace insample = 0 if n_insample < $MINOBS

di as txt _n "Sample selection (${SAMPLE}, min $MINOBS quarters):"
foreach s in full nospe core terror {
    qui count if s_`s' == 1
    local n_`s' = r(N)
    qui levelsof id if s_`s' == 1, local(ids)
    di as txt "  s_`s': " %7.0fc `n_`s'' " obs, " wordcount("`ids'") " countries"
}
qui count if insample == 1
local nobs = r(N)
qui levelsof id if insample, local(ids)
local ncty = wordcount("`ids'")
di as txt "  -> selected: " %7.0fc `nobs' " obs, `ncty' countries"

if `nobs' == 0 {
    di as error "The selected sample is empty. Check the switches in section 1."
    exit 2000
}


*==============================================================================*
* 4. VARIABLE CONSTRUCTION
*==============================================================================*

*--- 4a. FDI -----------------------------------------------------------------*
gen double fdi_raw = $FDIRAW if insample
label var fdi_raw "$FDIRAW (raw, in sample)"

gen double fdi_w = fdi_raw

if $WINSOR > 0 {
    local hi_p = 100 - $WINSOR
    qui _pctile fdi_raw if insample, p($WINSOR `hi_p')
    local lo = r(r1)
    local hi = r(r2)

    qui count if insample & fdi_raw < `lo' & !missing(fdi_raw)
    local n_lo = r(N)
    qui count if insample & fdi_raw > `hi' & !missing(fdi_raw)
    local n_hi = r(N)

    qui replace fdi_w = `lo' if insample & fdi_raw < `lo' & !missing(fdi_raw)
    qui replace fdi_w = `hi' if insample & fdi_raw > `hi' & !missing(fdi_raw)

    di as txt _n "FDI winsorised at ${WINSOR}% / `hi_p'%: [" ///
        %9.3f `lo' ", " %9.3f `hi' "]  (" `n_lo' " lower, " `n_hi' " upper)"
}
label var fdi_w "$FDIRAW (winsorised)"

gen double y_fdi = asinh(fdi_w)
label var y_fdi "IHS($FDIRAW)"

*--- 4b. Terror --------------------------------------------------------------*
gen double terr_raw = $TERRORRAW if insample

if "$TERRORSCALE" == "permil" {
    qui replace terr_raw = terr_raw / (pop_lag / 1000000) ///
        if insample & pop_lag > 0 & !missing(pop_lag)
    qui replace terr_raw = . if insample & (missing(pop_lag) | pop_lag <= 0)
    label var terr_raw "$TERRORRAW per million inhabitants"
}
else {
    label var terr_raw "$TERRORRAW (count)"
}

if "$TERRORSMOOTH" == "ma4" {
    gen double terr_use = terr_raw + L1.terr_raw + L2.terr_raw + L3.terr_raw
    label var terr_use "4-quarter rolling sum of $TERRORRAW"
}
else {
    gen double terr_use = terr_raw
    label var terr_use "$TERRORRAW"
}

gen double x_terr = asinh(terr_use)
label var x_terr "IHS(terror)"

*--- 4c. Seasonal dummies ----------------------------------------------------*
qui tab quarter, gen(q_)
forvalues q = 1/4 {
    label var q_`q' "Q`q'"
}

*--- 4d. Differences ---------------------------------------------------------*
gen double d_y_fdi  = D.y_fdi
gen double d_x_terr = D.x_terr
label var d_y_fdi  "First difference of y_fdi"
label var d_x_terr "First difference of x_terr"

*--- 4e. Descriptives --------------------------------------------------------*
di as txt _n "{hline 78}"
di as txt "Descriptives on the estimation sample"
di as txt "{hline 78}"
sum fdi_raw fdi_w y_fdi terr_use x_terr if insample, detail

qui count if insample & terr_use == 0
local nzero = r(N)
local zshare = 100 * `nzero' / `nobs'
di as txt _n "Zero share of the terror variable: " %5.1f `zshare' ///
    "% (" %7.0fc `nzero' " of " %7.0fc `nobs' ")"
if `zshare' > 85 {
    di as error "WARNING: more than 85% zeros. A linear PVAR on this variable"
    di as error "         is driven by a small number of country episodes."
    di as error "         Consider TERRORSMOOTH ma4 or a broader terror measure."
}


*==============================================================================*
* 5. DIAGNOSTIC 1 - COVERAGE AND GAP STRUCTURE
*==============================================================================*
preserve
    keep if insample
    bysort id (t): gen int gap = t - t[_n-1] if _n > 1

    di as txt _n "{hline 78}"
    di as txt "Gap structure within the estimation sample"
    di as txt "{hline 78}"
    tab gap, missing

    bysort id (t): gen byte newrun = (_n == 1 | gap != 1)
    bysort id (t): gen int  runid  = sum(newrun)
    bysort id runid: gen int runlen = _N
    bysort id: egen int maxrun = max(runlen)

    collapse (first) maxrun (count) nq = t (min) firstq = t (max) lastq = t, ///
        by(ISO3)
    gen str8 firsts = string(firstq, "%tq")
    gen str8 lasts  = string(lastq,  "%tq")

    di as txt _n "Countries by longest uninterrupted run:"
    foreach k in 8 12 20 28 40 60 {
        qui count if maxrun >= `k'
        di as txt "  >= `k' quarters: " %4.0f r(N)
    }

    qui count if maxrun < 12
    if r(N) > 0 {
        di as txt _n "Countries whose longest run is shorter than 12 quarters:"
        list ISO3 nq maxrun firsts lasts if maxrun < 12, noobs
    }
    else {
        di as txt _n "Every country has an uninterrupted run of >= 12 quarters."
    }

    keep ISO3 nq maxrun firsts lasts
    order ISO3 nq maxrun firsts lasts
    export delimited using "$TABLES/diag_coverage_${TAG}.csv", replace
restore


*==============================================================================*
* 6. DIAGNOSTIC 2 - CROSS-SECTIONAL DEPENDENCE (PESARAN CD)
*==============================================================================*
* Current xtcd2 reports four variants and stores them as MATRICES:
*   CD    Pesaran (2015, 2021)
*   CDw   Juodis & Reese (2021), randomised; conservative, low power
*   CDw+  CDw with power enhancement, Fan et al. (2015)
*   CD*   Pesaran & Xie (2021), defactored using principal components
*
* CD* is the informative one: if it still rejects after removing the
* principal components, the dependence goes beyond that many common factors.
* That matters twice over - CIPS (Pesaran 2007) corrects for ONE factor only,
* and the td option in pvar removes one common time effect only.
*
* Run on the RAW (non-demeaned) series: time demeaning is a model
* specification for robustness, not a preprocessing step.

if $RUN_DIAGNOSTICS == 1 {

capture postclose cdpost
postfile cdpost str12 variable double(cd cd_p cdw cdw_p cdwp cdwp_p cdstar cdstar_p) ///
    using "$TABLES/diag_cd_${TAG}.dta", replace

di as txt _n "{hline 78}"
di as txt "Pesaran CD test (H0: weak cross-sectional dependence)"
di as txt "{hline 78}"

foreach v in y_fdi x_terr d_y_fdi d_x_terr {

    di as txt _n "--- `v' ---"

    * Initialise every slot so that post always receives eight numbers.
    foreach s in cd cd_p cdw cdw_p cdwp cdwp_p cdstar cdstar_p {
        local `s' = .
    }

    cap noisily xtcd2 `v' if insample

    if _rc {
        di as error "  xtcd2 failed (rc = " _rc ")."
        di as error "  Older releases require xtcd2 to follow an xtreg fit:"
        di as error "     qui xtreg `v' if insample, fe"
        di as error "     xtcd2"
        di as error "  Check with: which xtcd2"
    }
    else {
        * Type-agnostic reading. r() may hold scalars OR matrices depending on
        * the installed version, so try the scalar route first and fall back to
        * the (1,1) element of a matrix.
        local names   "CD    p       CDw   pw      CDwp   pwp     CDstar   pstar"
        local targets "cd    cd_p    cdw   cdw_p   cdwp   cdwp_p  cdstar   cdstar_p"

        local k = 0
        foreach nm of local names {
            local ++k
            local tgt : word `k' of `targets'

            cap local `tgt' = r(`nm')
            if _rc {
                tempname M
                cap matrix `M' = r(`nm')
                if !_rc {
                    cap local `tgt' = `M'[1,1]
                    if _rc local `tgt' = .
                }
                else local `tgt' = .
            }
        }

        * Some releases name the power-enhanced variant differently.
        if missing(`cdwp') {
            foreach nm in CDwplus CDw_plus CDwP {
                if missing(`cdwp') {
                    cap local cdwp = r(`nm')
                    if _rc {
                        tempname M2
                        cap matrix `M2' = r(`nm')
                        if !_rc cap local cdwp = `M2'[1,1]
                    }
                }
            }
        }

        if missing(`cd') {
            di as txt "  Could not read r(); the printed table above is authoritative."
            di as txt "  r() contents for reference:"
            return list
        }
    }

    post cdpost ("`v'") (`cd') (`cd_p') (`cdw') (`cdw_p') ///
                (`cdwp') (`cdwp_p') (`cdstar') (`cdstar_p')
}
postclose cdpost

preserve
    use "$TABLES/diag_cd_${TAG}.dta", clear
    format cd* %9.3f
    di as txt _n "CD summary"
    list variable cd cd_p cdstar cdstar_p, noobs
    export delimited using "$TABLES/diag_cd_${TAG}.csv", replace
restore


*==============================================================================*
* 7. DIAGNOSTIC 3 - PANEL UNIT ROOT TESTS
*==============================================================================*
* IPS / Fisher-ADF : first generation, valid only under cross-sectional
*                    independence. Reported for comparison only.
* CIPS (pescadf)   : second generation, corrects for one common factor. Given
*                    the CD* result above, read it as the best available test,
*                    not as a definitive answer.
*
* IPS aborts on panels with zero variance; sparse terror variables produce
* exactly such panels, so those are excluded from the tests only.

di as txt _n "{hline 78}"
di as txt "Panel unit root tests   (trend: ${URTREND}, lags: ${URLAGS})"
di as txt "{hline 78}"

foreach v in y_fdi x_terr {
    bysort id: egen double _sd_`v' = sd(`v') if insample
    qui count if insample & (_sd_`v' == 0 | missing(_sd_`v'))
    if r(N) > 0 {
        di as txt _n "Note: `v' has no within-country variance in " ///
            %6.0fc r(N) " observations;"
        di as txt "      those panels are excluded from the unit-root tests only."
    }
}

capture postclose urpost
postfile urpost str12 variable str8 test str8 trend double(stat pval) ///
    using "$TABLES/diag_unitroot_${TAG}.dta", replace

foreach v in y_fdi x_terr d_y_fdi d_x_terr {

    local base = subinstr("`v'", "d_", "", 1)
    di as txt _n "==== `v' ===="

    *--- IPS ---
    local st = .
    local pv = .
    cap noisily xtunitroot ips `v' if insample & _sd_`base' > 0 & !missing(_sd_`base'), ///
        lags($URLAGS) $URTREND demean
    if !_rc {
        foreach nm in Zttildebar Ztbar Wtbar tbar {
            if missing(`st') {
                cap local st = r(`nm')
                if _rc local st = .
            }
        }
        foreach nm in p_Zttildebar p_Ztbar p_Wtbar {
            if missing(`pv') {
                cap local pv = r(`nm')
                if _rc local pv = .
            }
        }
        post urpost ("`v'") ("IPS") ("$URTREND") (`st') (`pv')
    }
    else di as error "  IPS failed (rc = " _rc ")"

    *--- Fisher-ADF ---
    local st = .
    local pv = .
    cap noisily xtunitroot fisher `v' if insample & _sd_`base' > 0 & !missing(_sd_`base'), ///
        dfuller lags($URLAGS) $URTREND
    if !_rc {
        foreach nm in Zt Z P Pm {
            if missing(`st') {
                cap local st = r(`nm')
                if _rc local st = .
            }
        }
        foreach nm in p_Zt p_Z p_P p_Pm {
            if missing(`pv') {
                cap local pv = r(`nm')
                if _rc local pv = .
            }
        }
        post urpost ("`v'") ("Fisher") ("$URTREND") (`st') (`pv')
    }
    else di as error "  Fisher-ADF failed (rc = " _rc ")"

    *--- CIPS ---
    local st = .
    cap noisily pescadf `v' if insample & _sd_`base' > 0 & !missing(_sd_`base'), ///
        lags($URLAGS) $URTREND
    if !_rc {
        foreach nm in zt_bar cips tbar Zt_bar cipsstat {
            if missing(`st') {
                cap local st = r(`nm')
                if _rc {
                    tempname M3
                    cap matrix `M3' = r(`nm')
                    if !_rc cap local st = `M3'[1,1]
                    if missing(`st') local st = .
                }
            }
        }
        post urpost ("`v'") ("CIPS") ("$URTREND") (`st') (.)
        if missing(`st') {
            di as txt "  (CIPS statistic not machine-readable; take it and the"
            di as txt "   critical values from the printed output above)"
        }
    }
    else {
        di as error "  pescadf failed (rc = " _rc ")"
        di as error "  pescadf needs a reasonably balanced panel. If it aborts,"
        di as error "  rerun on countries with maxrun >= 40 (see section 5)."
    }
}

postclose urpost

preserve
    use "$TABLES/diag_unitroot_${TAG}.dta", clear
    di as txt _n "{hline 78}"
    di as txt "Unit root summary"
    di as txt "{hline 78}"
    list, noobs sepby(variable)
    export delimited using "$TABLES/diag_unitroot_${TAG}.csv", replace
restore

di as txt _n "{hline 78}"
di as txt "How to read this"
di as txt "{hline 78}"
di as txt "1. CD rejects independence, so base the integration decision on"
di as txt "   CIPS rather than on IPS or Fisher."
di as txt "2. CIPS reports a t-bar statistic. Compare it with the Pesaran"
di as txt "   (2007) critical values printed by pescadf. More negative than"
di as txt "   the critical value means a unit root is rejected."
di as txt "3. If a level series carries a unit root but its first difference"
di as txt "   does not, that variable enters the PVAR in differences."
di as txt "4. Because CD* still rejects after removing principal components,"
di as txt "   the dependence is multi-factor. CIPS corrects for one factor,"
di as txt "   so treat its verdict as indicative and report the td / no-td"
di as txt "   comparison in part 3 as a required robustness check."
}

*==============================================================================*
* 8. SAVE THE WORKING FILE FOR PART 2
*==============================================================================*
cap drop _sd_*
compress
save "$DATA/pvar_q_work.dta", replace

di as txt _n "Saved working file: $DATA/pvar_q_work.dta"
di as txt "Tag for this configuration: ${TAG}"

log close
*==============================================================================*
* END OF PART 1
*==============================================================================*
