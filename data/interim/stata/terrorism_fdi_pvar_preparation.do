*===============================================================================
* PROJECT:   Terrorism and FDI - Panel VAR Analysis
*===============================================================================



*===============================================================================
* LOAD DATA AND PREPARE FOR MERGE
*===============================================================================
*-----------------------------------------------------------
* Drop observations for countries before they existed
* as independent states, based on GTD Codebook (Aug 2021), p.19
*-----------------------------------------------------------
clear
use "gtd_processed.dta"

drop if ISO3 == "not found"

* Germany - unification: 3 October 1990
drop if ISO3 == "DEU" & year < 1990

* Breakup of the Soviet Union (independence dates 1991)
foreach c in RUS ARM AZE BLR EST GEO KAZ KGZ LVA LTU MDA TJK TKM UKR UZB {
    drop if ISO3 == "`c'" & year < 1991
}

* Breakup of Czechoslovakia - independence: 1 January 1993
foreach c in CZE SVK {
    drop if ISO3 == "`c'" & year < 1993
}

* Breakup of Yugoslavia
drop if ISO3 == "HRV" & year < 1991   // Croatia
drop if ISO3 == "SVN" & year < 1991   // Slovenia
drop if ISO3 == "MKD" & year < 1991   // North Macedonia (Macedonia)
drop if ISO3 == "BIH" & year < 1992   // Bosnia and Herzegovina
drop if ISO3 == "SRB" & year < 2006   // Serbia
drop if ISO3 == "MNE" & year < 2006   // Montenegro

* Eritrea - independence: 24 May 1993
drop if ISO3 == "ERI" & year < 1993

* Renaming of Zaire to Democratic Republic of the Congo in 1997
drop if country_txt == "Democratic Republic of the Congo" & year < 1997
drop if country_txt == "Zaire" & year > 1997
replace country_txt = "Democratic Republic of the Congo" if country_txt == "Zaire"

unab all_vars : _all
local exclude "ISO3 year country_txt country_id cntry_id"
local sum_vars : list all_vars - exclude

foreach v of local sum_vars {
    bysort ISO3 year: replace `v' = `v'[1] + `v'[2] if ISO3 == "COD" & year == 1997
}

bysort ISO3 year: drop if _n == 2 & ISO3 == "COD" & year == 1997

* Independence of Zimbabwe in 1980
drop if country_txt == "Rhodesia" & year > 1980
drop if country_txt == "Zimbabwe" & year < 1980

foreach v of local sum_vars {
    bysort ISO3 year: replace `v' = `v'[1] + `v'[2] if ISO3 == "ZWE" & year == 1980
}

bysort ISO3 year: drop if _n == 2 & ISO3 == "ZWE" & year == 1980

* Drop remaining observations
drop if country_txt == "Czechoslovakia"
drop if country_txt == "New Hebrides"
drop if country_txt == "North Yemen"
drop if country_txt == "South Yemen"

*Alternatively:
*collapse (sum) `sum_vars' (first) country_txt country_id cntry_id, by(ISO3 year)


*===============================================================================
* MERGE ADDITIONAL DATASETS
*===============================================================================

merge 1:1 ISO3 year using "gmd_processed.dta"
rename _merge gmd_merge

merge 1:1 ISO3 year using "pwt_processed.dta"
rename _merge pwt_merge

merge 1:1 ISO3 year using "stat_tax_rate_processed.dta"
rename _merge tax_merge

merge 1:1 ISO3 year using "state_based_violence_processed.dta"
rename _merge ucdp_merge

merge 1:1 ISO3 year using "v_dem_processed.dta"
rename _merge v_dem_merge

merge 1:1 ISO3 year using "wb_data_processed.dta"
rename _merge wb_merge

merge m:1 ISO3 using "country_metadata_processed.dta"

* Restrict data to the timeframe and countries included in the GTD
drop if year < 1970 | year > 2020
drop if missing(country_txt)

drop *_merge /// Kept earlier to inspect merge, can be dropped

order country_txt ISO3 year











