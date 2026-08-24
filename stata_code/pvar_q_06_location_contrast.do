*==============================================================================*
* pvar_q_06_location_contrast.do
*
* Terrorism and FDI - quarterly Panel VAR
* LOCATION CONTRAST AS A SINGLE VARIABLE
*
* Motivation
* ----------
* The 3-variable systems (capital, outside_capital, FDI) tested location
* heterogeneity with a joint Wald test on two full lag polynomials. Out of 20
* such tests only 2 were significant at 5%, both adjacent lags of the same
* cell. Under a true null the expected count at 20 tests is 1, and P(>=2) is
* about 26%; the Bonferroni threshold at 20 tests is 0.0025, which neither
* p-value (0.044, 0.045) comes close to. That result should be read as
* essentially null, not as a location effect.
*
* This file does not add more tests in the hope of finding significance. It
* increases POWER for the same question by folding the two location series
* into a single contrast variable, which halves the system (3 -> 2
* variables), roughly halves the instrument count per equation, and turns the
* question from a joint Wald test on two lag polynomials into a single Granger
* test on one. If a real difference exists, this specification is better
* placed to detect it. If it does not, the null result becomes more credible
* precisely because the test had more power to reject it.
*
* Construction of the contrast variable
* --------------------------------------
* x_loc = asinh(inside) - asinh(outside)
*
* Not a ratio or a share: asinh is defined at zero, so a quarter with no
* events of either kind gives x_loc = 0 rather than a missing value, which
* would otherwise reintroduce the missing-data problem that a share variable
* (inside / (inside+outside)) has whenever both counts are zero. Because
* asinh(x) approximately equals ln(2x) away from zero, x_loc approximates the
* log ratio of inside to outside intensity for observations where at least
* one side is not tiny, while remaining well defined everywhere else.
*
* An optional control for overall intensity, asinh(total per capita), can be
* added as a strictly exogenous regressor. Because an exogenous regressor
* enters both the instrument set and the parameter count identically, it costs
* zero net overidentification degrees of freedom (verified against the part 2
* accounting: df = n^2 * INSTEXTRA regardless of exogenous regressors). Adding
* it is therefore free in terms of test power and rules out the concern that
* x_loc is just picking up total terror intensity.
*
* Honesty note for the write-up
* ------------------------------
* This specification was constructed AFTER the 3-variable results were seen,
* explicitly because those tests were underpowered. That must be disclosed.
* Frame it as a deliberate power-improving reformulation of the same
* pre-specified question, not as an additional search for significance, and
* report the 3-variable result alongside it rather than replacing it. Most
* importantly: cells are selected below by the gatekeepers (Hansen J,
* eigenvalue stability) only. The Wald/Granger p-value is reported for every
* passing cell, not used to pick which ones to show.
*
* Output: output/logs/locctr_<STAMP>.log
*         output/tables/locctr_grid_<STAMP>.csv
*         output/tables/locctr_decision_<STAMP>.csv
*         output/tables/locctr_irf_<STAMP>.csv          (DEEPCELLS only)
*         output/figures/irf_locctr_<cell>.png            (DEEPCELLS only)
*
* Stata 18. Required: pvar, pvarirf, pvarstable (Abrigo & Love)
*==============================================================================*

clear all
set more off
set linesize 220
version 18

*------------------------------------------------------------------------------*
* 0. PATHS
*------------------------------------------------------------------------------*
global ROOT     "C:/Users/Benedikt/PycharmProjects/terror_and_fdi"
global DATA     "$ROOT/data/processed"
global OUT      "$ROOT/output"
global LOGS     "$OUT/logs"
global TABLES   "$OUT/tables"
global FIGS     "$OUT/figures"

foreach d in "$OUT" "$LOGS" "$TABLES" "$FIGS" {
    cap mkdir "`d'"
}

global STAMP "loc1"

cap log close _all
log using "$LOGS/locctr_${STAMP}.log", replace text


*==============================================================================*
* 1. SWITCHES
*==============================================================================*
global BASESAMPLE   "core"
global MINOBS       28
global WINSOR       1
global INSTEXTRA    2

global FDISRC       "fdi_in_pct_qgdp"
global INCVAR       "income_group"
global INCFIXCOUNTRY 1

*--- Grid dimensions ----------------------------------------------------------*
global LOCVARS      "cap top3"
global SCALINGS     "permil raw"
global CONTROLS     "0 1"          // 0: x_loc alone; 1: + exogenous total control
global SAMPLES      "lic_lmc exhic"
global LAGLIST      "1 2 3 4 5 6 7 8"

global COND_lic_lmc "inc_grp <= 2"
global COND_exhic   "inc_grp < 4"
global COND_all     "1"
global COND_terrhigh "g_terr==3"

*--- Gatekeeper thresholds -----------------------------------------------------*
global JP_MIN       0.05
global MOD_MAX      0.98

*--- Deep analysis: which cells get Monte Carlo bands and a graph -------------*
* Empty by default. Fill in AFTER reviewing the decision table, using the
* format "locvar|scaling|control|sample|lag", e.g. "cap|permil|0|lic_lmc|6".
* This is a second, separate run of section 6 only - see the note at the end.
global DEEPCELLS `" "'

global STEP 40
global MC   500


*==============================================================================*
* 2. LOAD AND BUILD VARIABLES
*==============================================================================*
use "$DATA/pvar_q_work.dta", clear
xtset id t

cap drop insample n_insample
gen byte insample = s_$BASESAMPLE
bysort id: egen int n_insample = total(insample)
qui replace insample = 0 if n_insample < $MINOBS
bysort id: egen int T_country = total(insample)
xtset id t

*--- income classification (as in file 05) ------------------------------------*
cap drop inc_grp
capture confirm variable $INCVAR
if _rc {
    di as error "Income variable '$INCVAR' not found."
    exit 111
}
tempvar inctxt
capture confirm string variable $INCVAR
if !_rc qui gen str80 `inctxt' = $INCVAR
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

* terrhigh needs a country-level terror tercile, built the same way as in the
* screening file: averaged within country first so a country stays in one
* group for the whole sample.
cap drop g_terr
bysort id: egen double _tc = mean(casualties_total) if insample
bysort id: egen double _tcm = max(_tc)
drop _tc
preserve
    keep if insample
    collapse (first) _tcm, by(id)
    xtile g_terr = _tcm, nq(3)
    keep id g_terr
    tempfile gt
    save `gt'
restore
merge m:1 id using `gt', nogen keep(master match)
drop _tcm
xtset id t

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

*--- Location contrast variables -----------------------------------------------*
* x_loc_<loc>_<scale> = asinh(inside) - asinh(outside)
* x_tot_<scale>        = asinh(total), the optional exogenous control
* x_share_<loc>         = inside / (inside+outside), descriptive only, not fed
*                          into any pvar call because it is missing whenever
*                          both counts are zero (the majority of quarters)

local PAIRS `" "cap|casualties_capital|casualties_outside_capital" "top3|casualties_top3|casualties_outside_top3" "'

foreach pr of local PAIRS {
    tokenize "`pr'", parse("|")
    local lb  "`1'"
    local vin "`3'"
    local vout "`5'"

    capture confirm variable `vin'
    capture confirm variable `vout'

    * raw scaling
    cap drop x_loc_`lb'_raw
    gen double x_loc_`lb'_raw = asinh(`vin') - asinh(`vout') if insample
    label var x_loc_`lb'_raw "asinh(`vin') - asinh(`vout')"

    * per-capita scaling
    cap drop _in_pm _out_pm x_loc_`lb'_permil
    gen double _in_pm  = `vin'  / (pop_lag/1000000) if insample & pop_lag>0
    gen double _out_pm = `vout' / (pop_lag/1000000) if insample & pop_lag>0
    gen double x_loc_`lb'_permil = asinh(_in_pm) - asinh(_out_pm)
    label var x_loc_`lb'_permil "asinh(`vin' pm) - asinh(`vout' pm)"
    drop _in_pm _out_pm

    * descriptive share, not used in estimation
    cap drop x_share_`lb'
    gen double x_share_`lb' = `vin' / (`vin' + `vout') ///
        if insample & (`vin' + `vout') > 0
    label var x_share_`lb' "`vin' / (`vin'+`vout'), descriptive only"
}

* Total intensity control, both scalings.
cap drop x_tot_raw x_tot_permil _tot_pm
gen double x_tot_raw = asinh(casualties_total) if insample
gen double _tot_pm = casualties_total / (pop_lag/1000000) if insample & pop_lag>0
gen double x_tot_permil = asinh(_tot_pm)
drop _tot_pm

xtset id t
qui count if insample
di as txt _n "Base sample: " %7.0fc r(N) " observations"

di as txt _n "Descriptive: share of casualties inside vs outside (non-missing" ///
    " quarters only):"
foreach lb in cap top3 {
    qui sum x_share_`lb' if insample, detail
    di as txt "  `lb': n=" %6.0fc r(N) "  mean=" %5.3f r(mean) ///
        "  p50=" %5.3f r(p50)
}


*==============================================================================*
* 3. STAGE 1 - GATEKEEPER GRID
*==============================================================================*
* Every cell is a 2-variable system: x_loc first, y_fdi second (Cholesky order
* as before, terror-side variable first). Selection into the decision table
* is by pass_j and pass_mod only. The Wald/Granger p-value is recorded for
* every cell but is NOT part of the selection rule, to avoid rebuilding the
* multiple-testing problem this file was written to move away from.

capture postclose gr
postfile gr str6 locvar str8 scaling byte control str10 sample int(lags ilags) ///
    double(nobs ncty ninst inst_ratio jstat jdf jp maxmod halflife rho) ///
    double(waldchi2 waldp c4 c8 c20 c40) byte(pass_j pass_mod pass_both) ///
    using "$TABLES/locctr_grid_${STAMP}.dta", replace

di as txt _n "{hline 140}"
di as txt "STAGE 1: gatekeeper grid, location contrast variable"
di as txt "{hline 140}"
di as txt %6s "loc" %8s "scale" %4s "ctl" %10s "sample" %5s "lag" %9s "obs" ///
    %5s "cty" %8s "ratio" %9s "J p" %8s "maxmod" %10s "wald p" %10s "c40" %6s "pass"

foreach lv of global LOCVARS {
    foreach sc of global SCALINGS {
        local xv "x_loc_`lv'_`sc'"
        local tv "x_tot_`sc'"

        foreach ct of global CONTROLS {
            local xopt = cond(`ct' == 1, "exog(`tv')", "")

            foreach sm of global SAMPLES {
                local cnd "insample & (${COND_`sm'})"

                capture qui count if `cnd'
                if _rc | r(N) < 500 continue

                qui levelsof id if `cnd', local(cids)
                local cc = wordcount("`cids'")

                foreach p of global LAGLIST {
                    local k = `p' + $INSTEXTRA
                    local ninst = 2 * `k' + `ct'
                    local nparam = 2 * `p' + `ct'

                    cap pvar `xv' y_fdi if `cnd', lags(`p') instlags(1/`k') ///
                        `xopt' td
                    if _rc {
                        continue
                    }

                    local nb = e(N)
                    local js = e(J)
                    local jd = e(J_df)
                    local jpv = cond(missing(`js') | missing(`jd') | ///
                                     `jd' <= 0, ., chi2tail(`jd', `js'))
                    local ratio = `ninst' / `cc'

                    local mm = .
                    cap pvarstable
                    if !_rc {
                        tempname MD
                        cap matrix `MD' = r(Modulus)
                        if _rc cap matrix `MD' = r(modulus)
                        if !_rc {
                            local mm = 0
                            forvalues rr = 1/`=rowsof(`MD')' {
                                forvalues cc2 = 1/`=colsof(`MD')' {
                                    if `MD'[`rr',`cc2'] > `mm' & ///
                                       !missing(`MD'[`rr',`cc2']) {
                                        local mm = `MD'[`rr',`cc2']
                                    }
                                }
                            }
                        }
                    }
                    local hl = cond(!missing(`mm') & `mm'>0 & `mm'<1, ///
                                    ln(0.5)/ln(`mm'), .)

                    tempname SIG
                    local rho = .
                    cap matrix `SIG' = e(Sigma)
                    if !_rc {
                        local s11 = `SIG'[1,1]
                        local s22 = `SIG'[2,2]
                        if `s11'>0 & `s22'>0 {
                            local rho = `SIG'[1,2] / sqrt(`s11'*`s22')
                        }
                    }

                    * Granger/Wald test: all lags of x_loc jointly zero in the
                    * FDI equation. This is the direct, single test of the
                    * research question.
                    local wchi2 = .
                    local wp = .
                    local first = 1
                    local wok = 1
                    forvalues l = 1/`p' {
                        local lp = cond(`l'==1, "L.", "L`l'.")
                        if `first' {
                            cap test [y_fdi]`lp'`xv' = 0
                            local first = 0
                        }
                        else {
                            cap test [y_fdi]`lp'`xv' = 0, accumulate
                        }
                        if _rc {
                            local wok = 0
                            continue, break
                        }
                    }
                    if `wok' {
                        local wchi2 = r(chi2)
                        local wp = r(p)
                    }

                    * Cumulative response of FDI to x_loc, point estimate,
                    * from the analytic MA representation (same algebra as in
                    * file 05, specialised to n=2, no exogenous lag terms).
                    tempname B
                    matrix `B' = e(b)
                    local a11 = `B'[1, 1]
                    local a12 = `B'[1, `p'+1]
                    local a21 = `B'[1, 2*`p'+1]
                    local a22 = `B'[1, 3*`p'+1]
                    * Impact-period Cholesky loading of x_loc onto y_fdi.
                    local L11 = sqrt(`SIG'[1,1])
                    local L21 = `SIG'[2,1] / `L11'
                    * Iterate the MA coefficients out to h=40 in Stata scalars
                    * (n=2 keeps this simple without a Mata detour).
                    tempname PSI
                    matrix `PSI' = J($STEP+1, 4, 0)
                    matrix `PSI'[1,1] = 1
                    matrix `PSI'[1,4] = 1
                    local c4=.
                    local c8=.
                    local c20=.
                    local c40=.
                    local cum = `L21'
                    forvalues hh = 1/$STEP {
                        if `hh' == 1 {
                            local p11 = `a11'
                            local p12 = `a12'
                            local p21 = `a21'
                            local p22 = `a22'
                        }
                        else {
                            local q11 = `p11'
                            local q12 = `p12'
                            local q21 = `p21'
                            local q22 = `p22'
                            local p11 = `a11'*`q11' + `a12'*`q21'
                            local p12 = `a11'*`q12' + `a12'*`q22'
                            local p21 = `a21'*`q11' + `a22'*`q21'
                            local p22 = `a21'*`q12' + `a22'*`q22'
                        }
                        local resp = `p21'*`L11' + `p22'*`L21'
                        local cum = `cum' + `resp'
                        if `hh'==4  local c4  = `cum'
                        if `hh'==8  local c8  = `cum'
                        if `hh'==20 local c20 = `cum'
                        if `hh'==40 local c40 = `cum'
                    }

                    local pj = (`jpv' >= $JP_MIN) & !missing(`jpv')
                    local pm = (`mm' < $MOD_MAX) & !missing(`mm')
                    local pb = `pj' & `pm'

                    di as txt %6s "`lv'" %8s "`sc'" %4.0f `ct' %10s "`sm'" ///
                        %5.0f `p' %9.0fc `nb' %5.0f `cc' %8.3f `ratio' ///
                        %9.4f `jpv' %8.3f `mm' %10.4f `wp' %10.4f `c40' ///
                        %6s = cond(`pb',"yes","no")

                    post gr ("`lv'") ("`sc'") (`ct') ("`sm'") (`p') (`k') ///
                        (`nb') (`cc') (`ninst') (`ratio') (`js') (`jd') ///
                        (`jpv') (`mm') (`hl') (`rho') (`wchi2') (`wp') ///
                        (`c4') (`c8') (`c20') (`c40') (`pj') (`pm') (`pb')
                }
            }
        }
    }
}
postclose gr

preserve
    use "$TABLES/locctr_grid_${STAMP}.dta", clear
    export delimited using "$TABLES/locctr_grid_${STAMP}.csv", replace
restore


*==============================================================================*
* 4. STAGE 2 - DECISION TABLE
*==============================================================================*
* Collapses the lag dimension exactly as in the earlier screening file: how
* many lag orders pass BOTH gatekeepers, and what the diagnostics look like
* at the smallest such order. The Wald p-value at that order is reported for
* completeness, never as a selection criterion.

preserve
    use "$TABLES/locctr_grid_${STAMP}.dta", clear

    gen int lag_pass = lags if pass_both == 1
    bysort locvar scaling control sample: egen int n_pass = total(pass_both)
    bysort locvar scaling control sample: egen int best_lag = min(lag_pass)
    foreach v in jp maxmod waldp c40 ninst inst_ratio ncty nobs {
        bysort locvar scaling control sample: egen double best_`v' = ///
            max(cond(lags == best_lag, `v', .))
    }
    bysort locvar scaling control sample: keep if _n == 1
    keep locvar scaling control sample n_pass best_lag best_jp best_maxmod ///
        best_waldp best_c40 best_ninst best_inst_ratio best_ncty best_nobs
    gsort -n_pass best_lag -best_ncty

    format best_jp best_maxmod best_waldp %8.4f
    format best_c40 %8.4f
    format best_inst_ratio %6.3f

    di as txt _n "{hline 130}"
    di as txt "STAGE 2: decision table"
    di as txt "{hline 130}"
    list locvar scaling control sample n_pass best_lag best_ninst best_ncty ///
        best_inst_ratio best_jp best_maxmod best_waldp best_c40, ///
        noobs sepby(locvar scaling)

    export delimited using "$TABLES/locctr_decision_${STAMP}.csv", replace
restore

di as txt _n "{hline 78}"
di as txt "Reading the decision table"
di as txt "{hline 78}"
di as txt "1. Selection rule: n_pass and best_lag come from the gatekeepers"
di as txt "   only. best_waldp is shown for information; do not choose a row"
di as txt "   because its Wald p-value is small. Choosing on significance"
di as txt "   after the fact reintroduces the multiple-testing problem this"
di as txt "   file exists to avoid."
di as txt "2. control = 1 rows add asinh(total per-capita casualties) as an"
di as txt "   exogenous control, at no cost in overidentification df (verify:"
di as txt "   best_ninst should be nearly identical to the control = 0 row at"
di as txt "   the same lag, off by exactly 1). Compare control 0 vs 1: if the"
di as txt "   x_loc coefficient and its significance survive controlling for"
di as txt "   total intensity, that is a stronger result than either alone."
di as txt "3. Compare across locvar (cap vs top3) and scaling (permil vs raw)"
di as txt "   for consistency. A result that only appears in one of eight"
di as txt "   combinations is exactly the pattern multiple testing produces"
di as txt "   by chance."
di as txt "4. Once you have picked cells based on gatekeeper quality, fill"
di as txt "   DEEPCELLS in section 1 and rerun; section 6 below then adds"
di as txt "   Monte Carlo bands, a graph, and pvarirf/pvargranger output for"
di as txt "   verification against the point estimates already computed."


*==============================================================================*
* 5. WHICH CELLS AGREE WITH THE 3-VARIABLE RESULT?
*==============================================================================*
* Specifically: does x_loc_top3 behave consistently with the earlier
* observation that the outside-top3 series had the larger (more negative)
* response, i.e. does x_loc (inside minus outside, on the same asinh scale)
* come out POSITIVE when it matters - more relative weight on the inside
* series being associated with LESS negative FDI response?

preserve
    use "$TABLES/locctr_grid_${STAMP}.dta", clear
    keep if pass_both == 1
    gen double loc_advantage = c40   // positive: inside less damaging than outside, on net
    di as txt _n "{hline 100}"
    di as txt "Sign pattern of c40 (cumulative FDI response to x_loc) among" ///
        " gatekeeper-passing cells"
    di as txt "{hline 100}"
    tab locvar scaling if c40 > 0
    di as txt "(cells with c40 > 0 above; compare against total passing cells" ///
        " per combination)"
restore


*==============================================================================*
* 6. DEEP ANALYSIS FOR SELECTED CELLS  (fill DEEPCELLS in section 1 first)
*==============================================================================*
if `"$DEEPCELLS"' != `" "' {

    foreach cell of global DEEPCELLS {
        tokenize "`cell'", parse("|")
        local lv "`1'"
        local sc "`3'"
        local ct "`5'"
        local sm "`7'"
        local p  "`9'"

        local xv "x_loc_`lv'_`sc'"
        local tv "x_tot_`sc'"
        local xopt = cond(`ct' == 1, "exog(`tv')", "")
        local k = `p' + $INSTEXTRA
        local cnd "insample & (${COND_`sm'})"
        local cellid "`lv'_`sc'_c`ct'_`sm'_l`p'"

        di as txt _n "{hline 90}"
        di as txt "DEEP CELL: `cellid'"
        di as txt "{hline 90}"

        cap noisily pvar `xv' y_fdi if `cnd', lags(`p') instlags(1/`k') `xopt' td
        if _rc {
            di as error "  estimation failed; skipped"
            continue
        }

        pvarstable
        di as txt _n "--- Granger causality ---"
        cap noisily pvargranger

        di as txt _n "--- Orthogonalised IRF, Monte Carlo bands ---"
        cap noisily pvarirf, mc($MC) oirf porder(`xv' y_fdi) step($STEP) ///
            level(95) byoption(yrescale)
        if !_rc {
            cap graph export "$FIGS/irf_locctr_`cellid'.png", replace width(1800)
        }
    }
}
else {
    di as txt _n "DEEPCELLS is empty: stage 6 skipped. Review the decision"
    di as txt "table, set DEEPCELLS in section 1, and rerun."
}

log close
*==============================================================================*
* END
*==============================================================================*
