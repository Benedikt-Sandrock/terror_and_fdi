*==============================================================================*
* pvar_q_02b_diagnostics_J.do      VERSION 2
*
* Terrorism and FDI - quarterly Panel VAR
* PART 2b: why does Hansen's J reject?
*
* Changes against version 1:
*   - FIXED: merge m:1 leaves the data sorted by id only, so the time-series
*     operators in sections 6 and 7 aborted with "not sorted" (r 5). xtset is
*     now reissued after the merge and again before each section that uses
*     lag operators. pvar was unaffected because it sorts internally.
*   - FIXED: the country-by-country regressions in section 7 included i.t,
*     which is perfectly collinear within a single country. Both the pooled
*     and the country equations now use seasonal dummies instead, so that the
*     poolability test isolates slope homogeneity.
*   - EXTENDED: the residual autocorrelation test now runs to lag 8. The J
*     profile from section 3 is good at lags 4, 5 and 8 and bad at 6 and 7,
*     which suggests country-specific seasonality (period 4) in the errors.
*     Lags 4 and 8 are the ones that would reveal it.
*   - ADDED section 3b: the lag profile for the per-capita terror variable,
*     which was the only variant to pass Hansen's J in version 1
*     (J = 11.51, df = 8, p = 0.174 on the full sample).
*   - ADDED: SKIPDONE lets you jump straight to the sections that failed.
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

global MAXLAG       8
global REFLAG       5
global INSTEXTRA    2

global LONGT        60
global VERYLONGT    80

*--- Set to 1 to skip sections 3-5, which already ran in version 1 ----------*
global SKIPDONE     0

*--- Which terror variable the heterogeneity sections use --------------------*
* x_raw was the version-1 default. x_pm is the variant that passes J and is
* therefore the more relevant one to test for heterogeneity.
global HETVAR       "x_pm"

global TAG "${TERRORRAW}_${FDIRAW}_${SAMPLE}_min${MINOBS}"

cap log close _all
log using "$LOGS/pvar_q_02b_v2_${TAG}.log", replace text


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

xtset id t          // bysort/egen reorder the data

qui count if insample
local nobs = r(N)
qui levelsof id if insample, local(ids)
di as txt _n "Base sample: " %7.0fc `nobs' " obs, " wordcount("`ids'") " countries"

local SEAS "q_2 q_3 q_4"

*--- Terror variants ---------------------------------------------------------*
cap drop x_raw x_ma4 x_bin x_pm _ma4 _pm
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

*--- Country-level grouping variables ---------------------------------------*
cap drop gdppc_c terr_c _gdppc
gen double _gdppc = gdp_lag_usd / pop_lag if insample & pop_lag > 0
bysort id: egen double gdppc_c = mean(_gdppc)
bysort id: egen double _tc     = mean($TERRORRAW) if insample
bysort id: egen double terr_c  = max(_tc)
drop _tc

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

* The merge leaves the data sorted by id only. Every lag operator below needs
* id t, so restore the panel sort here. This was the version-1 abort.
xtset id t


*==============================================================================*
* 2b. HELPER
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
* 3. DIAGNOSTIC A - LAG PROFILE  (skipped when SKIPDONE = 1)
*==============================================================================*
if $SKIPDONE == 0 {

    capture postclose dA
    postfile dA str8 terrvar int(lags ilags) str4 tdopt ///
        double(nobs jstat jdf jp maxmod) ///
        using "$TABLES/diagJ_lags_${TAG}.dta", replace

    di as txt _n "{hline 90}"
    di as txt "A. Lag profile of Hansen's J, x_raw and x_pm, up to $MAXLAG lags"
    di as txt "{hline 90}"
    di as txt %9s "terror" %6s "lags" %6s "td" %10s "obs" %11s "J" ///
        %5s "df" %10s "p" %9s "maxmod"

    foreach tv in x_raw x_pm {
        foreach td in "" "timedemean" {
            local tdlab = cond("`td'" == "", "notd", "td")
            local xo    = cond("`td'" == "", "`SEAS'", "")

            forvalues p = 1/$MAXLAG {
                local k = `p' + $INSTEXTRA
                cap pvarj `tv' y_fdi if insample, lags(`p') ilags(`k') ///
                    `td' exogvars(`xo')
                if _rc | r(ok) == 0 {
                    di as error "  `tv' lags(`p') `tdlab': failed"
                    continue
                }
                di as txt %9s "`tv'" %6.0f `p' %6s "`tdlab'" %10.0fc r(N) ///
                    %11.2f r(J) %5.0f r(Jdf) %10.4f r(Jp) %9.3f r(maxmod)
                post dA ("`tv'") (`p') (`k') ("`tdlab'") (r(N)) (r(J)) ///
                    (r(Jdf)) (r(Jp)) (r(maxmod))
            }
        }
    }
    postclose dA

    preserve
        use "$TABLES/diagJ_lags_${TAG}.dta", clear
        export delimited using "$TABLES/diagJ_lags_${TAG}.csv", replace
    restore

    di as txt _n "Reading: a monotone decline means the problem was omitted"
    di as txt "dynamics. An alternating pattern that is good at lags 4 and 8"
    di as txt "and bad at 6 and 7 points to annual periodicity in the errors,"
    di as txt "which section 6 tests directly."


*==============================================================================*
* 4. DIAGNOSTIC B - TERROR MEASURE
*==============================================================================*
    capture postclose dB
    postfile dB str8 terrvar int lags double(nobs zeroshare jstat jdf jp maxmod) ///
        using "$TABLES/diagJ_terror_${TAG}.dta", replace

    di as txt _n "{hline 78}"
    di as txt "B. Terror measure and Hansen's J (lags $REFLAG, td)"
    di as txt "{hline 78}"
    di as txt %9s "variable" %10s "obs" %9s "%zero" %11s "J" %5s "df" ///
        %10s "p" %9s "maxmod"

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
* 5. DIAGNOSTIC C1 - SUBSAMPLES
*==============================================================================*
* Hansen's J scales roughly with N for a given degree of misspecification, so
* a smaller subsample mechanically produces a smaller J. The column
* "J/expected" below divides the subsample J by the value implied by pure
* sample-size scaling from the full sample. Only a ratio well below one is
* evidence that the subsample is better specified.

    capture postclose dC
    postfile dC str14 subsample str8 terrvar ///
        double(ncty nobs jstat jdf jp maxmod) ///
        using "$TABLES/diagJ_subsamples_${TAG}.dta", replace

    di as txt _n "{hline 95}"
    di as txt "C1. Subsamples (lags $REFLAG, td), both terror variants"
    di as txt "{hline 95}"
    di as txt %15s "subsample" %9s "terror" %7s "cty" %10s "obs" %11s "J" ///
        %5s "df" %10s "p" %12s "J/expected"

    local k = $REFLAG + $INSTEXTRA
    local subs `" "all|insample" "inc_low|insample & g_inc==1" "inc_mid|insample & g_inc==2" "inc_high|insample & g_inc==3" "terr_low|insample & g_terr==1" "terr_mid|insample & g_terr==2" "terr_high|insample & g_terr==3" "longT|insample & T_country>=$VERYLONGT" "nonzero_terr|insample & terrsum>0" "'

    foreach tv in x_raw x_pm {

        * Full-sample benchmark for this terror variant.
        cap pvarj `tv' y_fdi if insample, lags($REFLAG) ilags(`k') timedemean
        local Jfull = r(J)
        local Nfull = r(N)

        foreach s of local subs {
            local lab  = substr("`s'", 1, strpos("`s'", "|") - 1)
            local cond = substr("`s'", strpos("`s'", "|") + 1, .)

            qui count if `cond'
            if r(N) < 500 continue
            qui levelsof id if `cond', local(sids)
            local c_s = wordcount("`sids'")

            cap pvarj `tv' y_fdi if `cond', lags($REFLAG) ilags(`k') timedemean
            if _rc | r(ok) == 0 {
                di as error "  `lab' `tv': estimation failed"
                continue
            }
            local ratio = .
            if `Jfull' > 0 & `Nfull' > 0 {
                local ratio = r(J) / (`Jfull' * r(N) / `Nfull')
            }
            di as txt %15s "`lab'" %9s "`tv'" %7.0f `c_s' %10.0fc r(N) ///
                %11.2f r(J) %5.0f r(Jdf) %10.4f r(Jp) %12.2f `ratio'
            post dC ("`lab'") ("`tv'") (`c_s') (r(N)) (r(J)) (r(Jdf)) ///
                (r(Jp)) (r(maxmod))
        }
    }
    postclose dC

    preserve
        use "$TABLES/diagJ_subsamples_${TAG}.dta", clear
        export delimited using "$TABLES/diagJ_subsamples_${TAG}.csv", replace
    restore
}


*==============================================================================*
* 6. DIAGNOSTIC D - RESIDUAL SERIAL CORRELATION, TO LAG 8
*==============================================================================*
* Lagged levels are valid instruments only if the idiosyncratic errors are
* serially uncorrelated. The pvar suite offers no Arellano-Bond test, so the
* assumption is tested directly on LSDV residuals. At T of about 80 the
* Nickell bias in those residuals is small enough for this to be informative.
*
* The test runs to lag 8 on purpose: the J profile is good at lags 4, 5 and 8
* and bad at 6 and 7. If country-specific seasonality is the cause, the
* residual autocorrelation should spike at lags 4 and 8.

xtset id t

di as txt _n "{hline 78}"
di as txt "D. Serial correlation in LSDV residuals (equation lags $REFLAG)"
di as txt "   Terror variable: $HETVAR"
di as txt "{hline 78}"

foreach dv in $HETVAR y_fdi {
    local other = cond("`dv'" == "y_fdi", "$HETVAR", "y_fdi")

    di as txt _n "--- Equation: `dv'  (other variable: `other') ---"

    cap qui xtreg `dv' L(1/$REFLAG).`dv' L(1/$REFLAG).`other' i.t ///
        if insample, fe
    if _rc {
        di as error "  LSDV estimation failed (rc = " _rc ")"
        continue
    }

    cap drop resid_e
    qui predict double resid_e if e(sample), e
    xtset id t

    di as txt "   lag        b         se          t"
    forvalues j = 1/8 {
        cap qui xtreg resid_e L`j'.resid_e if insample, fe
        if _rc continue
        local b  = _b[L`j'.resid_e]
        local se = _se[L`j'.resid_e]
        di as txt %6.0f `j' %10.4f `b' %11.4f `se' %11.2f `b'/`se'
    }
    cap drop resid_e

    di as txt "   Coefficients near zero support the moment conditions."
    di as txt "   Spikes at lags 4 and 8 would indicate country-specific"
    di as txt "   seasonality that time demeaning cannot remove."
}


*==============================================================================*
* 7. DIAGNOSTIC C2 - POOLABILITY AND MEAN GROUP
*==============================================================================*
* Both the pooled and the country-specific equations use seasonal dummies
* rather than full time dummies, because i.t is collinear within a single
* country. The test therefore isolates slope homogeneity and does not control
* for common time shocks; read it together with the td results above.

xtset id t

di as txt _n "{hline 78}"
di as txt "C2. Poolability and Mean Group, FDI equation, lags $REFLAG"
di as txt "    terror variable: $HETVAR, countries with >= $LONGT quarters"
di as txt "{hline 78}"

tempvar touse
gen byte `touse' = insample & T_country >= $LONGT & !missing($HETVAR)

qui levelsof id if `touse', local(longids)
di as txt "  Countries entering: " wordcount("`longids'")

* Restricted: common slopes, country fixed effects, seasonal dummies.
cap qui reg y_fdi L(1/$REFLAG).y_fdi L(1/$REFLAG).$HETVAR `SEAS' i.id if `touse'
if _rc {
    di as error "  Pooled regression failed (rc = " _rc ")"
}
else {
    local rss_r = e(rss)
    local n_r   = e(N)
    local k_r   = e(df_m) + 1
    di as txt "  Pooled RSS = " %12.3f `rss_r' "  on " %7.0fc `n_r' " obs, " ///
        `k_r' " parameters"

    * Unrestricted: country-specific slopes.
    local rss_u = 0
    local n_u   = 0
    local k_u   = 0
    local nok   = 0

    capture postclose dD
    postfile dD int cid double(b_terr1 b_own1 nobs) ///
        using "$TABLES/diagJ_heterogeneity_${TAG}.dta", replace

    foreach i of local longids {
        cap qui reg y_fdi L(1/$REFLAG).y_fdi L(1/$REFLAG).$HETVAR `SEAS' ///
            if `touse' & id == `i'
        if _rc continue
        if e(N) < 3 * (2 * $REFLAG + 4) continue

        local rss_u = `rss_u' + e(rss)
        local n_u   = `n_u'   + e(N)
        local k_u   = `k_u'   + e(df_m) + 1
        local ++nok

        local b1 = .
        local b2 = .
        cap local b1 = _b[L1.$HETVAR]
        cap local b2 = _b[L1.y_fdi]
        post dD (`i') (`b1') (`b2') (e(N))
    }
    postclose dD

    di as txt "  Countries with an estimable equation: `nok'"

    if `nok' > 10 & `rss_u' > 0 {
        local q     = `k_u' - `k_r'
        local dfden = `n_u' - `k_u'
        if `q' > 0 & `dfden' > 0 {
            local F  = ((`rss_r' - `rss_u') / `q') / (`rss_u' / `dfden')
            local pF = Ftail(`q', `dfden', `F')
            di as txt _n "  Poolability F(" `q' ", " `dfden' ") = " %9.3f `F'
            di as txt "  p = " %10.8f `pF'
            di as txt "  H0: identical slopes across countries."
        }
    }

    preserve
        use "$TABLES/diagJ_heterogeneity_${TAG}.dta", clear
        di as txt _n "  Country-specific L1 coefficients:"
        sum b_terr1 b_own1, detail

        qui sum b_terr1
        local mg   = r(mean)
        local mgse = r(sd) / sqrt(r(N))
        di as txt _n "  Mean Group, L1.terror in the FDI equation:"
        di as txt "    MG = " %9.4f `mg' "   se = " %8.4f `mgse' ///
            "   t = " %7.2f `mg'/`mgse'
        di as txt "  Compare with the pooled GMM coefficient. A large gap is"
        di as txt "  heterogeneity bias, not noise."

        export delimited using "$TABLES/diagJ_heterogeneity_${TAG}.csv", replace
    restore
}


*==============================================================================*
* 8. READING GUIDE
*==============================================================================*
di as txt _n "{hline 78}"
di as txt "What version 1 already established"
di as txt "{hline 78}"
di as txt "- Zero inflation is NOT the problem: the binary indicator makes J"
di as txt "  worse, and the 4-quarter sum is far worse still and pushes the"
di as txt "  largest eigenvalue to 0.995."
di as txt "- Per-capita scaling of the terror count IS the fix: J = 11.51,"
di as txt "  p = 0.17 on the full sample, with the p-value in the healthy"
di as txt "  0.10-0.25 range rather than suspiciously close to one."
di as txt "- Splitting into income or terror terciles does not help once the"
di as txt "  mechanical scaling of J with sample size is accounted for."
di as txt ""
di as txt "What this run adds"
di as txt "- Whether the residual autocorrelation spikes at lags 4 and 8,"
di as txt "  which would explain the alternating J profile through"
di as txt "  country-specific seasonality."
di as txt "- Whether slope homogeneity is rejected once terror is measured"
di as txt "  per capita, and how far Mean Group sits from the pooled estimate."

log close
*==============================================================================*
* END OF PART 2b, VERSION 2
*==============================================================================*
