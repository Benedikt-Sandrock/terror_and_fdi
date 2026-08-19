*==============================================================================*
* pvar_q_02_estimation.do
*
* Terrorism and FDI - quarterly Panel VAR
* PART 2 of 3: lag selection, baseline estimation, stability, Granger, Hansen J
*
* Runs on the working file produced by pvar_q_01_setup_diagnostics_v3.do.
*
* Specification decisions carried over from part 1:
*   - Both y_fdi and x_terr are stationary in levels (IPS, Fisher and CIPS all
*     reject a unit root at any conventional level, with a trend included and
*     therefore in the conservative specification). The PVAR is estimated in
*     LEVELS; no differencing.
*   - Cross-sectional dependence is strong in levels but essentially absent in
*     first differences, so the common component is a level/trend factor. The
*     td option (time demeaning) is the right instrument against it and is
*     reported alongside the no-td specification.
*
* Output: output/logs/pvar_q_02_<tag>.log
*         output/tables/lagsel_<tag>.csv       screening over lag orders
*         output/tables/baseline_<tag>.csv     baseline coefficients
*         output/tables/gatekeepers_<tag>.csv  stability, J, Granger, residuals
*         output/estimates/pvar_<tag>_l<p>_<td>.ster   for the IRFs in part 3
*
* Stata 18. Required: pvar, pvarsoc, pvarstable, pvargranger (Abrigo & Love)
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
global ESTS     "$OUT/estimates"

cap mkdir "$OUT"
cap mkdir "$LOGS"
cap mkdir "$TABLES"
cap mkdir "$ESTS"


*==============================================================================*
* 1. SWITCHES
*==============================================================================*
* These must match part 1 for the tag to line up. MINOBS may differ: the
* estimation sample is rebuilt from the stored s_* flags below.

global FDIRAW       "fdi_in_pct_qgdp"
global TERRORRAW    "attacks_total"
global TERRORSCALE  "raw"
global TERRORSMOOTH "none"
global SAMPLE       "core"

*--- Minimum series length. 28 is the baseline; 20 and 40 are robustness. ----*
* Rationale: the Nickell bias is of order (1+rho)/(T-1), so it is negligible
* at T = 100 but around eight percentage points at T = 20. Raising the floor
* from 20 to 28 costs four countries here.
global MINOBS       28

*--- Lag structure -----------------------------------------------------------*
global MAXLAG       6      // upper bound screened by pvarsoc and the lag loop
global BASELAG      0      // 0 = take the MMSC-BIC choice; otherwise force it

*--- Instrument depth --------------------------------------------------------*
* With IV-style (non-gmmstyle) instruments the instrument count is
*   #variables x #instrument lags,
* and the number of parameters per equation is #variables x #lags.
* Overidentification therefore requires INSTEXTRA >= 1. Each additional
* instrument lag buys two degrees of freedom for Hansen's J and costs nothing
* in instrument proliferation, because the count does not grow with T.
global INSTEXTRA    2      // instlags(1/(lags + INSTEXTRA))

*--- Demonstrate instrument proliferation with gmmstyle? (0/1) --------------*
* gmmstyle builds the Holtz-Eakin/Arellano-Bond matrix whose size grows with
* T. At T ~ 85 this produces thousands of instruments and destroys the
* informativeness of Hansen's J. Set to 1 once, to see the effect, then leave
* it off.
global SHOWGMMSTYLE 0

*--- Tag ---------------------------------------------------------------------*
global TAG "${TERRORRAW}_${FDIRAW}_${SAMPLE}"
if "$TERRORSMOOTH" != "none" global TAG "${TAG}_$TERRORSMOOTH"
if "$TERRORSCALE"  != "raw"  global TAG "${TAG}_$TERRORSCALE"
global TAG "${TAG}_min$MINOBS"

cap log close _all
log using "$LOGS/pvar_q_02_${TAG}.log", replace text


*==============================================================================*
* 2. LOAD AND REBUILD THE SAMPLE
*==============================================================================*
use "$DATA/pvar_q_work.dta", clear
xtset id t

* Rebuild insample so that MINOBS can be changed without rerunning part 1.
cap drop insample n_insample
gen byte insample = s_$SAMPLE
bysort id: egen int n_insample = total(insample)
qui replace insample = 0 if n_insample < $MINOBS

qui count if insample
local nobs = r(N)
qui levelsof id if insample, local(ids)
local ncty = wordcount("`ids'")
di as txt _n "Estimation sample (${SAMPLE}, min $MINOBS quarters): " ///
    %7.0fc `nobs' " obs, `ncty' countries"

* Variables that enter the system, in Cholesky order for part 3:
* terror first, FDI second.
local SYS "x_terr y_fdi"

* Seasonal dummies for the no-td specification. q_1 is the reference category.
* Under td the cross-sectional mean is removed at every t, which already
* absorbs all common seasonal variation, so the dummies are dropped there.
local SEAS "q_2 q_3 q_4"


*==============================================================================*
* 3. LAG ORDER SELECTION
*==============================================================================*
* pvarsoc reports the Andrews-Lu moment and model selection criteria
* (MMSC-BIC, MMSC-AIC, MMSC-HQIC) together with Hansen's J. The criteria trade
* off fit against the number of moment conditions, which is why they are
* preferred to plain AIC/BIC in a GMM setting.
*
* The comparison is only valid on a common sample, so the criteria are
* computed on the observations available at MAXLAG.

di as txt _n "{hline 78}"
di as txt "Lag order selection (pvarsoc, maxlag $MAXLAG)"
di as txt "{hline 78}"

local instmax = $MAXLAG + $INSTEXTRA

cap noisily pvarsoc `SYS' if insample, maxlag($MAXLAG) ///
    pvaropts(instlags(1/`instmax'))
if _rc {
    di as error "pvarsoc with maxlag() failed (rc = " _rc "); trying maxlags()."
    cap noisily pvarsoc `SYS' if insample, maxlags($MAXLAG) ///
        pvaropts(instlags(1/`instmax'))
}
if _rc {
    di as error "pvarsoc failed. The manual screen in section 4 still runs and"
    di as error "provides the information needed to choose a lag order."
}


*==============================================================================*
* 4. MANUAL SCREEN OVER LAG ORDERS
*==============================================================================*
* pvarsoc reports fit criteria but not stability. Both gatekeepers matter, so
* every lag order is estimated and the eigenvalue modulus, Hansen's J, the
* implied instrument count and the sample size are collected side by side.
*
* Reading guide:
*   max modulus  < 1 required; anything above about 0.95 means the system is
*                near-integrated and the impulse responses will be imprecise.
*   Hansen J p   a value in roughly 0.10-0.25 is healthy. A p-value near 1.00
*                signals instrument proliferation, not a well-specified model.
*   instruments  should stay far below the number of countries.

capture postclose lagsel
postfile lagsel int(lags instlag_max) str4 tdopt ///
    double(nobs ncty jstat jdf jp maxmod nparam ninst) ///
    using "$TABLES/lagsel_${TAG}.dta", replace

foreach td in "" "td" {

    local tdlab = cond("`td'" == "", "notd", "td")
    local xopt  = cond("`td'" == "", "exog(`SEAS')", "")

    di as txt _n "{hline 78}"
    di as txt "Lag screen, time demeaning: `tdlab'"
    di as txt "{hline 78}"

    forvalues p = 1/$MAXLAG {

        local k = `p' + $INSTEXTRA

        local jstat  = .
        local jdf    = .
        local jp     = .
        local maxmod = .
        local nobs_p = .
        local ncty_p = .

        cap noisily pvar `SYS' if insample, lags(`p') instlags(1/`k') ///
            `xopt' `td'

        if _rc {
            di as error "  lags(`p'), `tdlab': pvar failed (rc = " _rc ")"
        }
        else {
            local nobs_p = e(N)
            local ncty_p = e(N_g)
            foreach nm in J j {
                if missing(`jstat') local jstat = e(`nm')
            }
            foreach nm in J_df j_df Jdf {
                if missing(`jdf') local jdf = e(`nm')
            }
            foreach nm in J_pvalue jp J_p {
                if missing(`jp') local jp = e(`nm')
            }

            * Eigenvalue stability.
            cap noisily pvarstable
            if !_rc {
                tempname MOD
                cap matrix `MOD' = r(Modulus)
                if _rc cap matrix `MOD' = r(modulus)
                if !_rc {
                    local maxmod = 0
                    forvalues rr = 1/`=rowsof(`MOD')' {
                        forvalues cc = 1/`=colsof(`MOD')' {
                            if `MOD'[`rr', `cc'] > `maxmod' & ///
                               !missing(`MOD'[`rr', `cc']) {
                                local maxmod = `MOD'[`rr', `cc']
                            }
                        }
                    }
                }
            }
        }

        * Parameters and instruments per equation under IV-style instruments.
        local nvar   = wordcount("`SYS'")
        local nparam = `nvar' * `p' + cond("`td'" == "", wordcount("`SEAS'"), 0)
        local ninst  = `nvar' * `k' + cond("`td'" == "", wordcount("`SEAS'"), 0)

        di as txt "  lags(`p') instlags(1/`k') `tdlab': " ///
            "obs = " %7.0fc `nobs_p' ///
            ", maxmod = " %5.3f `maxmod' ///
            ", J p = " %5.3f `jp' ///
            ", inst/eq = " `ninst'

        post lagsel (`p') (`k') ("`tdlab'") (`nobs_p') (`ncty_p') ///
            (`jstat') (`jdf') (`jp') (`maxmod') (`nparam') (`ninst')
    }
}
postclose lagsel

preserve
    use "$TABLES/lagsel_${TAG}.dta", clear
    format jstat maxmod %9.3f
    format jp %6.3f
    di as txt _n "{hline 78}"
    di as txt "Lag screen summary"
    di as txt "{hline 78}"
    list lags instlag_max tdopt nobs ncty maxmod jstat jdf jp ninst, ///
        noobs sepby(tdopt)
    export delimited using "$TABLES/lagsel_${TAG}.csv", replace

    * Suggest a lag order: smallest p that is stable and whose J is not
    * rejected, preferring the td specification.
    qui gen byte ok = (maxmod < 0.98) & (jp > 0.05) & !missing(jp)
    qui count if ok & tdopt == "td"
    if r(N) > 0 {
        qui sum lags if ok & tdopt == "td"
        global SUGGESTLAG = r(min)
    }
    else {
        global SUGGESTLAG = 2
        di as error "No lag order passes both gatekeepers under td;"
        di as error "falling back to lags(2). Inspect the table above."
    }
    di as txt _n "Suggested lag order (smallest stable, J not rejected): " ///
        "$SUGGESTLAG"
restore

if $BASELAG > 0 {
    global P = $BASELAG
    di as txt "Lag order forced by BASELAG: $P"
}
else {
    global P = $SUGGESTLAG
    di as txt "Lag order taken from the screen: $P"
}
global K = $P + $INSTEXTRA


*==============================================================================*
* 5. BASELINE ESTIMATION
*==============================================================================*
* Estimated in levels, Helmert-transformed (forward orthogonal deviations,
* the pvar default). FOD is preferred to first differencing here because it
* leaves the transformed errors serially uncorrelated and, with the four
* internal gaps in this panel, destroys one observation per gap rather than
* two.

capture postclose gate
postfile gate str4 tdopt double(nobs ncty jstat jdf jp maxmod resid_corr) ///
    str24 note using "$TABLES/gatekeepers_${TAG}.dta", replace

foreach td in "" "td" {

    local tdlab = cond("`td'" == "", "notd", "td")
    local xopt  = cond("`td'" == "", "exog(`SEAS')", "")

    di as txt _n "{hline 78}"
    di as txt "BASELINE PVAR: lags($P), instlags(1/$K), `tdlab'"
    di as txt "  Cholesky order for part 3: `SYS'  (terror first)"
    di as txt "{hline 78}"

    cap noisily pvar `SYS' if insample, lags($P) instlags(1/$K) `xopt' `td'
    if _rc {
        di as error "Baseline estimation failed (rc = " _rc "); skipping `tdlab'."
        continue
    }

    local nobs_b = e(N)
    local ncty_b = e(N_g)
    local jstat  = .
    local jdf    = .
    local jp     = .
    foreach nm in J j {
        if missing(`jstat') local jstat = e(`nm')
    }
    foreach nm in J_df j_df Jdf {
        if missing(`jdf') local jdf = e(`nm')
    }
    foreach nm in J_pvalue jp J_p {
        if missing(`jp') local jp = e(`nm')
    }

    * Store for the impulse responses in part 3.
    estimates store pvar_`tdlab'
    cap estimates save "$ESTS/pvar_${TAG}_l${P}_`tdlab'.ster", replace

    *--- Gatekeeper 1: eigenvalue stability ---------------------------------*
    di as txt _n "--- Eigenvalue stability ---"
    local maxmod = .
    cap noisily pvarstable
    if !_rc {
        tempname MOD
        cap matrix `MOD' = r(Modulus)
        if _rc cap matrix `MOD' = r(modulus)
        if !_rc {
            local maxmod = 0
            forvalues rr = 1/`=rowsof(`MOD')' {
                forvalues cc = 1/`=colsof(`MOD')' {
                    if `MOD'[`rr', `cc'] > `maxmod' & !missing(`MOD'[`rr', `cc']) {
                        local maxmod = `MOD'[`rr', `cc']
                    }
                }
            }
        }
    }
    if !missing(`maxmod') & `maxmod' > 0 & `maxmod' < 1 {
        local halflife = ln(0.5) / ln(`maxmod')
        di as txt "  Largest modulus: " %6.4f `maxmod'
        di as txt "  Implied half-life of the most persistent root: " ///
            %5.1f `halflife' " quarters"
        if `maxmod' > 0.95 {
            di as error "  Formally stable but near-integrated: the impulse"
            di as error "  response bands will be wide and asymmetric."
        }
    }

    *--- Gatekeeper 2: Hansen J ---------------------------------------------*
    di as txt _n "--- Overidentification ---"
    di as txt "  Hansen J = " %8.3f `jstat' "  df = " `jdf' "  p = " %6.3f `jp'
    local nvar  = wordcount("`SYS'")
    local ninst = `nvar' * $K + cond("`td'" == "", wordcount("`SEAS'"), 0)
    di as txt "  Instruments per equation: " `ninst' ///
        "   Countries: " `ncty_b'
    if !missing(`jp') {
        if `jp' > 0.25 {
            di as error "  J p-value above 0.25: check the instrument count"
            di as error "  before reading this as evidence of validity."
        }
        if `jp' < 0.05 {
            di as error "  J rejects. Possible causes, in order of plausibility:"
            di as error "   (a) an omitted, serially correlated determinant of"
            di as error "       FDI sitting in the error term;"
            di as error "   (b) too few lags, leaving serial correlation;"
            di as error "   (c) genuinely invalid instruments."
        }
    }

    *--- Granger causality ---------------------------------------------------*
    di as txt _n "--- Granger causality (Wald tests on the lag blocks) ---"
    cap noisily pvargranger

    *--- Residual correlation: does the Cholesky ordering matter? -----------*
    * If the reduced-form residuals are close to uncorrelated, A is close to
    * diagonal and the ordering is nearly irrelevant. That is the cleanest
    * defence of the recursive identification used in part 3.
    local rcorr = .
    tempname SIG
    cap matrix `SIG' = e(Sigma)
    if !_rc {
        if rowsof(`SIG') >= 2 {
            local s11 = `SIG'[1,1]
            local s22 = `SIG'[2,2]
            local s12 = `SIG'[1,2]
            if `s11' > 0 & `s22' > 0 {
                local rcorr = `s12' / sqrt(`s11' * `s22')
            }
        }
    }
    di as txt _n "--- Reduced-form residual correlation ---"
    if !missing(`rcorr') {
        di as txt "  corr(e_terror, e_fdi) = " %6.3f `rcorr'
        if abs(`rcorr') < 0.10 {
            di as txt "  Small: the Cholesky ordering should barely matter."
            di as txt "  Verify this in part 3 by reversing porder()."
        }
        else {
            di as error "  Non-trivial: the impulse responses will depend on the"
            di as error "  ordering. Both orderings must be reported."
        }
    }
    else {
        di as txt "  e(Sigma) not available; compute it from the residuals."
    }

    post gate ("`tdlab'") (`nobs_b') (`ncty_b') (`jstat') (`jdf') (`jp') ///
        (`maxmod') (`rcorr') ("lags=$P instlags=1/$K")
}
postclose gate

preserve
    use "$TABLES/gatekeepers_${TAG}.dta", clear
    format jstat maxmod resid_corr %9.4f
    format jp %6.3f
    di as txt _n "{hline 78}"
    di as txt "Gatekeeper summary"
    di as txt "{hline 78}"
    list, noobs
    export delimited using "$TABLES/gatekeepers_${TAG}.csv", replace
restore


*==============================================================================*
* 6. HOW MUCH DOES GMM ACTUALLY BUY? GMM VERSUS WITHIN
*==============================================================================*
* The textbook case for GMM is the Nickell bias, which is of order
* (1+rho)/(T-1). At the average T of this panel that is on the order of one to
* two percentage points, so the two estimators should agree closely. If they
* do, the identification is not doing heavy lifting and the results are robust
* to the estimator. If they diverge, the first thing to check is the
* instrument count.

di as txt _n "{hline 78}"
di as txt "GMM versus within: coefficient on the first lag of the other variable"
di as txt "{hline 78}"

* GMM values from the stored td specification.
cap estimates restore pvar_td
if !_rc {
    di as txt _n "PVAR (GMM, Helmert, td), lags($P):"
    matrix b_gmm = e(b)
    matrix list b_gmm, format(%9.4f) title("GMM coefficients")
}

* Within counterparts, one equation at a time, with country and time effects.
di as txt _n "Within (xtreg, fe) counterparts with time dummies:"
foreach dv in x_terr y_fdi {
    local other = cond("`dv'" == "x_terr", "y_fdi", "x_terr")
    di as txt _n "  Equation: `dv'"
    cap noisily xtreg `dv' L(1/$P).`dv' L(1/$P).`other' i.t if insample, fe
    if !_rc {
        di as txt "    L1.`other' = " %9.4f _b[L1.`other'] ///
            "  (se " %7.4f _se[L1.`other'] ")"
    }
}

di as txt _n "Compare the L1 cross-coefficients above with the GMM matrix."
di as txt "Close agreement means the estimator choice is not driving results."


*==============================================================================*
* 7. OPTIONAL: WHAT GMMSTYLE DOES TO HANSEN'S J
*==============================================================================*
if $SHOWGMMSTYLE == 1 {
    di as txt _n "{hline 78}"
    di as txt "Demonstration: gmmstyle instruments at T of roughly 85"
    di as txt "{hline 78}"
    di as txt "gmmstyle builds an instrument matrix whose column count grows"
    di as txt "with T. Watch the Hansen J degrees of freedom and p-value."

    cap noisily pvar `SYS' if insample, lags($P) instlags(1/$K) gmmstyle td
    if !_rc {
        local jp2 = .
        foreach nm in J_pvalue jp J_p {
            if missing(`jp2') local jp2 = e(`nm')
        }
        local jdf2 = .
        foreach nm in J_df j_df Jdf {
            if missing(`jdf2') local jdf2 = e(`nm')
        }
        di as txt _n "  gmmstyle: J df = " `jdf2' ", p = " %6.4f `jp2'
        di as txt "  Compare with the baseline above. A p-value that jumps"
        di as txt "  towards 1.00 is the proliferation problem, not a better"
        di as txt "  specification."
    }
}


*==============================================================================*
* 8. WHAT TO CHECK BEFORE MOVING TO PART 3
*==============================================================================*
di as txt _n "{hline 78}"
di as txt "Checklist"
di as txt "{hline 78}"
di as txt "1. Does the chosen lag order pass both gatekeepers under td AND"
di as txt "   without td? If only one passes, that asymmetry is a result and"
di as txt "   needs discussing, not hiding."
di as txt "2. Is the largest modulus comfortably below one? Read the implied"
di as txt "   half-life and ask whether it is economically plausible."
di as txt "3. Is the J p-value in a healthy range with an instrument count"
di as txt "   well below the number of countries?"
di as txt "4. Is the residual correlation small? If so, the Cholesky ordering"
di as txt "   is nearly innocuous and part 3 can say so with evidence."
di as txt "5. Do GMM and within agree? If yes, say so explicitly; it is a"
di as txt "   strong robustness statement at this panel length."

log close
*==============================================================================*
* END OF PART 2
*==============================================================================*
