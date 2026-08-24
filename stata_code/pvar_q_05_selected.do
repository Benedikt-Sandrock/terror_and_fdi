*==============================================================================*
* pvar_q_05_selected.do
*
* Terrorism and FDI - quarterly Panel VAR
* DEEP ANALYSIS OF THE SELECTED SPECIFICATIONS
*
* Runs on pvar_q_work.dta and follows the screening in pvar_q_04_screening.do.
*
* Selected cells (all with td, instlags = lags + 2, FDI = inflow as percent of
* quarterly GDP, winsorised at 1% and IHS transformed):
*
*   permil  lic_lmc   cap, top3      lags 4, 6, 7, 8      tot lags 6, 7, 8
*   permil  exhic     cap, top3      lags 4, 8            tot lag  8
*   raw     lic_lmc   cap, top3, tot lags 6, 7, 8
*   raw     exhic     cap, top3, tot lag  8
*
* Lag 4 carries cap and top3 only: the total specification does not pass
* Hansen's J there, so the three are not comparable at that order. It is kept
* because it has the lowest instrument burden in the whole grid (18 per
* equation) and the lowest eigenvalue moduli (0.89-0.91).
*
* What this file produces per cell:
*   - the two gatekeepers again, with the instrument-to-country ratio, which
*     the screening tables did not show and which matters in lic_lmc, where
*     45 countries face up to 30 instruments per equation
*   - Granger causality tests
*   - the reduced-form residual correlation matrix
*   - a Wald test that the entire lag polynomial of the capital (top3) series
*     equals that of its complement in the FDI equation. This is the direct
*     test of the research question and does not rely on comparing confidence
*     bands, which is not a test of difference
*   - orthogonalised impulse responses, point estimates from Mata for every
*     cell and Monte Carlo bands plus graphs for the cells listed in DEEPCELLS
*   - a reversed Cholesky ordering check
*   - forecast error variance decomposition for the DEEPCELLS
*
* Output: output/logs/selected_<STAMP>.log
*         output/tables/sel_gatekeepers_<STAMP>.csv
*         output/tables/sel_irf_<STAMP>.csv        full IRF paths
*         output/tables/sel_cumulative_<STAMP>.csv summary at fixed horizons
*         output/tables/sel_waldtests_<STAMP>.csv
*         output/figures/irf_<cell>.png
*         output/estimates/pvar_<cell>.ster
*
* Stata 18. Required: pvar, pvarirf, pvarfevd, pvarstable (Abrigo & Love)
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
global ESTS     "$OUT/estimates"

foreach d in "$OUT" "$LOGS" "$TABLES" "$FIGS" "$ESTS" {
    cap mkdir "`d'"
}

global STAMP "sel1"

cap log close _all
log using "$LOGS/selected_${STAMP}.log", replace text


*==============================================================================*
* 1. SWITCHES
*==============================================================================*

global BASESAMPLE   "core"
global MINOBS       28
global WINSOR       1
global INSTEXTRA    2

*--- FDI variable ------------------------------------------------------------*
global FDISRC       "fdi_in_pct_qgdp"

*--- Income variable, as merged into the data --------------------------------*
global INCVAR       "income_group"
global INCFIXCOUNTRY 1

*--- Impulse response horizon and bands --------------------------------------*
* The screening showed eigenvalue moduli of 0.89 to 0.96, implying half-lives
* of 9 to 19 quarters. A 20-quarter horizon would cut the responses off before
* they decay, so 40 quarters is the default here.
global STEP         40
global MC           500
global LEVEL        95

*--- Cells: scaling | sample | terrspec | lag list ---------------------------*
global CELLS `" "permil|lic_lmc|cap|4 6 7 8" "permil|lic_lmc|top3|4 6 7 8" "permil|lic_lmc|tot|6 7 8" "permil|exhic|cap|4 8" "permil|exhic|top3|4 8" "permil|exhic|tot|8" "raw|lic_lmc|cap|6 7 8" "raw|lic_lmc|top3|6 7 8" "raw|lic_lmc|tot|6 7 8" "raw|exhic|cap|8" "raw|exhic|top3|8" "raw|exhic|tot|8" "'

*--- Cells that additionally get Monte Carlo bands, graphs and FEVD ----------*
* These are slow. Point estimates and all tests run for every cell above.
global DEEPCELLS `" "permil|lic_lmc|cap|6" "'

/*
"permil|lic_lmc|top3|6" "permil|lic_lmc|tot|6" "permil|lic_lmc|cap|4" "permil|lic_lmc|top3|4" "permil|exhic|cap|8" "permil|exhic|top3|8" "permil|exhic|tot|8" "permil|exhic|cap|4" "permil|exhic|top3|4"
*/

*--- Sample conditions -------------------------------------------------------*
global COND_lic_lmc "inc_grp <= 2"
global COND_exhic   "inc_grp < 4"
global COND_all     "1"


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

*--- 2a. Income classification ----------------------------------------------*
cap drop inc_grp
cap label drop inclbl
label define inclbl 1 "Low income" 2 "Lower middle income" ///
                    3 "Upper middle income" 4 "High income"

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
label values inc_grp inclbl
xtset id t

*--- 2b. FDI ----------------------------------------------------------------*
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
label var y_fdi "IHS($FDISRC, winsorised)"
drop _tmpf

*--- 2c. Terror variables ---------------------------------------------------*
* Names match the screening file: tr_ raw counts, tp_ per million.
local SPECMAP `" "tot|casualties_total" "cap|casualties_capital casualties_outside_capital" "top3|casualties_top3 casualties_outside_top3" "'

foreach s of local SPECMAP {
    tokenize "`s'", parse("|")
    local slab "`1'"
    local svars "`3'"
    local ai = 0
    foreach v of local svars {
        local ++ai
        capture confirm variable `v'
        if _rc {
            di as error "  terror variable not found: `v'"
            continue
        }
        cap drop tr_`slab'`ai' tp_`slab'`ai' _tt
        gen double tr_`slab'`ai' = asinh(`v') if insample
        gen double _tt = `v' / (pop_lag / 1000000) ///
            if insample & pop_lag > 0 & !missing(pop_lag)
        gen double tp_`slab'`ai' = asinh(_tt)
        drop _tt
        label var tr_`slab'`ai' "IHS(`v')"
        label var tp_`slab'`ai' "IHS(`v' per million)"
    }
}
xtset id t

qui count if insample
di as txt _n "Base sample: " %7.0fc r(N) " observations"


*==============================================================================*
* 3. MATA: ORTHOGONALISED IRF FROM e(b) AND e(Sigma)
*==============================================================================*
* Works for any number of variables. The coefficient layout assumed is the one
* visible in the pvar output: equation by equation, within an equation
* variable by variable in system order, within a variable lag 1 to p,
* exogenous regressors last. Section 4 prints the Mata impact responses next
* to the pvarirf table for the deep cells so the layout can be verified.

capture mata: mata drop pvar_oirf()
mata:
void pvar_oirf(string scalar bname, string scalar signame,
               real scalar n, real scalar p, real scalar nex,
               real scalar H, real rowvector ordv, string scalar outname)
{
    real rowvector b
    real matrix Sig, Al, Psi, P0, S, L, OUT, Ph, Ih
    real scalar i, j, l, h, idx, lo, hi

    b   = st_matrix(bname)
    Sig = st_matrix(signame)

    Al = J(n, n*p, 0)
    for (i = 1; i <= n; i++) {
        for (j = 1; j <= n; j++) {
            for (l = 1; l <= p; l++) {
                idx = (i-1)*(n*p + nex) + (j-1)*p + l
                Al[i, (l-1)*n + j] = b[idx]
            }
        }
    }

    Psi = I(n)
    for (h = 1; h <= H; h++) {
        Ph = J(n, n, 0)
        for (l = 1; l <= min((h, p)); l++) {
            lo = (h-l)*n + 1
            hi = (h-l)*n + n
            Ph = Ph + Al[., ((l-1)*n+1)..((l-1)*n+n)] * Psi[., lo..hi]
        }
        Psi = (Psi, Ph)
    }

    S  = Sig[ordv, ordv]
    L  = cholesky(S)
    P0 = J(n, n, 0)
    P0[ordv, ordv] = L

    OUT = J(H+1, 1 + n*n, 0)
    for (h = 0; h <= H; h++) {
        lo = h*n + 1
        hi = h*n + n
        Ih = Psi[., lo..hi] * P0
        OUT[h+1, 1] = h
        for (i = 1; i <= n; i++) {
            for (j = 1; j <= n; j++) {
                OUT[h+1, 1 + (j-1)*n + i] = Ih[i, j]
            }
        }
    }
    st_matrix(outname, OUT)
}
end


*==============================================================================*
* 4. MAIN LOOP OVER THE SELECTED CELLS
*==============================================================================*

capture postclose gk
postfile gk str8 scaling str10 sample str6 spec int(lags ilags nvar ninst) ///
    double(nobs ncty inst_ratio jstat jdf jp maxmod halflife rho_max) ///
    byte(pass_j pass_mod) ///
    using "$TABLES/sel_gatekeepers_${STAMP}.dta", replace

capture postclose cum
postfile cum str8 scaling str10 sample str6 spec int(lags) str12 shockvar ///
    double(sd_shock r1 r4 c4 c8 c12 c20 c40 peak peak_h) ///
    using "$TABLES/sel_cumulative_${STAMP}.dta", replace

capture postclose irfp
postfile irfp str8 scaling str10 sample str6 spec int(lags h) str12 shockvar ///
    double(resp cumresp) ///
    using "$TABLES/sel_irf_${STAMP}.dta", replace

capture postclose wald
postfile wald str8 scaling str10 sample str6 spec int(lags df) ///
    double(chi2 pvalue) ///
    using "$TABLES/sel_waldtests_${STAMP}.dta", replace


foreach cell of global CELLS {

    tokenize "`cell'", parse("|")
    local sc    "`1'"
    local sm    "`3'"
    local ts    "`5'"
    local laglist "`7'"

    local pre = cond("`sc'" == "raw", "tr_", "tp_")
    local cnd "insample & (${COND_`sm'})"

    * Terror variables of this specification.
    local tvlist ""
    forvalues a = 1/3 {
        capture confirm variable `pre'`ts'`a'
        if !_rc local tvlist "`tvlist' `pre'`ts'`a'"
    }
    if "`tvlist'" == "" {
        di as error "No terror variables found for `ts' / `sc'; cell skipped."
        continue
    }

    local SYS "`tvlist' y_fdi"
    local nv = wordcount("`SYS'")
    local nterr = `nv' - 1

    foreach p of local laglist {

        local k = `p' + $INSTEXTRA
        local ninst = `nv' * `k'
        local cellid "`sc'_`sm'_`ts'_l`p'"

        di as txt _n "{hline 100}"
        di as txt "CELL: `cellid'"
        di as txt "  system: `SYS'   (Cholesky order as listed, FDI last)"
        di as txt "  lags(`p') instlags(1/`k') td"
        di as txt "{hline 100}"

        cap noisily pvar `SYS' if `cnd', lags(`p') instlags(1/`k') td
        if _rc {
            di as error "  estimation failed (rc " _rc "); cell skipped."
            continue
        }

        local nb = e(N)
        local js = e(J)
        local jd = e(J_df)
        local jpv = cond(missing(`js') | missing(`jd') | `jd' <= 0, ., ///
                         chi2tail(`jd', `js'))

        qui levelsof id if `cnd', local(cids)
        local cc = wordcount("`cids'")
        local ratio = `ninst' / `cc'

        estimates store est_`ts'
        cap estimates save "$ESTS/pvar_`cellid'.ster", replace

        *--- Gatekeeper 1: stability ---------------------------------------*
        local mm = .
        cap noisily pvarstable
        if !_rc {
            tempname MD
            cap matrix `MD' = r(Modulus)
            if _rc cap matrix `MD' = r(modulus)
            if !_rc {
                local mm = 0
                forvalues rr = 1/`=rowsof(`MD')' {
                    forvalues cc2 = 1/`=colsof(`MD')' {
                        if `MD'[`rr',`cc2'] > `mm' & !missing(`MD'[`rr',`cc2']) {
                            local mm = `MD'[`rr',`cc2']
                        }
                    }
                }
            }
        }
        local hl = cond(!missing(`mm') & `mm' > 0 & `mm' < 1, ///
                        ln(0.5)/ln(`mm'), .)

        *--- Gatekeeper 2: Hansen J ----------------------------------------*
        di as txt _n "  Hansen J = " %8.3f `js' "  df = " `jd' ///
            "  p = " %6.4f `jpv'
        di as txt "  instruments per equation = `ninst', countries = `cc'" ///
            "  ratio = " %5.2f `ratio'
        if `ratio' > 0.5 {
            di as error "  Instrument-to-country ratio above 0.5: Hansen's J"
            di as error "  loses power here. Treat a high p-value with caution."
        }
        di as txt "  largest modulus = " %6.4f `mm' ///
            "   implied half-life = " %5.1f `hl' " quarters"

        *--- Reduced-form residual correlations ----------------------------*
        tempname SIG
        cap matrix `SIG' = e(Sigma)
        local rhomax = .
        if !_rc {
            di as txt _n "  Reduced-form residual correlations:"
            forvalues i = 1/`nv' {
                forvalues j2 = 1/`nv' {
                    if `j2' > `i' {
                        local sii = `SIG'[`i',`i']
                        local sjj = `SIG'[`j2',`j2']
                        if `sii' > 0 & `sjj' > 0 {
                            local rr2 = `SIG'[`i',`j2'] / sqrt(`sii'*`sjj')
                            local vi : word `i' of `SYS'
                            local vj : word `j2' of `SYS'
                            di as txt "    corr(`vi', `vj') = " %7.4f `rr2'
                            if missing(`rhomax') | abs(`rr2') > abs(`rhomax') {
                                local rhomax = `rr2'
                            }
                        }
                    }
                }
            }
            di as txt "  A largest absolute correlation well below 0.10 means"
            di as txt "  the Cholesky ordering is nearly irrelevant."
        }

        post gk ("`sc'") ("`sm'") ("`ts'") (`p') (`k') (`nv') (`ninst') ///
            (`nb') (`cc') (`ratio') (`js') (`jd') (`jpv') (`mm') (`hl') ///
            (`rhomax') ((`jpv' >= 0.05) & !missing(`jpv')) ///
            ((`mm' < 0.98) & !missing(`mm'))

        *--- Granger causality ---------------------------------------------*
        di as txt _n "  --- Granger causality ---"
        cap noisily pvargranger

        *--- The research question: is the location split significant? ------*
        * Joint Wald test that the whole lag polynomial of the first terror
        * variable equals that of the second in the FDI equation. Comparing
        * two confidence bands is not a test of difference; this is.
        * Note that both series are IHS transformed, so equality is equality
        * of semi-elasticities per unit of the transform.
        if `nterr' == 2 {
            local v1 : word 1 of `tvlist'
            local v2 : word 2 of `tvlist'
            di as txt _n "  --- Wald test: equal effect of `v1' and `v2'" ///
                " in the FDI equation ---"

            local ok = 1
            local first = 1
            forvalues l = 1/`p' {
                local lp = cond(`l' == 1, "L.", "L`l'.")
                if `first' {
                    cap test [y_fdi]`lp'`v1' = [y_fdi]`lp'`v2'
                    local first = 0
                }
                else {
                    cap test [y_fdi]`lp'`v1' = [y_fdi]`lp'`v2', accumulate
                }
                if _rc {
                    local ok = 0
                    continue, break
                }
            }
            if `ok' {
                di as txt "    chi2(" r(df) ") = " %8.3f r(chi2) ///
                    "   p = " %6.4f r(p)
                di as txt "    H0: the capital/top3 series and its complement"
                di as txt "        have identical dynamic effects on FDI."
                post wald ("`sc'") ("`sm'") ("`ts'") (`p') (r(df)) ///
                    (r(chi2)) (r(p))
            }
            else {
                di as error "    Wald test failed; check the coefficient names"
                di as error "    with: matrix list e(b)"
            }
        }

        *--- Impulse responses, point estimates -----------------------------*
        tempname IRF
        local ordv "(1"
        forvalues i = 2/`nv' {
            local ordv "`ordv', `i'"
        }
        local ordv "`ordv')"

        cap mata: pvar_oirf("e(b)", "e(Sigma)", `nv', `p', 0, $STEP, `ordv', "`IRF'")
        if _rc {
            di as error "  Mata IRF failed; skipping the response tables."
            continue
        }

        di as txt _n "  --- Orthogonalised responses of FDI (column " `nv' ") ---"
        di as txt %6s "h" _continue
        forvalues sj = 1/`nterr' {
            local vs : word `sj' of `tvlist'
            di as txt %14s abbrev("`vs'", 13) _continue
        }
        di as txt ""

        forvalues sj = 1/`nterr' {
            local vs : word `sj' of `tvlist'
            local sdsh = sqrt(`SIG'[`sj',`sj'])

            local cumv = 0
            local pk = 0
            local pkh = 0
            local r1 = .
            local r4 = .
            local c4 = .
            local c8 = .
            local c12 = .
            local c20 = .
            local c40 = .

            forvalues hh = 1/`=rowsof(`IRF')' {
                local hrz = `hh' - 1
                * Column for shock sj, response nv (the FDI equation).
                local col = 1 + (`sj'-1)*`nv' + `nv'
                local rv = `IRF'[`hh', `col']
                local cumv = `cumv' + `rv'

                if abs(`rv') > abs(`pk') {
                    local pk = `rv'
                    local pkh = `hrz'
                }
                if `hrz' == 1  local r1 = `rv'
                if `hrz' == 4  local r4 = `rv'
                if `hrz' == 4  local c4 = `cumv'
                if `hrz' == 8  local c8 = `cumv'
                if `hrz' == 12 local c12 = `cumv'
                if `hrz' == 20 local c20 = `cumv'
                if `hrz' == 40 local c40 = `cumv'

                post irfp ("`sc'") ("`sm'") ("`ts'") (`p') (`hrz') ///
                    ("`vs'") (`rv') (`cumv')
            }

            post cum ("`sc'") ("`sm'") ("`ts'") (`p') ("`vs'") (`sdsh') ///
                (`r1') (`r4') (`c4') (`c8') (`c12') (`c20') (`c40') ///
                (`pk') (`pkh')
        }

        forvalues hh = 1/`=rowsof(`IRF')' {
            local hrz = `hh' - 1
            if inlist(`hrz', 0, 1, 2, 4, 8, 12, 20, 40) {
                di as txt %6.0f `hrz' _continue
                forvalues sj = 1/`nterr' {
                    local col = 1 + (`sj'-1)*`nv' + `nv'
                    di as txt %14.5f `IRF'[`hh', `col'] _continue
                }
                di as txt ""
            }
        }

        *--- Reversed Cholesky ordering -------------------------------------*
        * Only the ordering changes; the estimates are the same. With residual
        * correlations of the size reported above the two should be almost
        * indistinguishable beyond the impact horizon.
        tempname IRFR
        local rev "(`nv'"
        forvalues i = `=`nv'-1'(-1)1 {
            local rev "`rev', `i'"
        }
        local rev "`rev')"
        cap mata: pvar_oirf("e(b)", "e(Sigma)", `nv', `p', 0, $STEP, `rev', "`IRFR'")
        if !_rc {
            local maxdiff = 0
            forvalues hh = 1/`=rowsof(`IRF')' {
                forvalues sj = 1/`nterr' {
                    local col = 1 + (`sj'-1)*`nv' + `nv'
                    local dd = abs(`IRF'[`hh',`col'] - `IRFR'[`hh',`col'])
                    if `dd' > `maxdiff' local maxdiff = `dd'
                }
            }
            di as txt _n "  Largest absolute difference between the two" ///
                " Cholesky orderings: " %8.6f `maxdiff'
        }

        *--- Deep analysis for the selected cells ---------------------------*
        local isdeep = 0
        foreach dc of global DEEPCELLS {
            if "`dc'" == "`sc'|`sm'|`ts'|`p'" local isdeep = 1
        }

        if `isdeep' {
            di as txt _n "  --- Monte Carlo bands, graph and FEVD ---"
            cap noisily pvarirf, mc($MC) oirf porder(`SYS') step($STEP) ///
                level($LEVEL) byoption(yrescale)
            if !_rc {
                cap graph export "$FIGS/irf_`cellid'.png", replace width(1800)
                cap graph save   "$FIGS/irf_`cellid'.gph", replace
            }
            else di as error "  pvarirf failed (rc " _rc ")"

            cap noisily pvarfevd, step($STEP) porder(`SYS')
            if _rc cap noisily pvarfevd, step($STEP)
        }
    }
}

postclose gk
postclose cum
postclose irfp
postclose wald


*==============================================================================*
* 5. SUMMARY TABLES
*==============================================================================*

preserve
    use "$TABLES/sel_gatekeepers_${STAMP}.dta", clear
    format jstat maxmod halflife rho_max inst_ratio %9.3f
    format jp %6.3f
    di as txt _n "{hline 120}"
    di as txt "Gatekeepers for the selected cells"
    di as txt "{hline 120}"
    list scaling sample spec lags ninst ncty inst_ratio nobs jstat jdf jp ///
        maxmod halflife rho_max, noobs sepby(scaling sample)
    export delimited using "$TABLES/sel_gatekeepers_${STAMP}.csv", replace
restore

preserve
    use "$TABLES/sel_cumulative_${STAMP}.dta", clear
    format sd_shock r1 r4 c4 c8 c12 c20 c40 peak %9.4f
    di as txt _n "{hline 130}"
    di as txt "Cumulative orthogonalised response of FDI to a one-sd terror shock"
    di as txt "{hline 130}"
    list scaling sample spec lags shockvar sd_shock c4 c8 c12 c20 c40 ///
        peak peak_h, noobs sepby(scaling sample spec)
    export delimited using "$TABLES/sel_cumulative_${STAMP}.csv", replace
restore

preserve
    use "$TABLES/sel_irf_${STAMP}.dta", clear
    export delimited using "$TABLES/sel_irf_${STAMP}.csv", replace
restore

capture confirm file "$TABLES/sel_waldtests_${STAMP}.dta"
if !_rc {
    preserve
        use "$TABLES/sel_waldtests_${STAMP}.dta", clear
        format chi2 %9.3f
        format pvalue %6.4f
        di as txt _n "{hline 90}"
        di as txt "Wald tests: equal dynamic effect of the two location series"
        di as txt "  H0 rejected means the location split matters"
        di as txt "{hline 90}"
        list, noobs sepby(scaling sample)
        export delimited using "$TABLES/sel_waldtests_${STAMP}.csv", replace
    restore
}


*==============================================================================*
* 6. HOW TO READ THIS
*==============================================================================*
di as txt _n "{hline 78}"
di as txt "Reading guide"
di as txt "{hline 78}"
di as txt "1. The Wald test is the answer to the research question. Comparing"
di as txt "   two impulse response bands and noting that one excludes zero"
di as txt "   while the other does not is NOT a test that they differ."
di as txt ""
di as txt "2. inst_ratio above 0.5 means Hansen's J has lost power in that"
di as txt "   cell. This affects the lic_lmc cells at lags 7 and 8, where 27"
di as txt "   to 30 instruments face 45 countries. Prefer lag 6 there and"
di as txt "   lag 4 for the cap and top3 systems."
di as txt ""
di as txt "3. Units. Both sides are inverse hyperbolic sine transforms, so a"
di as txt "   cumulative response of -0.05 is roughly a five percent change"
di as txt "   in the FDI-to-GDP ratio, and only away from zero. With 70 to 89"
di as txt "   percent of the terror series at zero, say so explicitly."
di as txt ""
di as txt "4. sd_shock is the size of the one-standard-deviation shock in the"
di as txt "   transformed units, so responses across specifications are only"
di as txt "   comparable after accounting for it."
di as txt ""
di as txt "5. Half-lives of 9 to 19 quarters are long for a terror shock."
di as txt "   Report them and discuss whether they are plausible, rather than"
di as txt "   showing only the first eight quarters of the response."
di as txt ""
di as txt "6. The full sample and the terrhigh split pass no specification at"
di as txt "   all. That the model only works after excluding high-income"
di as txt "   countries is a result and belongs in the text."

log close
*==============================================================================*
* END
*==============================================================================*
