*==============================================================================*
* pvar_q_04_screening.do
*
* Terrorism and FDI - quarterly Panel VAR
* SPECIFICATION SCREENING
*
* Two stages, deliberately separated:
*
*   STAGE 1  Variable level. Cross-sectional dependence and stationarity are
*            properties of a single series, not of a combination, so each
*            variable is tested once. Also reports the descriptive facts that
*            decide whether a specification is worth estimating at all: zero
*            share, number of countries with any variation, within-country sd.
*
*   STAGE 2  System level. Every combination of terror specification, scaling,
*            FDI measure, sample and lag order is estimated and screened on
*            the two gatekeepers: Hansen's J and the largest eigenvalue
*            modulus of the companion matrix.
*
*   STAGE 3  Decision table. For each combination, the lag orders that pass
*            both gatekeepers, the smallest such order, and the sample size
*            behind it.
*
* Held fixed on purpose (settled by the earlier diagnostics, or not a
* screening question):
*   - IHS transform for every variable
*   - FDI ratios winsorised at 1% within the base sample
*   - MINOBS 28
*   - time demeaning on; the td / no-td contrast belongs in the detailed
*     analysis of the selected specifications, not in the grid
*   - instlags = lags + 2, uncapped; the lag-8 instrument exclusion that the
*     residual diagnostics justified for attacks_total is a per-specification
*     decision, not a screening default
*   - no information criteria; with instlags tied to lags the J degrees of
*     freedom are constant and MBIC collapses into a ranking by J. The full
*     gatekeeper profile over lags 1-8 is reported instead.
*
* Output: output/logs/screen_<STAMP>.log
*         output/tables/screen_stage1_variables_<STAMP>.csv
*         output/tables/screen_stage2_grid_<STAMP>.csv
*         output/tables/screen_stage3_decision_<STAMP>.csv
*
* Stata 18. Required: pvar, pvarstable (Abrigo & Love); xtcd2; pescadf
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

foreach d in "$OUT" "$LOGS" "$TABLES" {
    cap mkdir "`d'"
}

global STAMP "run3"      // change to keep several screening runs side by side

cap log close _all
log using "$LOGS/screen_${STAMP}.log", replace text


*==============================================================================*
* 1. WHAT TO SCREEN  -  everything you edit lives in this section
*==============================================================================*

*--- 1a. Base sample ---------------------------------------------------------*
global BASESAMPLE   "terror"     // full | nospe | core | terror
global MINOBS       28
global WINSOR       1          // percent per tail for the FDI ratios

*--- 1b. Terror specifications -----------------------------------------------*
* Each entry: label | one or more GTD variables entering the system jointly.
* A single variable gives a 2-variable PVAR with FDI; two variables give a
* 3-variable PVAR. Add or remove lines freely.
global TERRORSPECS `" "tot|casualties_total" "cap|casualties_capital casualties_outside_capital" "top3|casualties_top3 casualties_outside_top3" "'

*--- 1c. Terror scalings -----------------------------------------------------*
* raw    : IHS of the count
* permil : IHS of the count per million inhabitants
global SCALINGS     "permil"

*--- 1d. FDI measures --------------------------------------------------------*
* Each entry: label | source variable | winsorise (1/0)
*   pct  inflow as percent of quarterly GDP
*   net  net inflow as percent of quarterly GDP
*   musd inflow in millions of USD, not normalised by GDP. IHS is roughly a
*        log here, so within-country variation is proportional and the country
*        effect absorbs the level.
global FDIVARS `" "inflow|fdi_in_pct_qgdp|1" "'

*--- 1e. Country groupings to construct ---------------------------------------*
* Each entry: name | country-level expression | number of quantile groups.
* The expression is averaged within country first, so a country is always in
* exactly one group.
global GROUPVARS `" "g_inc|gdp_lag_usd/pop_lag|3" "g_terr|casualties_total|3" "g_pop|pop_lag|3" "'

*--- 1e2. Income classification already merged into the data -----------------*
* Name of the variable holding the World Bank style income description, e.g.
* "Low income", "Lower middle income", "Upper middle income", "High income".
* Section 2d turns it into the ordered numeric variable inc_grp:
*     1 Low   2 Lower middle   3 Upper middle   4 High
* Leave INCVAR empty to skip. Numeric variables with value labels and
* variables already coded 1-4 are handled as well.
global INCVAR       "income_group"

* 1 forces one group per country (the country's modal value), so that a
* country cannot switch group mid-sample. A time-varying split would respond
* to the country's own growth during the sample and make the split partly
* endogenous. Set to 0 to keep the classification time-varying as merged.
global INCFIXCOUNTRY 1

*--- 1f. Samples -------------------------------------------------------------*
* Each entry: label | condition. The condition is combined with the base
* sample automatically, so write only the restriction itself. Use the group
* variables from 1e, inc_grp from 1e2, any variable in the data, or an
* explicit list.
*
* inc_grp examples:
*   "exhic|inc_grp<4"        everything except high income
*   "hic|inc_grp==4"         high income only
*   "lic_lmc|inc_grp<=2"     low and lower middle income
*   "developing|inlist(inc_grp, 1, 2, 3)"
global SAMPLES `" "all|1" "exhic|inc_grp<4" "lic_lmc|inc_grp<=2" "terrhigh|g_terr>1" "'

*--- 1g. Lag orders and instrument depth -------------------------------------*
global LAGLIST      "2 4 5 6 7 8"
global INSTEXTRA    2

*--- 1h. Gatekeeper thresholds -----------------------------------------------*
global JP_MIN       0.05      // Hansen J must not reject below this
global JP_SUSPECT   0.25      // above this, suspect instrument proliferation
global MOD_MAX      0.98      // largest eigenvalue modulus must stay below

*--- 1i. Stage switches ------------------------------------------------------*
global RUN_STAGE1   1
global RUN_STAGE2   1


*==============================================================================*
* 2. LOAD, BASE SAMPLE, VARIABLE CONSTRUCTION
*==============================================================================*
use "$DATA/pvar_q_work.dta", clear
xtset id t

cap drop insample n_insample
gen byte insample = s_$BASESAMPLE
bysort id: egen int n_insample = total(insample)
qui replace insample = 0 if n_insample < $MINOBS
bysort id: egen int T_country = total(insample)
xtset id t

qui count if insample
local NBASE = r(N)
qui levelsof id if insample, local(baseids)
local CBASE = wordcount("`baseids'")
di as txt _n "Base sample (${BASESAMPLE}, min $MINOBS quarters): " ///
    %7.0fc `NBASE' " obs, `CBASE' countries"

*--- 2a. FDI variables -------------------------------------------------------*
* Winsorising happens within the base sample, so that countries excluded from
* it never set the cut-offs.
local FDILIST ""
foreach f of global FDIVARS {
    tokenize "`f'", parse("|")
    local lab "`1'"
    local src "`3'"
    local win "`5'"

    capture confirm variable `src'
    if _rc {
        di as error "  FDI source variable not found, skipped: `src'"
        continue
    }

    cap drop y_`lab' _tmpf
    gen double _tmpf = `src' if insample

    if `win' == 1 & $WINSOR > 0 {
        local hp = 100 - $WINSOR
        qui _pctile _tmpf if insample, p($WINSOR `hp')
        qui replace _tmpf = r(r1) if insample & _tmpf < r(r1) & !missing(_tmpf)
        qui replace _tmpf = r(r2) if insample & _tmpf > r(r2) & !missing(_tmpf)
    }

    gen double y_`lab' = asinh(_tmpf)
    label var y_`lab' "IHS(`src')"
    drop _tmpf
    local FDILIST "`FDILIST' `lab'"
}
di as txt "FDI measures built:`FDILIST'"

*--- 2b. Terror variables, both scalings -------------------------------------*
* Short internal names keep every Stata variable below 32 characters:
*   tr_<abbrev>  raw count, IHS
*   tp_<abbrev>  count per million inhabitants, IHS
local TERRBUILT ""
foreach s of global TERRORSPECS {
    tokenize "`s'", parse("|")
    local slab "`1'"
    local svars "`3'"

    local ai = 0
    foreach v of local svars {
        local ++ai
        capture confirm variable `v'
        if _rc {
            di as error "  terror variable not found, skipped: `v'"
            continue
        }
        local ab "`slab'`ai'"

        cap drop tr_`ab' tp_`ab' _tmpt
        gen double tr_`ab' = asinh(`v') if insample
        label var tr_`ab' "IHS(`v')"

        gen double _tmpt = `v' / (pop_lag / 1000000) ///
            if insample & pop_lag > 0 & !missing(pop_lag)
        gen double tp_`ab' = asinh(_tmpt)
        label var tp_`ab' "IHS(`v' per million)"
        drop _tmpt

        local TERRBUILT "`TERRBUILT' tr_`ab' tp_`ab'"
    }
}
di as txt "Terror variables built:`TERRBUILT'"

*--- 2c. Country groupings ---------------------------------------------------*
foreach g of global GROUPVARS {
    tokenize "`g'", parse("|")
    local gname "`1'"
    local gexpr "`3'"
    local gq    "`5'"

    cap drop `gname' _gsrc _gmean
    cap gen double _gsrc = (`gexpr') if insample
    if _rc {
        di as error "  grouping expression failed, skipped: `gexpr'"
        continue
    }
    bysort id: egen double _gmean = mean(_gsrc)

    preserve
        keep if insample
        collapse (first) _gmean, by(id)
        xtile `gname' = _gmean, nq(`gq')
        keep id `gname'
        tempfile gg
        save `gg'
    restore
    merge m:1 id using `gg', nogen keep(master match)
    drop _gsrc _gmean
    xtset id t          // merge leaves the data sorted by id only

    di as txt "  grouping `gname' built from `gexpr' (`gq' groups)"
}
xtset id t

*--- 2d. Income classification into an ordered numeric variable --------------*
* Accepts the text descriptions ("Low income", "Lower middle income", ...),
* numeric variables carrying those value labels, and variables already coded
* 1-4. The result is inc_grp, ordered so that inc_grp < 4 means "everything
* except high income" and inc_grp <= 2 means "low and lower middle".

cap drop inc_grp
cap label drop inclbl
label define inclbl 1 "Low income" 2 "Lower middle income" ///
                    3 "Upper middle income" 4 "High income"

if "$INCVAR" == "" {
    di as txt _n "No income variable specified (INCVAR empty); inc_grp not built."
}
else {
    capture confirm variable $INCVAR
    if _rc {
        di as error _n "Income variable '$INCVAR' not found in the data."
        di as error "Set INCVAR in section 1e2 to the correct name, or leave"
        di as error "it empty. Any sample referring to inc_grp will be skipped."
    }
    else {
        tempvar inctxt
        capture confirm string variable $INCVAR
        if !_rc {
            qui gen str80 `inctxt' = $INCVAR
        }
        else {
            capture decode $INCVAR, gen(`inctxt')
            if _rc qui gen str80 `inctxt' = string($INCVAR)
        }

        * Normalise: lowercase, hyphens to spaces, collapse blanks. This also
        * catches the older labels "High income: OECD" / "High income: nonOECD"
        * and hyphenated spellings such as "Lower-middle income".
        qui replace `inctxt' = lower(itrim(trim(subinstr(`inctxt', "-", " ", .))))

        gen byte inc_grp = .
        * Order matters: "lower middle income" also contains "low".
        qui replace inc_grp = 3 if strpos(`inctxt', "upper middle") > 0
        qui replace inc_grp = 2 if missing(inc_grp) & strpos(`inctxt', "lower middle") > 0
        qui replace inc_grp = 4 if missing(inc_grp) & strpos(`inctxt', "high") > 0
        qui replace inc_grp = 1 if missing(inc_grp) & strpos(`inctxt', "low") > 0

        * Fallback: the variable was already coded 1-4.
        qui count if !missing(inc_grp)
        if r(N) == 0 {
            capture confirm numeric variable $INCVAR
            if !_rc {
                qui count if inlist($INCVAR, 1, 2, 3, 4)
                if r(N) > 0 {
                    qui replace inc_grp = $INCVAR if inlist($INCVAR, 1, 2, 3, 4)
                    di as txt "  income variable interpreted as numeric codes 1-4"
                }
            }
        }

        * Report anything the mapping did not recognise.
        qui levelsof `inctxt' if missing(inc_grp) & !missing(`inctxt') ///
            & `inctxt' != "" & insample, local(unmapped) clean
        if `"`unmapped'"' != "" {
            di as error _n "  Income values not recognised: `unmapped'"
            di as error "  Extend the matching rules in section 2d."
        }

        * One group per country, so that a country cannot switch mid-sample.
        if $INCFIXCOUNTRY == 1 {
            cap drop _incmode
            bysort id: egen byte _incmode = mode(inc_grp), minmode
            qui replace inc_grp = _incmode
            cap drop _incmode
        }

        label values inc_grp inclbl
        label var inc_grp "Income group (1 low ... 4 high)"
        xtset id t

        di as txt _n "Income classification (countries in the base sample):"
        preserve
            keep if insample
            collapse (first) inc_grp, by(id)
            tab inc_grp, missing
        restore

        qui levelsof id if insample & missing(inc_grp), local(noinc)
        if wordcount("`noinc'") > 0 {
            di as error "  Countries in the sample without an income group: " ///
                wordcount("`noinc'")
            di as error "  They drop out of every inc_grp sample but stay in 'all'."
        }
    }
}
xtset id t


*==============================================================================*
* 3. STAGE 1 - VARIABLE LEVEL DIAGNOSTICS
*==============================================================================*
* CD and stationarity are properties of a series, so each variable is tested
* once on the base sample rather than once per combination.
*
* Tests are run on the RAW series. Time demeaning is a model specification,
* not a preprocessing step: demeaning first can mechanically induce apparent
* stationarity and distort the differencing decision.

if $RUN_STAGE1 == 1 {

    capture postclose s1
    postfile s1 str12 varname str6 kind double(nobs ncty zeroshare nvarying) ///
    double(sd_within cd cd_p cdstar cdstar_p cips_lev cips_lev_p ///
           cips_dif cips_dif_p ur_ncty) ///
    using "$TABLES/screen_stage1_variables_${STAMP}.dta", replace

    di as txt _n "{hline 120}"
    di as txt "STAGE 1: variable level diagnostics (base sample)"
    di as txt "{hline 120}"
    di as txt %13s "variable" %8s "kind" %9s "obs" %6s "cty" %8s "%zero" ///
        %7s "vary" %9s "sd(w)" %10s "CD" %9s "CD p" %10s "CIPS lev" ///
        %9s "p" %10s "CIPS dif" %9s "p"

    local ALLVARS ""
    foreach f of local FDILIST {
        local ALLVARS "`ALLVARS' y_`f'"
    }
    local ALLVARS "`ALLVARS' `TERRBUILT'"

    foreach v of local ALLVARS {

        local kind = cond(substr("`v'", 1, 2) == "y_", "fdi", ///
                     cond(substr("`v'", 1, 3) == "tr_", "terr_r", "terr_p"))

        *--- descriptives ---
        qui count if insample & !missing(`v')
        local nv = r(N)
        if `nv' == 0 continue
        qui levelsof id if insample & !missing(`v'), local(vids)
        local cv = wordcount("`vids'")

        qui count if insample & `v' == 0
        local zs = 100 * r(N) / `nv'

        cap drop _sdv
        bysort id: egen double _sdv = sd(`v') if insample
        qui levelsof id if insample & _sdv > 0 & !missing(_sdv), local(vv)
        local nvary = wordcount("`vv'")
        qui sum _sdv if insample
        local sdw = r(mean)

        *--- Pesaran CD ---
        local cd = .
        local cdp = .
        local cds = .
        local cdsp = .
        cap qui xtcd2 `v' if insample
        if !_rc {
            foreach nm in CD {
                cap local cd = r(`nm')
                if _rc {
                    tempname M
                    cap matrix `M' = r(`nm')
                    if !_rc cap local cd = `M'[1,1]
                }
            }
            foreach nm in p {
                cap local cdp = r(`nm')
                if _rc {
                    tempname M2
                    cap matrix `M2' = r(`nm')
                    if !_rc cap local cdp = `M2'[1,1]
                }
            }
            foreach nm in CDstar {
                cap local cds = r(`nm')
                if _rc {
                    tempname M3
                    cap matrix `M3' = r(`nm')
                    if !_rc cap local cds = `M3'[1,1]
                }
            }
            foreach nm in pstar {
                cap local cdsp = r(`nm')
                if _rc {
                    tempname M4
                    cap matrix `M4' = r(`nm')
                    if !_rc cap local cdsp = `M4'[1,1]
                }
            }
        }

                *--- CIPS, levels and first differences ---------------------------*
        * pescadf tolerates unbalanced panels but not internal gaps, and it
        * evaluates an if-condition against the full xtset rectangle rather
        * than against the selected rows. Both problems disappear if the
        * sample is restricted physically before the call. Locals survive
        * preserve/restore, so the statistics are carried out.
        cap drop _maxd _gapfree
        preserve
            qui keep if insample & !missing(`v')
            bysort id (t): gen int _d = t - t[_n-1] if _n > 1
            bysort id: egen int _maxd = max(_d)
            bysort id: keep if _n == 1
            keep id _maxd
            tempfile gapinfo
            qui save `gapinfo'
        restore
        qui merge m:1 id using `gapinfo', nogen keep(master match)
        xtset id t
        gen byte _gapfree = (_maxd <= 1 | missing(_maxd))

        local cl = .
        local clp = .
        local cdif = .
        local cdifp = .
        local ur_ncty = 0

        preserve
            qui keep if insample & _gapfree & !missing(`v') ///
                & _sdv > 0 & !missing(_sdv)
            qui count
            local ur_nobs = r(N)
            qui levelsof id, local(urids)
            local ur_ncty = wordcount("`urids'")

            if `ur_nobs' > 0 {
                cap xtset id t
                di as txt "  `v': CIPS on `ur_ncty' gap-free countries, " ///
                    %7.0fc `ur_nobs' " observations"

                cap qui pescadf `v', lags(4) trend
                if _rc {
                    di as error "    levels failed with trend (rc " _rc ///
                        "); retrying without trend"
                    cap qui pescadf `v', lags(4)
                }
                if !_rc {
                    foreach nm in zt_bar cips tbar Zt_bar {
                        if missing(`cl') {
                            cap local cl = r(`nm')
                            if _rc local cl = .
                        }
                    }
                    foreach nm in pval p zt_bar_p {
                        if missing(`clp') {
                            cap local clp = r(`nm')
                            if _rc local clp = .
                        }
                    }
                }
                else di as error "    levels failed (rc " _rc ")"

                cap drop _dv
                qui gen double _dv = D.`v'
                cap qui pescadf _dv, lags(4) trend
                if _rc cap qui pescadf _dv, lags(4)
                if !_rc {
                    foreach nm in zt_bar cips tbar Zt_bar {
                        if missing(`cdif') {
                            cap local cdif = r(`nm')
                            if _rc local cdif = .
                        }
                    }
                    foreach nm in pval p zt_bar_p {
                        if missing(`cdifp') {
                            cap local cdifp = r(`nm')
                            if _rc local cdifp = .
                        }
                    }
                }
                else di as error "    differences failed (rc " _rc ")"
            }
            else di as error "  `v': no observations left for CIPS"
        restore

        cap drop _sdv _maxd _gapfree
        xtset id t

        di as txt %13s "`v'" %8s "`kind'" %9.0fc `nv' %6.0f `cv' %8.1f `zs' ///
            %7.0f `nvary' %9.3f `sdw' %10.2f `cd' %9.3f `cdp' ///
            %10.3f `cl' %9.3f `clp' %10.3f `cdif' %9.3f `cdifp'

        post s1 ("`v'") ("`kind'") (`nv') (`cv') (`zs') (`nvary') (`sdw') ///
            (`cd') (`cdp') (`cds') (`cdsp') (`cl') (`clp') (`cdif') (`cdifp') ///
			(`ur_ncty')
    }
    postclose s1

    preserve
        use "$TABLES/screen_stage1_variables_${STAMP}.dta", clear
        export delimited using ///
            "$TABLES/screen_stage1_variables_${STAMP}.csv", replace
    restore

    di as txt _n "Reading stage 1:"
    di as txt "  %zero   above roughly 85 means a linear PVAR is driven by a"
    di as txt "          handful of country episodes."
    di as txt "  vary    countries with any within-country variation. A low"
    di as txt "          count means the specification rests on few countries"
    di as txt "          however large the observation count looks."
    di as txt "  CIPS    pescadf prints the standardised Z[t-bar] and its"
    di as txt "          p-value; if the value is missing here, read it from"
    di as txt "          the printed output. More negative means stationary."
}


*==============================================================================*
* 4. STAGE 2 - SYSTEM LEVEL GATEKEEPER GRID
*==============================================================================*
* Two gatekeepers per cell:
*   Hansen J          overidentification. Degrees of freedom are n^2 *
*                     INSTEXTRA, so 8 for a 2-variable and 18 for a
*                     3-variable system.
*   Largest modulus   stability of the companion matrix. Above roughly 0.95
*                     the system is near-integrated and impulse responses
*                     will be imprecise even though the formal condition
*                     holds.
*
* Instruments per equation are n * (lags + INSTEXTRA) and do not grow with T,
* because pvar collapses the moment conditions unless gmmstyle is requested.
* The count is reported so it can be checked against the number of countries.

if $RUN_STAGE2 == 1 {

    capture postclose s2
    postfile s2 str8 terrspec str8 scaling str6 fdivar str12 sample ///
        int(nvar lags ilags ninst) ///
        double(nobs ncty jstat jdf jp maxmod zeroshare) ///
        byte(pass_j pass_mod pass_both suspect_j) ///
        using "$TABLES/screen_stage2_grid_${STAMP}.dta", replace

    di as txt _n "{hline 130}"
    di as txt "STAGE 2: gatekeeper grid"
    di as txt "{hline 130}"
    di as txt %8s "terror" %8s "scale" %6s "fdi" %11s "sample" %5s "n" ///
        %5s "lag" %6s "inst" %9s "obs" %6s "cty" %10s "J" %5s "df" ///
        %9s "J p" %8s "maxmod" %7s "pass"

    local ncell = 0

    foreach sp of global TERRORSPECS {
        tokenize "`sp'", parse("|")
        local slab "`1'"
        local svars "`3'"
        local nterr = wordcount("`svars'")

        foreach sc of global SCALINGS {
            local pre = cond("`sc'" == "raw", "tr_", "tp_")

            * Build the terror variable list for this cell.
            local tvlist ""
            forvalues a = 1/`nterr' {
                capture confirm variable `pre'`slab'`a'
                if !_rc local tvlist "`tvlist' `pre'`slab'`a'"
            }
            if "`tvlist'" == "" continue

            * Zero share of the first terror variable, for context.
            local firstv : word 1 of `tvlist'
            qui count if insample & !missing(`firstv')
            local den = r(N)
            qui count if insample & `firstv' == 0
            local zs = cond(`den' > 0, 100 * r(N) / `den', .)

            foreach fv of local FDILIST {

                foreach sm of global SAMPLES {
                    tokenize "`sm'", parse("|")
                    local smlab "`1'"
                    local smcnd "`3'"
                    local cond "insample & (`smcnd')"

                    * A sample whose condition names a variable that was never
                    * built (for example inc_grp when INCVAR is unset) is
                    * skipped with a message rather than aborting the grid.
                    capture qui count if `cond'
                    if _rc {
                        di as error "  sample `smlab' skipped: condition " ///
                            "`smcnd' could not be evaluated (rc " _rc ")"
                        continue
                    }

                    qui count if `cond'
                    if r(N) < 500 {
                        di as error "  `slab' `sc' `fv' `smlab': " ///
                            "only " r(N) " observations, skipped"
                        continue
                    }
                    qui levelsof id if `cond', local(cids)
                    local cc = wordcount("`cids'")

                    local SYS "`tvlist' y_`fv'"
                    local nv = wordcount("`SYS'")

                    foreach p of global LAGLIST {
                        local k = `p' + $INSTEXTRA
                        local ninst = `nv' * `k'

                        cap pvar `SYS' if `cond', lags(`p') instlags(1/`k') td
                        if _rc {
                            di as error "  `slab' `sc' `fv' `smlab' l`p': " ///
                                "estimation failed (rc " _rc ")"
                            continue
                        }

                        local nb = e(N)
                        local js = e(J)
                        local jd = e(J_df)
                        local jpv = cond(missing(`js') | missing(`jd') | ///
                                         `jd' <= 0, ., chi2tail(`jd', `js'))

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

                        local pj  = (`jpv' >= $JP_MIN)   & !missing(`jpv')
                        local pm  = (`mm'  <  $MOD_MAX)  & !missing(`mm')
                        local pb  = `pj' & `pm'
                        local sj  = (`jpv' > $JP_SUSPECT) & !missing(`jpv')

                        local flag = cond(`pb', "yes", "no")
                        if `pb' & `sj' local flag = "yes?"

                        di as txt %8s "`slab'" %8s "`sc'" %6s "`fv'" ///
                            %11s "`smlab'" %5.0f `nv' %5.0f `p' %6.0f `ninst' ///
                            %9.0fc `nb' %6.0f `cc' %10.2f `js' %5.0f `jd' ///
                            %9.4f `jpv' %8.3f `mm' %7s "`flag'"

                        post s2 ("`slab'") ("`sc'") ("`fv'") ("`smlab'") ///
                            (`nv') (`p') (`k') (`ninst') (`nb') (`cc') ///
                            (`js') (`jd') (`jpv') (`mm') (`zs') ///
                            (`pj') (`pm') (`pb') (`sj')

                        local ++ncell
                    }
                }
            }
        }
    }
    postclose s2

    di as txt _n "Cells estimated: `ncell'"

    preserve
        use "$TABLES/screen_stage2_grid_${STAMP}.dta", clear
        export delimited using ///
            "$TABLES/screen_stage2_grid_${STAMP}.csv", replace
    restore
}


*==============================================================================*
* 5. STAGE 3 - DECISION TABLE
*==============================================================================*
* One row per combination, collapsing the lag dimension: how many lag orders
* pass, which is the smallest, and what the diagnostics look like there.

preserve
    use "$TABLES/screen_stage2_grid_${STAMP}.dta", clear

    gen int lag_pass = lags if pass_both == 1
    bysort terrspec scaling fdivar sample: egen int n_pass    = total(pass_both)
    bysort terrspec scaling fdivar sample: egen int best_lag  = min(lag_pass)
    bysort terrspec scaling fdivar sample: egen double best_jp = ///
        max(cond(lags == best_lag, jp, .))
    bysort terrspec scaling fdivar sample: egen double best_mod = ///
        max(cond(lags == best_lag, maxmod, .))
    bysort terrspec scaling fdivar sample: egen double best_n = ///
        max(cond(lags == best_lag, nobs, .))
    bysort terrspec scaling fdivar sample: egen double best_cty = ///
        max(cond(lags == best_lag, ncty, .))

    bysort terrspec scaling fdivar sample: keep if _n == 1
    keep terrspec scaling fdivar sample nvar zeroshare n_pass best_lag ///
        best_jp best_mod best_n best_cty
    gsort -n_pass best_lag -best_cty

    format best_jp best_mod %8.3f
    format zeroshare %6.1f

    di as txt _n "{hline 110}"
    di as txt "STAGE 3: decision table, sorted by number of passing lag orders"
    di as txt "{hline 110}"
    list terrspec scaling fdivar sample nvar zeroshare n_pass best_lag ///
        best_jp best_mod best_n best_cty, noobs sepby(terrspec)

    export delimited using ///
        "$TABLES/screen_stage3_decision_${STAMP}.csv", replace
restore

di as txt _n "{hline 78}"
di as txt "How to use this"
di as txt "{hline 78}"
di as txt "1. A combination that passes at several adjacent lag orders is far"
di as txt "   more trustworthy than one that passes at exactly one. Isolated"
di as txt "   passes are usually an accident of the instrument depth."
di as txt "2. Read best_cty next to best_n. A specification resting on 40"
di as txt "   countries is a different object from one resting on 119, even"
di as txt "   with a similar observation count."
di as txt "3. Check zeroshare from stage 1 before believing any sparse"
di as txt "   specification, however good its J looks."
di as txt "4. A J p-value above $JP_SUSPECT is flagged yes? rather than yes."
di as txt "   Verify the instrument count against the country count before"
di as txt "   treating it as a pass."
di as txt "5. This screening fixes td on. For the specifications you carry"
di as txt "   forward, the td / no-td contrast is a result in its own right"
di as txt "   and must be reported."

log close
*==============================================================================*
* END OF SCREENING
*==============================================================================*
