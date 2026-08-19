*==============================================================================*
* pvar_q_03_irf.do
*
* Terrorism and FDI - quarterly Panel VAR
* PART 3 of 3: impulse responses, variance decomposition, robustness
*
* Specification carried over from the part 2b diagnostics:
*   variables   x_pm = asinh(attacks per million inhabitants)
*               y_fdi = asinh(winsorised FDI inflow, % of quarterly GDP)
*   lags        5
*   instruments 1/7   -- deliberately stops short of lag 8
*   td          yes
*   J = 11.51, df = 8, p = 0.174, largest eigenvalue modulus 0.880
*
* Why instruments stop at lag 7: the LSDV residual test in part 2b found no
* autocorrelation at lags 1-6 but a clear spike at lag 8 (b = 0.076, t = 6.84
* in the FDI equation). A lag-8 instrument is therefore correlated with the
* error by construction. This is established by an independent residual
* diagnostic, not by searching over J. The lags(8)/instlags(1/10)
* specification, which absorbs the same structure through the regressors
* instead, is reported as a robustness check and gives J p = 0.248.
*
* Output: output/logs/pvar_q_03_<tag>.log
*         output/tables/irf_baseline_<tag>.csv
*         output/tables/irf_robustness_<tag>.csv
*         output/tables/fevd_<tag>.csv
*         output/figures/irf_<tag>.gph / .png
*
* Stata 18. Required: pvar, pvarirf, pvarfevd, pvarstable (Abrigo & Love)
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
global FIGS     "$OUT/figures"
global ESTS     "$OUT/estimates"

foreach d in "$OUT" "$LOGS" "$TABLES" "$FIGS" "$ESTS" {
    cap mkdir "`d'"
}


*==============================================================================*
* 1. SWITCHES
*==============================================================================*
global TERRORRAW    "attacks_total"
global FDIRAW       "fdi_in_pct_qgdp"
global SAMPLE       "core"
global MINOBS       28

*--- Baseline specification --------------------------------------------------*
global TERRVAR      "x_pm"     // x_pm (per capita) | x_raw (counts)
global P            5          // model lags
global K            7          // instrument lags, 1/K
global TD           "td"       // "td" or "" for no time demeaning

*--- Impulse response options ------------------------------------------------*
global STEP         20         // horizon in quarters (5 years)
global MC           500        // Monte Carlo draws for the confidence bands
global LEVEL        95

*--- Cholesky ordering -------------------------------------------------------*
* Baseline places terror first: FDI does not react to terror within the same
* quarter. The reverse ordering is estimated in section 6. Part 2 found the
* reduced-form residual correlation to be about 0.02, so the two orderings
* should be nearly indistinguishable; section 6 verifies that rather than
* assuming it.
global ORDER        "$TERRVAR y_fdi"

global TAG "${TERRVAR}_${FDIRAW}_${SAMPLE}_min${MINOBS}_l${P}i${K}"

cap log close _all
log using "$LOGS/pvar_q_03_${TAG}.log", replace text


*==============================================================================*
* 2. LOAD AND PREPARE
*==============================================================================*
use "$DATA/pvar_q_work.dta", clear
xtset id t

cap drop insample n_insample
gen byte insample = s_$SAMPLE
bysort id: egen int n_insample = total(insample)
qui replace insample = 0 if n_insample < $MINOBS
bysort id: egen int T_country = total(insample)
xtset id t

cap drop x_raw x_pm _pm
gen double x_raw = asinh($TERRORRAW) if insample
gen double _pm = $TERRORRAW / (pop_lag / 1000000) ///
    if insample & pop_lag > 0 & !missing(pop_lag)
gen double x_pm = asinh(_pm)
label var x_raw "IHS(attacks)"
label var x_pm  "IHS(attacks per million)"

local SEAS "q_2 q_3 q_4"

qui count if insample
di as txt _n "Sample: " %7.0fc r(N) " obs"


*==============================================================================*
* 3. SIDE CHECK - IS THE LAG-8 STRUCTURE IN THE DATA OR IN THE DENOMINATOR?
*==============================================================================*
* The part 2b residual test found autocorrelation at lag 8 in the FDI
* equation. Two candidate sources:
*   (a) the denominator, since lagged annual GDP divided by four is a step
*       function that is constant within a year;
*   (b) the IMF quarterly balance-of-payments data themselves, which many
*       countries derive by benchmarking or interpolating annual totals.
*
* The test: repeat the residual autocorrelation check on the UNNORMALISED
* inflow. If the lag-8 spike survives, it lives in the source data; if it
* disappears, the denominator introduced it. Either answer belongs in the
* data section of the thesis.

cap drop y_raw_musd
gen double y_raw_musd = asinh(fdi_inflow_musd) if insample
label var y_raw_musd "IHS(FDI inflow, mn USD, unnormalised)"

di as txt _n "{hline 78}"
di as txt "Residual autocorrelation: normalised vs unnormalised FDI"
di as txt "{hline 78}"

foreach dv in y_fdi y_raw_musd {
    di as txt _n "--- Dependent variable: `dv' ---"
    cap qui xtreg `dv' L(1/$P).`dv' L(1/$P).$TERRVAR i.t if insample, fe
    if _rc {
        di as error "  estimation failed (rc = " _rc ")"
        continue
    }
    cap drop _resid
    qui predict double _resid if e(sample), e
    xtset id t
    di as txt "   lag        b         se          t"
    forvalues j = 1/8 {
        cap qui xtreg _resid L`j'._resid if insample, fe
        if _rc continue
        di as txt %6.0f `j' %10.4f _b[L`j'._resid] %11.4f _se[L`j'._resid] ///
            %11.2f _b[L`j'._resid]/_se[L`j'._resid]
    }
    cap drop _resid
}
di as txt _n "If the lag-8 spike persists without the GDP denominator, it is a"
di as txt "property of the IMF quarterly series, not of our construction."


*==============================================================================*
* 4. MATA: IMPULSE RESPONSES COMPUTED DIRECTLY FROM e(b) AND e(Sigma)
*==============================================================================*
* pvarirf produces the baseline responses with confidence bands. For the
* robustness grid in section 8 the point estimates are computed here instead,
* so that the Cholesky ordering is under explicit control and no assumption
* about pvarirf internals is needed.
*
* Coefficient layout assumed (verified against the part 2 output):
*   e(b) runs equation by equation; within an equation, variable by variable
*   in system order; within a variable, lag 1 to lag p; exogenous regressors
*   last. Section 5 prints both this routine and pvarirf so the layout can be
*   checked before the grid is trusted.

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

    // Companion blocks: Al holds A_1 ... A_p side by side, each n x n.
    Al = J(n, n*p, 0)
    for (i = 1; i <= n; i++) {
        for (j = 1; j <= n; j++) {
            for (l = 1; l <= p; l++) {
                idx = (i-1)*(n*p + nex) + (j-1)*p + l
                Al[i, (l-1)*n + j] = b[idx]
            }
        }
    }

    // Moving-average coefficients: Psi_0 = I, Psi_h = sum_l A_l Psi_(h-l).
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

    // Cholesky factor in the requested ordering, permuted back.
    S  = Sig[ordv, ordv]
    L  = cholesky(S)
    P0 = J(n, n, 0)
    P0[ordv, ordv] = L

    // Row h+1 holds horizon h; columns are (shock s, response r) pairs.
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
* 5. BASELINE ESTIMATION AND IMPULSE RESPONSES
*==============================================================================*
local XOPT = cond("$TD" == "", "exog(`SEAS')", "")
local NEX  = cond("$TD" == "", 3, 0)

di as txt _n "{hline 78}"
di as txt "BASELINE: $ORDER, lags($P), instlags(1/$K), ${TD}"
di as txt "{hline 78}"

pvar $ORDER if insample, lags($P) instlags(1/$K) `XOPT' $TD

local Jb  = e(J)
local Jdb = e(J_df)
di as txt _n "Hansen J = " %8.3f `Jb' "  df = " `Jdb' ///
    "  p = " %6.4f chi2tail(`Jdb', `Jb')

estimates store base
cap estimates save "$ESTS/pvar_base_${TAG}.ster", replace

pvarstable

* Shock size in interpretable units: the orthogonalised shock to the first
* variable is one standard deviation of its reduced-form residual.
tempname SIG
matrix `SIG' = e(Sigma)
local sd_terr = sqrt(`SIG'[1,1])
local sd_fdi  = sqrt(`SIG'[2,2])
local rho     = `SIG'[1,2] / (`sd_terr' * `sd_fdi')
di as txt _n "Residual sd (terror) = " %6.4f `sd_terr' ///
    "   sd (FDI) = " %6.4f `sd_fdi' ///
    "   corr = " %6.4f `rho'
di as txt "A one-sd terror shock moves asinh(attacks per million) by " ///
    %5.3f `sd_terr' ", i.e. it multiplies attacks per million by about " ///
    %5.2f exp(`sd_terr') " away from zero."

*--- Orthogonalised IRFs with Monte Carlo bands ------------------------------*
di as txt _n "--- Orthogonalised impulse responses, $MC draws ---"
cap noisily pvarirf, mc($MC) oirf porder($ORDER) step($STEP) level($LEVEL) ///
    byoption(yrescale) save("$TABLES/irf_baseline_${TAG}", replace)
if _rc {
    di as error "pvarirf failed (rc = " _rc ")."
    di as error "Try without save(), or reduce mc(). The Mata responses below"
    di as error "are computed independently and do not depend on pvarirf."
}
else {
    cap graph export "$FIGS/irf_${TAG}.png", replace width(1600)
    cap graph save "$FIGS/irf_${TAG}.gph", replace
}

*--- The same responses from the Mata routine, for verification --------------*
tempname IRF
mata: pvar_oirf("e(b)", "e(Sigma)", 2, $P, `NEX', $STEP, (1, 2), "`IRF'")

di as txt _n "{hline 78}"
di as txt "Point estimates from the Mata routine (verify against pvarirf)"
di as txt "  column 2: terror shock -> terror"
di as txt "  column 3: terror shock -> FDI      <- the response of interest"
di as txt "  column 4: FDI shock    -> terror"
di as txt "  column 5: FDI shock    -> FDI"
di as txt "{hline 78}"
di as txt %6s "h" %12s "terr->terr" %12s "terr->FDI" %12s "FDI->terr" ///
    %12s "FDI->FDI" %14s "cum terr->FDI"

local cum = 0
forvalues h = 1/`=rowsof(`IRF')' {
    local cum = `cum' + `IRF'[`h', 3]
    if inlist(`h'-1, 0, 1, 2, 3, 4, 8, 12, 16, 20) {
        di as txt %6.0f `IRF'[`h',1] %12.5f `IRF'[`h',2] %12.5f `IRF'[`h',3] ///
            %12.5f `IRF'[`h',4] %12.5f `IRF'[`h',5] %14.5f `cum'
    }
}

di as txt _n "If these differ from the pvarirf table, the assumed coefficient"
di as txt "layout in section 4 is wrong and the grid in section 8 must not be"
di as txt "used. They should agree to several decimals."


*==============================================================================*
* 6. IS THE CHOLESKY ORDERING INNOCUOUS?
*==============================================================================*
* Part 2 found a reduced-form residual correlation of about 0.02, which
* implies that A is nearly diagonal and the recursive assumption is close to
* irrelevant. This section demonstrates it instead of asserting it: the same
* estimates are used, only the ordering changes.

di as txt _n "{hline 78}"
di as txt "Ordering check: terror first vs FDI first"
di as txt "{hline 78}"

tempname IRFR
mata: pvar_oirf("e(b)", "e(Sigma)", 2, $P, `NEX', $STEP, (2, 1), "`IRFR'")

di as txt %6s "h" %16s "terr->FDI (T1)" %16s "terr->FDI (F1)" %14s "difference"
forvalues h = 1/`=rowsof(`IRF')' {
    if inlist(`h'-1, 0, 1, 2, 4, 8, 12, 20) {
        di as txt %6.0f `IRF'[`h',1] %16.5f `IRF'[`h',3] %16.5f `IRFR'[`h',3] ///
            %14.6f `IRF'[`h',3] - `IRFR'[`h',3]
    }
}
di as txt _n "Differences confined to the impact horizon and small thereafter"
di as txt "mean the identification assumption is doing very little work."

cap noisily pvarirf, mc($MC) oirf porder(y_fdi $TERRVAR) step($STEP) ///
    level($LEVEL) byoption(yrescale)
cap graph export "$FIGS/irf_reverse_${TAG}.png", replace width(1600)


*==============================================================================*
* 7. FORECAST ERROR VARIANCE DECOMPOSITION
*==============================================================================*
* How much of the forecast error variance of FDI is attributable to terror
* innovations? This is the natural companion to the IRF: the IRF gives the
* shape of the response, the FEVD its economic weight.

di as txt _n "{hline 78}"
di as txt "Forecast error variance decomposition"
di as txt "{hline 78}"

cap noisily estimates restore base
cap noisily pvarfevd, step($STEP) porder($ORDER)
if _rc {
    di as error "pvarfevd failed (rc = " _rc "); trying without porder()."
    cap noisily pvarfevd, step($STEP)
}


*==============================================================================*
* 8. ROBUSTNESS GRID
*==============================================================================*
* Every cell reports the two gatekeepers alongside the response, so that a
* specification which fails them can be identified rather than silently
* averaged into the picture. The response reported is the cumulative
* orthogonalised response of FDI to a one-sd terror shock after 4, 8 and 20
* quarters.

capture postclose rob
postfile rob str10 terrvar int(lags ilags) str4 tdopt str14 subsample ///
    double(nobs jstat jdf jp maxmod r4 r8 r20) ///
    using "$TABLES/irf_robustness_${TAG}.dta", replace

di as txt _n "{hline 110}"
di as txt "Robustness grid"
di as txt "{hline 110}"
di as txt %9s "terror" %5s "lag" %5s "ins" %5s "td" %13s "sample" %9s "obs" ///
    %9s "J p" %8s "maxmod" %10s "cum h=4" %10s "cum h=8" %10s "cum h=20"

local grid `" "x_pm|5|7|td|all|insample" "x_pm|8|10|td|all|insample" "x_pm|5|7||all|insample" "x_raw|5|7|td|all|insample" "x_raw|8|10|td|all|insample" "x_pm|5|7|td|longT|insample & T_country>=80" "x_pm|5|7|td|nonzero|insample & terrsum>0" "x_pm|5|7|td|exc_highinc|insample & gdp_lag_usd/pop_lag < 20000" "'

foreach g of local grid {

    tokenize "`g'", parse("|")
    local tv   "`1'"
    local lg   "`3'"
    local il   "`5'"
    local tdo  "`7'"
    local slab "`9'"
    local scnd "`11'"

    local xo   = cond("`tdo'" == "", "exog(`SEAS')", "")
    local nx   = cond("`tdo'" == "", 3, 0)
    local tdl  = cond("`tdo'" == "", "notd", "td")

    cap pvar `tv' y_fdi if `scnd', lags(`lg') instlags(1/`il') `xo' `tdo'
    if _rc {
        di as error "  `tv' l`lg' `tdl' `slab': estimation failed"
        continue
    }

    local nb  = e(N)
    local js  = e(J)
    local jd  = e(J_df)
    local jpv = cond(missing(`js') | missing(`jd') | `jd' <= 0, ., ///
                     chi2tail(`jd', `js'))

    local mm = .
    cap pvarstable
    if !_rc {
        tempname MD
        cap matrix `MD' = r(Modulus)
        if _rc cap matrix `MD' = r(modulus)
        if !_rc {
            local mm = 0
            forvalues rr = 1/`=rowsof(`MD')' {
                forvalues cc = 1/`=colsof(`MD')' {
                    if `MD'[`rr',`cc'] > `mm' & !missing(`MD'[`rr',`cc']) {
                        local mm = `MD'[`rr',`cc']
                    }
                }
            }
        }
    }

    tempname G
    cap mata: pvar_oirf("e(b)", "e(Sigma)", 2, `lg', `nx', 20, (1, 2), "`G'")
    if _rc {
        di as error "  `tv' l`lg' `tdl' `slab': IRF computation failed"
        continue
    }

    local c4 = 0
    local c8 = 0
    local c20 = 0
    forvalues h = 1/21 {
        local c20 = `c20' + `G'[`h', 3]
        if `h' <= 5  local c4  = `c4'  + `G'[`h', 3]
        if `h' <= 9  local c8  = `c8'  + `G'[`h', 3]
    }

    di as txt %9s "`tv'" %5.0f `lg' %5.0f `il' %5s "`tdl'" %13s "`slab'" ///
        %9.0fc `nb' %9.4f `jpv' %8.3f `mm' %10.5f `c4' %10.5f `c8' %10.5f `c20'

    post rob ("`tv'") (`lg') (`il') ("`tdl'") ("`slab'") (`nb') ///
        (`js') (`jd') (`jpv') (`mm') (`c4') (`c8') (`c20')
}
postclose rob

preserve
    use "$TABLES/irf_robustness_${TAG}.dta", clear
    format jstat maxmod r4 r8 r20 %9.4f
    format jp %6.4f
    di as txt _n "Robustness summary"
    list, noobs
    export delimited using "$TABLES/irf_robustness_${TAG}.csv", replace
restore


*==============================================================================*
* 9. HOW TO READ AND REPORT THIS
*==============================================================================*
di as txt _n "{hline 78}"
di as txt "Interpretation"
di as txt "{hline 78}"
di as txt "1. Units. Both variables are inverse hyperbolic sine transforms, so"
di as txt "   a response of -0.05 means roughly a five percent change in the"
di as txt "   FDI-to-GDP ratio, and only away from zero. Near zero the"
di as txt "   semi-elasticity reading breaks down; say so rather than"
di as txt "   quietly reporting percentages."
di as txt ""
di as txt "2. What the shock is. An orthogonalised innovation is the part of"
di as txt "   terror that the history of the system does not predict. It is"
di as txt "   not an exogenous shock. Any omitted driver of both series sits"
di as txt "   inside it, which is why the bivariate system limits what can be"
di as txt "   claimed. Report it as a conditional dynamic association."
di as txt ""
di as txt "3. Bands. The Monte Carlo intervals reflect coefficient"
di as txt "   uncertainty only. They do not cover the choice of lag order,"
di as txt "   sample or terror measure; the grid in section 8 does that."
di as txt ""
di as txt "4. Report together, always: the response, Hansen J with its p"
di as txt "   value, the instrument count, the largest eigenvalue modulus and"
di as txt "   the number of countries and observations. A specification that"
di as txt "   fails a gatekeeper belongs in the table with a flag, not in a"
di as txt "   drawer."
di as txt ""
di as txt "5. The td comparison is a result, not a nuisance. Without time"
di as txt "   demeaning the part 2 Granger tests were strongly significant;"
di as txt "   with it they were marginal. Common global shocks account for"
di as txt "   most of the raw association, and that finding is worth stating"
di as txt "   explicitly."

log close
*==============================================================================*
* END OF PART 3
*==============================================================================*
