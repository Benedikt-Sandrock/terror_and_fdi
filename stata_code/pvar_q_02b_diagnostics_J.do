*==============================================================================*
* pvar_q_02b_diagnostics_J.do
*
* Terrorism and FDI - quarterly Panel VAR
* PART 2b: why does Hansen's J reject?
*
* Part 2 produced a clean result on two fronts (residual correlation ~0.02,
* all eigenvalues well inside the unit circle) and one problem: Hansen's J
* rejects at every lag order, marginally so only at lags(5) with td
* (J = 18.25, df = 8, p = 0.020).
*
* This file tests four candidate explanations against each other:
*
*   A  Lag depth          Is J still falling beyond lag 6? Section 3.
*   B  Zero inflation     61% of x_terr is exactly zero. Does a smoothed or
*                         binary terror measure fix it? Section 4.
*   C  Slope heterogeneity  Pooling 119 countries with identical dynamics.
*                         Subsample splits (5), poolability and Mean Group (7).
*   D  Serial correlation  The mechanism J actually detects, measured directly
*                         on LSDV residuals rather than inferred. Section 6.
*
* Every J p-value is computed as chi2tail(df, J) rather than read from e(),
* because the e() name for the p-value is not present in this pvar release.
*
* Output: output/logs/pvar_q_02b_<tag>.log
*         output/tables/diagJ_lags_<tag>.csv
*         output/tables/diagJ_terror_<tag>.csv
*         output/tables/diagJ_subsamples_<tag>.csv
*         output/tables/diagJ_heterogeneity_<tag>.csv
*
* Stata 18. Required: pvar, pvarstable (Abrigo & Love)
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
global FDIRAW       "fdi_in_pct_qgdp"
global TERRORRAW    "attacks_total"
global SAMPLE       "core"
global MINOBS       28

global MAXLAG       8      // extended from 6 to resolve the non-monotonicity
global REFLAG       5      // reference lag order for sections 4-7
global INSTEXTRA    2      // df of Hansen's J = nvar^2 * INSTEXTRA = 8

global LONGT        60     // minimum T for the country-by-country estimates
global VERYLONGT    80     // panel-length subsample in section 5

global TAG "${TERRORRAW}_${FDIRAW}_${SAMPLE}_min${MINOBS}"

cap log close _all
log using "$LOGS/pvar_q_02b_${TAG}.log", replace text


*==============================================================================*
* 2. LOAD, REBUILD SAMPLE, BUILD VARIANT VARIABLES
*==============================================================================*
use "$DATA/pvar_q_work.dta", clear
xtset id t

cap drop insample n_insample
gen byte insample = s_$SAMPLE
bysort id: egen int n_insample = total(insample)
qui replace insample = 0 if n_insample < $MINOBS
bysort id: egen int T_country = total(insample)

qui count if insample
local nobs = r(N)
qui levelsof id if insample, local(ids)
local ncty = wordcount("`ids'")
di as txt _n "Base sample: " %7.0fc `nobs' " obs, `ncty' countries"

local SEAS "q_2 q_3 q_4"

*--- Terror variants ---------------------------------------------------------*
* x_raw : IHS of the quarterly count            (baseline, 61% zeros)
* x_ma4 : IHS of the rolling 4-quarter sum      (reduces the zero mass)
* x_bin : indicator, any attack this quarter    (removes the count scale)
* x_pm  : IHS of attacks per million people     (removes size heterogeneity)
cap drop x_raw x_ma4 x_bin x_pm
gen double x_raw = asinh($TERRORRAW) if insample

gen double _ma4 = $TERRORRAW + L1.$TERRORRAW + L2.$TERRORRAW + L3.$TERRORRAW ///
    if insample
gen double x_ma4 = asinh(_ma4)

gen double x_bin = ($TERRORRAW > 0) if insample & !missing($TERRORRAW)

gen double _pm = $TERRORRAW / (pop_lag / 1000000) ///
    if insample & pop_lag > 0 & !missing(pop_lag)
gen double x_pm = asinh(_pm)

label var x_raw "IHS(count)"
label var x_ma4 "IHS(4-quarter sum)"
label var x_bin "Any attack (0/1)"
label var x_pm  "IHS(count per million)"

di as txt _n "Zero / mass-point share of each terror variant:"
foreach v in x_raw x_ma4 x_bin x_pm {
    qui count if insample & `v' == 0
    local z = r(N)
    qui count if insample & !missing(`v')
    di as txt "  " %-8s "`v'" ": " %5.1f 100*`z'/r(N) "% at zero"
}

*--- Country-level grouping variables ---------------------------------------*
cap drop gdppc_c terr_c
gen double _gdppc = gdp_lag_usd / pop_lag if insample & pop_lag > 0
bysort id: egen double gdppc_c = mean(_gdppc)
bysort id: egen double terr_c  = mean($TERRORRAW) if insample
bysort id: egen double terr_cm = max(terr_c)
drop terr_c
rename terr_cm terr_c

* Terciles are formed across COUNTRIES, not observations, so that a country
* never appears in two groups.
preserve
    keep if insample
    collapse (first) gdppc_c terr_c, by(id)
    xtile g_inc  = gdppc_c, nq(3)
    xtile g_terr = terr_c,  nq(3)
    keep id g_inc g_terr
    tempfile groups
    save `groups'
restore
merge m:1 id using `groups', nogen keep(master match)

di as txt _n "Countries per group:"
preserve
    keep if insample
    collapse (first) g_inc g_terr, by(id)
    tab g_inc
    tab g_terr
restore


*==============================================================================*
* 2b. HELPER: estimate one PVAR and return its diagnostics
*==============================================================================*
capture program drop pvarj
program define pvarj, rclass
    syntax varlist(min=2) [if], LAGs(integer) ILAgs(integer) ///
        [TIMEdemean EXOGvars(string)]

    local xopt ""
    if "`exogvars'" != "" local xopt "exog(`exogvars')"
    local tdopt ""
    if "`timedemean'" != "" local tdopt "td"

    tempname J Jdf MOD
    scalar `J'   = .
    scalar `Jdf' = .

    cap pvar `varlist' `if', lags(`lags') instlags(1/`ilags') `xopt' `tdopt'
    if _rc {
        return scalar ok = 0
        return scalar rc = _rc
        exit
    }

    scalar `J'   = e(J)
    scalar `Jdf' = e(J_df)
    local Nobs   = e(N)

    * Largest eigenvalue modulus.
    local maxmod = .
    cap pvarstable
    if !_rc {
        cap matrix `MOD' = r(Modulus)
        if _rc cap matrix `MOD' = r(modulus)
        if !_rc {
            local maxmod = 0
            forvalues rr = 1/`=rowsof(`MOD')' {
                forvalues cc = 1/`=colsof(`MOD')' {
                    if `MOD'[`rr',`cc'] > `maxmod' & !missing(`MOD'[`rr',`cc']) {
                        local maxmod = `MOD'[`rr',`cc']
                    }
                }
            }
        }
    }

    return scalar ok     = 1
    return scalar N      = `Nobs'
    return scalar J      = `J'
    return scalar Jdf    = `Jdf'
    return scalar Jp     = cond(missing(`J') | missing(`Jdf') | `Jdf' <= 0, ., ///
                                chi2tail(`Jdf', `J'))
    return scalar maxmod = `maxmod'
end


*==============================================================================*
* 3. DIAGNOSTIC A - DOES J KEEP FALLING WITH MORE LAGS?
*==============================================================================*
* In part 2, J fell monotonically to lag 5 and rose again at lag 6. If the
* problem were simply omitted dynamics, J should decline monotonically until
* the lag structure is adequate. A U shape points elsewhere.

capture postclose dA
postfile dA int(lags ilags) str4 tdopt double(nobs jstat jdf jp maxmod) ///
    using "$TABLES/diagJ_lags_${TAG}.dta", replace

di as txt _n "{hline 78}"
di as txt "A. Lag profile of Hansen's J, extended to $MAXLAG lags"
di as txt "{hline 78}"
di as txt %5s "lags" %6s "td" %10s "obs" %11s "J" %5s "df" %10s "p" %9s "maxmod"

foreach td in "" "timedemean" {
    local tdlab = cond("`td'" == "", "notd", "td")
    local xo    = cond("`td'" == "", "`SEAS'", "")

    forvalues p = 1/$MAXLAG {
        local k = `p' + $INSTEXTRA
        cap pvarj x_raw y_fdi if insample, lags(`p') ilags(`k') ///
            `td' exogvars(`xo')
        if _rc | r(ok) == 0 {
            di as error "  lags(`p') `tdlab': failed"
            continue
        }
        di as txt %5.0f `p' %6s "`tdlab'" %10.0fc r(N) %11.2f r(J) ///
            %5.0f r(Jdf) %10.4f r(Jp) %9.3f r(maxmod)
        post dA (`p') (`k') ("`tdlab'") (r(N)) (r(J)) (r(Jdf)) (r(Jp)) (r(maxmod))
    }
}
postclose dA

preserve
    use "$TABLES/diagJ_lags_${TAG}.dta", clear
    export delimited using "$TABLES/diagJ_lags_${TAG}.csv", replace
restore


*==============================================================================*
* 4. DIAGNOSTIC B - IS THE ZERO MASS THE PROBLEM?
*==============================================================================*
* 61% of x_raw is exactly zero. A linear autoregression on a variable with a
* large mass point produces errors that are neither homoskedastic nor free of
* structure, which can invalidate the moment conditions on its own. If J
* improves sharply for x_ma4 or x_bin, that channel is identified.

capture postclose dB
postfile dB str8 terrvar int lags double(nobs zeroshare jstat jdf jp maxmod) ///
    using "$TABLES/diagJ_terror_${TAG}.dta", replace

di as txt _n "{hline 78}"
di as txt "B. Terror measure and Hansen's J (lags $REFLAG, td)"
di as txt "{hline 78}"
di as txt %9s "variable" %10s "obs" %9s "%zero" %11s "J" %5s "df" %10s "p" %9s "maxmod"

local k = $REFLAG + $INSTEXTRA
foreach v in x_raw x_ma4 x_bin x_pm {

    qui count if insample & `v' == 0
    local z = r(N)
    qui count if insample & !missing(`v')
    local zs = 100 * `z' / r(N)

    cap pvarj `v' y_fdi if insample, lags($REFLAG) ilags(`k') timedemean
    if _rc | r(ok) == 0 {
        di as error "  `v': failed"
        continue
    }
    di as txt %9s "`v'" %10.0fc r(N) %9.1f `zs' %11.2f r(J) ///
        %5.0f r(Jdf) %10.4f r(Jp) %9.3f r(maxmod)
    post dB ("`v'") ($REFLAG) (r(N)) (`zs') (r(J)) (r(Jdf)) (r(Jp)) (r(maxmod))
}
postclose dB

preserve
    use "$TABLES/diagJ_terror_${TAG}.dta", clear
    export delimited using "$TABLES/diagJ_terror_${TAG}.csv", replace
restore


*==============================================================================*
* 5. DIAGNOSTIC C1 - DOES J IMPROVE IN MORE HOMOGENEOUS SUBSAMPLES?
*==============================================================================*
* If pooling heterogeneous dynamics is what breaks the moment conditions, then
* J should improve within groups of similar countries. Note that J also falls
* mechanically with sample size, so read the p-value together with the number
* of observations: a p-value that rises while N falls by a third is weak
* evidence; a p-value that rises sharply on a similar N is strong evidence.

capture postclose dC
postfile dC str14 subsample double(ncty nobs jstat jdf jp maxmod) ///
    using "$TABLES/diagJ_subsamples_${TAG}.dta", replace

di as txt _n "{hline 78}"
di as txt "C1. Subsamples (lags $REFLAG, td, x_raw)"
di as txt "{hline 78}"
di as txt %15s "subsample" %7s "cty" %10s "obs" %11s "J" %5s "df" %10s "p" %9s "maxmod"

local k = $REFLAG + $INSTEXTRA

* Label, condition
local subs `" "all|insample" "inc_low|insample & g_inc==1" "inc_mid|insample & g_inc==2" "inc_high|insample & g_inc==3" "terr_low|insample & g_terr==1" "terr_mid|insample & g_terr==2" "terr_high|insample & g_terr==3" "longT|insample & T_country>=$VERYLONGT" "nonzero_terr|insample & terrsum>0" "'

foreach s of local subs {
    local lab  = substr("`s'", 1, strpos("`s'", "|") - 1)
    local cond = substr("`s'", strpos("`s'", "|") + 1, .)

    qui count if `cond'
    local n_s = r(N)
    if `n_s' < 500 {
        di as error "  `lab': only `n_s' observations, skipped"
        continue
    }
    qui levelsof id if `cond', local(sids)
    local c_s = wordcount("`sids'")

    cap pvarj x_raw y_fdi if `cond', lags($REFLAG) ilags(`k') timedemean
    if _rc | r(ok) == 0 {
        di as error "  `lab': estimation failed"
        continue
    }
    di as txt %15s "`lab'" %7.0f `c_s' %10.0fc r(N) %11.2f r(J) ///
        %5.0f r(Jdf) %10.4f r(Jp) %9.3f r(maxmod)
    post dC ("`lab'") (`c_s') (r(N)) (r(J)) (r(Jdf)) (r(Jp)) (r(maxmod))
}
postclose dC

preserve
    use "$TABLES/diagJ_subsamples_${TAG}.dta", clear
    export delimited using "$TABLES/diagJ_subsamples_${TAG}.csv", replace
restore


*==============================================================================*
* 6. DIAGNOSTIC D - RESIDUAL SERIAL CORRELATION, MEASURED DIRECTLY
*==============================================================================*
* Hansen's J detects a violation but not which one. Lagged instruments are
* valid only if the idiosyncratic errors are serially uncorrelated, so that
* assumption is worth testing on its own rather than inferring it from J.
*
* The pvar suite offers no Arellano-Bond test, so the test is run on LSDV
* residuals: estimate each equation with country and time fixed effects, then
* regress the residual on its own lags with country effects. At T of about 80
* the Nickell bias in the LSDV residuals is small enough for this to be
* informative.

di as txt _n "{hline 78}"
di as txt "D. Serial correlation in LSDV residuals (lags $REFLAG)"
di as txt "{hline 78}"

foreach dv in x_raw y_fdi {
    local other = cond("`dv'" == "x_raw", "y_fdi", "x_raw")

    di as txt _n "--- Equation: `dv' ---"
    cap noisily qui xtreg `dv' L(1/$REFLAG).`dv' L(1/$REFLAG).`other' i.t ///
        if insample, fe
    if _rc {
        di as error "  LSDV estimation failed (rc = " _rc ")"
        continue
    }

    cap drop resid_`dv'
    qui predict double resid_`dv' if e(sample), e

    forvalues j = 1/4 {
        qui xtreg resid_`dv' L`j'.resid_`dv' if insample, fe
        local b  = _b[L`j'.resid_`dv']
        local se = _se[L`j'.resid_`dv']
        local tt = `b' / `se'
        di as txt "  AR(`j') on residuals: b = " %8.4f `b' ///
            "  se = " %7.4f `se' "  t = " %7.2f `tt'
    }
    di as txt "  A coefficient near zero supports the moment conditions."
    di as txt "  Persistent nonzero values mean lagged levels are not valid"
    di as txt "  instruments, whatever the lag order."
}


*==============================================================================*
* 7. DIAGNOSTIC C2 - POOLABILITY AND MEAN GROUP
*==============================================================================*
* The most direct test of slope homogeneity. Country-by-country equations are
* estimated for countries with at least $LONGT quarters, and:
*   (a) an F test compares the pooled residual sum of squares with the sum of
*       the country-specific ones (Chow / poolability);
*   (b) the Mean Group estimate (Pesaran & Smith 1995) is the simple average
*       of the country coefficients, with standard error sd/sqrt(N). Under
*       homogeneity MG and the pooled estimate agree; under heterogeneity the
*       pooled dynamic estimate is inconsistent and MG is not.

di as txt _n "{hline 78}"
di as txt "C2. Poolability and Mean Group, FDI equation, lags $REFLAG"
di as txt "  countries with at least $LONGT quarters"
di as txt "{hline 78}"

qui levelsof id if insample & T_country >= $LONGT, local(longids)
local nlong = wordcount("`longids'")
di as txt "  Countries entering: `nlong'"

* Pooled (restricted) model on exactly the same countries.
tempvar touse
gen byte `touse' = insample & T_country >= $LONGT

qui reg y_fdi L(1/$REFLAG).y_fdi L(1/$REFLAG).x_raw i.id i.t if `touse'
local rss_r = e(rss)
local n_r   = e(N)
local k_r   = e(df_m) + 1

* Unrestricted: separate slopes per country.
local rss_u = 0
local n_u   = 0
local k_u   = 0
local nok   = 0

capture postclose dD
postfile dD int cid double(b_terr1 b_own1 nobs) ///
    using "$TABLES/diagJ_heterogeneity_${TAG}.dta", replace

foreach i of local longids {
    cap qui reg y_fdi L(1/$REFLAG).y_fdi L(1/$REFLAG).x_raw i.t ///
        if `touse' & id == `i'
    if _rc continue
    if e(N) < 3 * (2 * $REFLAG + 1) continue

    local rss_u = `rss_u' + e(rss)
    local n_u   = `n_u' + e(N)
    local k_u   = `k_u' + e(df_m) + 1
    local ++nok

    local b1 = .
    local b2 = .
    cap local b1 = _b[L1.x_raw]
    cap local b2 = _b[L1.y_fdi]
    post dD (`i') (`b1') (`b2') (e(N))
}
postclose dD

di as txt "  Countries with an estimable equation: `nok'"

if `nok' > 10 & `rss_u' > 0 {
    local q     = `k_u' - `k_r'
    local dfden = `n_u' - `k_u'
    if `q' > 0 & `dfden' > 0 {
        local F = ((`rss_r' - `rss_u') / `q') / (`rss_u' / `dfden')
        local pF = Ftail(`q', `dfden', `F')
        di as txt _n "  Poolability F(" `q' ", " `dfden' ") = " %8.3f `F' ///
            "   p = " %8.6f `pF'
        di as txt "  H0: identical slopes across countries."
    }
}

preserve
    use "$TABLES/diagJ_heterogeneity_${TAG}.dta", clear
    di as txt _n "  Distribution of the country-specific L1 coefficients:"
    sum b_terr1 b_own1, detail

    qui sum b_terr1
    local mg   = r(mean)
    local mgse = r(sd) / sqrt(r(N))
    di as txt _n "  Mean Group estimate, L1.terror in the FDI equation:"
    di as txt "    MG  = " %8.4f `mg' "   se = " %7.4f `mgse' ///
        "   t = " %6.2f `mg'/`mgse'
    di as txt "  Compare with the pooled GMM coefficient from part 2."
    di as txt "  A large gap is evidence of heterogeneity bias, not noise."

    export delimited using "$TABLES/diagJ_heterogeneity_${TAG}.csv", replace
restore


*==============================================================================*
* 8. READING GUIDE
*==============================================================================*
di as txt _n "{hline 78}"
di as txt "How to read the four diagnostics together"
di as txt "{hline 78}"
di as txt "A  If J keeps falling to lag 7 or 8 and becomes insignificant, the"
di as txt "   problem was omitted dynamics and the fix is simply more lags."
di as txt "   If it stays U shaped, it is not a lag-length problem."
di as txt ""
di as txt "B  If x_ma4 or x_bin turn J acceptable while x_raw does not, the"
di as txt "   zero mass in the quarterly count is the binding problem. That"
di as txt "   would argue for the smoothed measure as the main specification"
di as txt "   and would apply with even more force to business_target_top3."
di as txt ""
di as txt "C1 If J improves within income or terror-intensity terciles on a"
di as txt "   comparable number of observations, pooling is the problem."
di as txt "   Watch the sample sizes: J falls with N by construction."
di as txt ""
di as txt "D  A clearly nonzero AR coefficient on the residuals invalidates"
di as txt "   lagged instruments directly, independently of J."
di as txt ""
di as txt "C2 A rejected poolability test plus a Mean Group estimate far from"
di as txt "   the pooled one is the strongest evidence for heterogeneity. In"
di as txt "   that case the way forward is not a better instrument set but a"
di as txt "   different estimator: Mean Group, or fixed-effects local"
di as txt "   projections, which sidestep the instrument problem entirely."

log close
*==============================================================================*
* END OF PART 2b
*==============================================================================*
