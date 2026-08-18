HOW TO CREATE THE BASIC DATASET - CAPITAL- AND TOP3-CLASSIFIED GTD MERGED WITH FDI DATA

=== GTD CLASSIFICATION ===
Run:
1. create_capital_reference_cshapes.py (Download and prepare dynamic capital file)
2. classify_gtd_capitals_cshapes.py (Use prepared dynamic capital file to classify events in capital/non-capital)

Download the GHS-UCDB data (multi-temporal dataset) from the following site:
https://human-settlement.emergency.copernicus.eu/ghs_ucdb_2024.php
Correct file name: GHS_UCDB_MTUC_GLOBE_R2024A.gpkg

3. ghs_ucdb_classification.py (Uses previously downloaded population and urban-centre data to classify events as
   in-/outside the 3 largest urban agglomerations)

=> CLASSIFICATION COMPLETE

=== AGGREGATION AND MERGE WITH FDI DATA ===
Run:
1. build_quarterly_terror_panel.py (Aggregates event-data to country-quarters. Creates different variables (fatalities,
   casualties, wounded) for different specifications (total, capital, top3))
2. clean_imf_bop_fdi_quarterly_optimized.py
3. merge_fdi_gtd_quarterly_fixed.py

