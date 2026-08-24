*==============================================================================*
* pvar_q_05b_residual_check.do
*
* Terrorism and FDI - quarterly Panel VAR
* RESIDUAL AUTOCORRELATION CHECK FOR SELECTED CELLS
*
* Same logic as part 2b, section 6, applied to the cells where the Wald test
* in pvar_q_05_selected.do turned significant: permil / lic_lmc / top3 at
* lags 7 and 8 (p = 0.044 and 0.045), where the sign of the cumulative FDI
* response to tp_top31 flips between lag 6 and lag 8. That flip, combined
* with an instrument-to-country ratio of 0.60-0.67 in exactly those cells, is
* the signature that led to the lag-8 instrument exclusion for attacks_total
* in part 2b. This file tests directly whether the same mechanism is at work
* here, rather than inferring it from the Wald result alone.
*
* The pvar suite has no Arellano-Bond test, so the assumption that lagged
* levels are valid instruments - which requires serially uncorrelated
* idiosyncratic errors - is tested directly on LSDV residuals. At T of about
* 45-65 quarters per country here the Nickell bias in those residuals is
* larger than in the full quarterly panel (T ~ 80-108), so read the results
* as indicative, not definitive; the pvarj sign flip itself remains the
* primary evidence.
*
* For each of the three equations (inside top3, outside top3, FDI):
*   equation ~ L(1/REFLAG).equation L(1/REFLAG).other1 L(1/REFLAG).other2 i.t
*   then AR(1) to AR(8) on the residual.
* A clear spike at a given lag means that lag is not a valid instrument,
* independently of what lags(p) is chosen for estimation.
*
* Output: output/logs/resid_check_<STAMP>.log
*         output/tables/residcheck_<STAMP>.csv
*
* Stata 18.
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

foreach d in "$OUT" "$LOGS" "$TABLES" {
    cap mkdir "`d'"
}

global STAMP "sel1"


*==============================================================================*
* 1. SWITCHES
*==============================================================================*
global BASESAMPLE   "core"
global MINOBS       28
global WINSOR       1

global FDISRC       "fdi_in_pct_qgdp"
global INCVAR       "income_group"
global INCFIXCOUNTRY 1

*--- Which cell(s) to check ---------------------------------------------------*
* Each entry: scaling | sample | terror spec | equation lag order for the LSDV
* regressions. REFLAG need not equal the pvar lag order under test; it only
* has to be long enough to whiten the LSDV residual. 8 is used here because
* the earlier finding concerned a lag-8 phenomenon and a shorter equation lag
* could leave that structure in the residual rather than in the regressors.
global CHECKCELLS `" "permil|lic_lmc|top3|8" "raw|lic_lmc|top3|8" "'

cap log close _all
log using "$LOGS/resid_check_${STAMP}.log", replace text


*==============================================================================*
* 2. LOAD AND BUILD VARIABLES  (mirrors pvar_q_05_selected.do section 2)
*==============================================================================*
use "$DATA/pvar_q_work.dta", clear
xtset id t

cap drop insample n_insample
gen byte insample = s_$BASESAMPLE
bysort id: egen int n_insample = total(insample)
qui replace insample = 0 if n_insample < $MINOBS
bysort id: egen int T_country = total(insample)
xtset id t

*--- income classification ----------------------------------------------------*
cap drop inc_grp
capture confirm variable $INCVAR
if _rc {
    di as error "Income variable '$INCVAR' not found. Set INCVAR in section 1."
    exit 111
}
tempvar inctxt
capture confirm string variable $INCVAR
if !_rc {
    qui gen str80 `inctxt' = $INCVAR
}
else {
    capture decode $INCVAR, gen(`inctxt')
    if _rc qui gen str80 `inctxt' = string($INCVAR)
}
qui replace `inctxt' = lower(itrim(trim(subinstr(`inctxt', "-", " ", .))))

gen byte inc_grp = .
qui replace inc_grp = 3 if strpos(`inctxt', "upper middle") > 0
qui replace inc_grp = 2 if missing(inc_grp) & strpos(`inctxt', "lower middle") > 0
qui replace inc_grp = 4 if missing(inc_grp) & strpos(`inctxt', "high") > 0
qui replace inc_grp = 1 if missing(inc_grp) & strpos(`inctxt', "low") > 0

if $INCFIXCOUNTRY == 1 {
    cap drop _incmode
    bysort id: egen byte _incmode = mode(inc_grp), minmode
    qui replace inc_grp = _incmode
    cap drop _incmode
}
xtset id t

local COND_lic_lmc "inc_grp <= 2"
local COND_exhic   "inc_grp < 4"
local COND_all     "1"

*--- FDI ------------------------------------------------------------------------*
cap drop y_fdi
cap drop _tmpf
gen double _tmpf = $FDISRC if insample
if $WINSOR > 0 {
    local hp = 100 - $WINSOR
    qui _pctile _tmpf if insample, p($WINSOR `hp')
    qui replace _tmpf = r(r1) if insample & _tmpf < r(r1) & !missing(_tmpf)
    qui replace _tmpf = r(r2) if insample & _tmpf > r(r2) & !missing(_tmpf)
}
gen double y_fdi = asinh(_tmpf)
drop _tmpf

*--- terror variables, both scalings, top3/cap/total ----------------------------*
local SPECMAP `" "tot|casualties_total" "cap|casualties_capital casualties_outside_capital" "top3|casualties_top3 casualties_outside_top3" "'
foreach s of local SPECMAP {
    tokenize "`s'", parse("|")
    local slab "`1'"
    local svars "`3'"
    local ai = 0
    foreach v of local svars {
        local ++ai
        capture confirm variable `v'
        if _rc continue
        cap drop tr_`slab'`ai' tp_`slab'`ai' _tt
        gen double tr_`slab'`ai' = asinh(`v') if insample
        gen double _tt = `v' / (pop_lag / 1000000) ///
            if insample & pop_lag > 0 & !missing(pop_lag)
        gen double tp_`slab'`ai' = asinh(_tt)
        drop _tt
    }
}
xtset id t


*==============================================================================*
* 3. HELPER: LSDV RESIDUAL AND ITS AUTOCORRELATION UP TO LAG 8
*==============================================================================*
capture program drop resid_ar
program define resid_ar
    syntax varlist(min=1 max=1), OTHERVARS(string) SUBCOND(string) ///
        REFLAG(integer) RESULTNAME(string)

    local dv : word 1 of `varlist'

    * L(1/reflag).(v1 v2) is not valid syntax for more than one variable in
    * Stata's time-series operators. Build the lag terms for each control
    * variable separately instead.
    local ctrlterms ""
    foreach ov of local othervars {
        local ctrlterms "`ctrlterms' L(1/`reflag').`ov'"
    }

    di as txt _n "  Equation: `dv'   (controls: `othervars', lags 1-`reflag')"

    xtreg `dv' L(1/`reflag').`dv' `ctrlterms' i.t if `subcond', fe
    if _rc {
        di as error "  LSDV failed for `dv' (rc " _rc "); equation skipped."
        exit
    }

    cap drop _resid_ar
    qui predict double _resid_ar if e(sample), e
    xtset id t

    di as txt "    lag        b         se          t"
    forvalues j = 1/8 {
        cap qui xtreg _resid_ar L`j'._resid_ar if `subcond', fe
        if _rc {
            di as error "    lag `j': AR regression failed (rc " _rc ")"
            continue
        }
        cap local b  = _b[L`j'._resid_ar]
        cap local se = _se[L`j'._resid_ar]
        if missing(`b') | missing(`se') | `se' == 0 {
            di as error "    lag `j': coefficient not available"
            continue
        }
        local tt = `b' / `se'
        di as txt %6.0f `j' %10.4f `b' %11.4f `se' %11.2f `tt'

        post `resultname' ("`dv'") (`j') (`b') (`se') (`tt')
    }
    cap drop _resid_ar
end


*==============================================================================*
* 4. RUN THE CHECK FOR EACH REQUESTED CELL
*==============================================================================*
capture postclose rc
postfile rc str10 cellid str12 eqvar int lag double(b se t) ///
    using "$TABLES/residcheck_${STAMP}.dta", replace

foreach cell of global CHECKCELLS {

    tokenize "`cell'", parse("|")
    local sc "`1'"
    local sm "`3'"
    local ts "`5'"
    local rl "`7'"

    local pre = cond("`sc'" == "raw", "tr_", "tp_")
    local cellid "`sc'_`sm'_`ts'"

    * Terror variables of this specification, in order.
    local tvlist ""
    forvalues a = 1/3 {
        capture confirm variable `pre'`ts'`a'
        if !_rc local tvlist "`tvlist' `pre'`ts'`a'"
    }
    if "`tvlist'" == "" {
        di as error "No terror variables found for `ts' / `sc'; cell skipped."
        continue
    }
    local nterr = wordcount("`tvlist'")

    di as txt _n "{hline 90}"
    di as txt "CELL: `cellid'   (LSDV equation lags 1-`rl')"
    di as txt "  sample: ${COND_`sm'}"
    di as txt "{hline 90}"

    if `nterr' == 2 {
        local v1 : word 1 of `tvlist'
        local v2 : word 2 of `tvlist'

        resid_ar `v1', othervars(`v2' y_fdi) subcond(insample & (${COND_`sm'})) ///
            reflag(`rl') resultname(rc)
        resid_ar `v2', othervars(`v1' y_fdi) subcond(insample & (${COND_`sm'})) ///
            reflag(`rl') resultname(rc)
        resid_ar y_fdi, othervars(`v1' `v2') subcond(insample & (${COND_`sm'})) ///
            reflag(`rl') resultname(rc)
    }
    else {
        local v1 : word 1 of `tvlist'
        resid_ar `v1', othervars(y_fdi) subcond(insample & (${COND_`sm'})) ///
            reflag(`rl') resultname(rc)
        resid_ar y_fdi, othervars(`v1') subcond(insample & (${COND_`sm'})) ///
            reflag(`rl') resultname(rc)
    }
}
postclose rc


*==============================================================================*
* 5. SUMMARY
*==============================================================================*
preserve
    use "$TABLES/residcheck_${STAMP}.dta", clear
    format b se t %9.4f
    di as txt _n "{hline 78}"
    di as txt "Residual autocorrelation summary"
    di as txt "{hline 78}"
    list, noobs sepby(cellid eqvar)
    export delimited using "$TABLES/residcheck_${STAMP}.csv", replace

    di as txt _n "Flag: |t| > 2 at a given lag means that lag is correlated"
    di as txt "with the equation's own error and is not a valid GMM instrument,"
    di as txt "independently of the pvar lag order chosen for estimation."
    gen byte flag = abs(t) > 2
    qui count if flag
    if r(N) > 0 {
        di as error _n "`=r(N)' lag/equation combinations exceed |t| = 2:"
        list cellid eqvar lag b t if flag, noobs
    }
    else {
        di as txt _n "No lag/equation combination exceeds |t| = 2."
    }
restore

di as txt _n "{hline 78}"
di as txt "How this bears on the Wald result"
di as txt "{hline 78}"
di as txt "The Wald test for tp_top31 vs tp_top32 in the FDI equation was"
di as txt "significant only at lags 7 and 8 (p = 0.044, 0.045), not at lag 6"
di as txt "(p = 0.105), and the sign of the cumulative FDI response to"
di as txt "tp_top31 flips between lag 6 and lag 8. If lag 7 or 8 shows"
di as txt "residual autocorrelation here, the same mechanism identified for"
di as txt "attacks_total in part 2b is at work: those instrument lags should"
di as txt "be excluded, and the lag-6 result (weaker, same sign throughout)"
di as txt "is the one to report as the primary finding."

log close
*==============================================================================*
* END
*==============================================================================*
