#remove all countries that are not in the sample by Abadie & Gardeazabal
import country_converter as coco

country_names_186 = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda", "Argentina", "Armenia",
    "Australia", "Austria", "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus", "Belgium",
    "Belize", "Benin", "Bermuda", "Bhutan", "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei",
    "Bulgaria", "Burkina Faso", "Burundi", "Cambodia", "Cameroon", "Canada", "Cape Verde", "Cayman Islands",
    "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros", "Congo", "Costa Rica",
    "Cote d'Ivoire", "Croatia", "Cuba", "Cyprus", "Czech Republic", "DRCongo", "Denmark", "Djibouti",
    "Dominica", "Dominican Republic", "East Timor", "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea",
    "Eritrea", "Estonia", "Ethiopia", "Fiji", "Finland", "France", "French Guiana", "Gabon", "Gambia", "Georgia",
    "Germany", "Ghana", "Greece", "Grenada", "Guatemala", "Guinea", "Guinea Bissau", "Guyana", "Haiti",
    "Honduras", "Hong Kong SAR", "Hungary", "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel",
    "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kuwait", "Kyrgyzstan", "Lao PDR", "Latvia",
    "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania", "Luxembourg", "Macedonia", "Macau",
    "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali", "Malta", "Martinique", "Mauritania", "Mauritius",
    "Mexico", "Moldova", "Mongolia", "Morocco", "Mozambique", "Myanmar", "Namibia", "Nepal", "Netherlands",
    "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea", "Norway", "Oman", "Pakistan", "Palestinian Authority",
    "Panama", "Papua New Guinea", "Paraguay", "Peru", "Philippines", "Poland", "Portugal", "Puerto Rico", "Qatar",
    "Romania", "Russia", "Rwanda", "Samoa", "Sao Tome", "Saudi Arabia", "Senegal", "Serbia", "Montenegro",
    "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia", "Somalia", "South Africa", "South Korea",
    "Spain", "Sri Lanka", "Sudan", "Suriname", "Swaziland", "Sweden", "Switzerland", "Syria", "Taiwan", "Tajikistan",
    "Tanzania", "Thailand", "Togo", "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan", "Uganda",
    "Ukraine", "United Arab Emirates", "United Kingdom", "United States", "Uruguay", "Uzbekistan", "Venezuela",
    "Vietnam", "Yemen", "Zambia", "Zimbabwe"
]

country_names_110 = [
    # 110-country sample (excluding the "plus those in 98-country sample" part)
    "Antigua and Barbuda", "Comoros", "Dominica", "Eritrea", "Liberia", "Maldives",
    "Palestinian Authority", "Papua New Guinea", "Sao Tome", "Serbia", "Montenegro",
    "Seychelles", "Sudan",
    # 98-country sample
    "Albania", "Argentina", "Armenia", "Australia", "Austria", "Azerbaijan", "Bahamas",
    "Belarus", "Bolivia", "Bosnia and Herzegovina", "Botswana", "Bulgaria", "Cambodia",
    "Canada", "Cape Verde", "Costa Rica", "Croatia", "Czech Republic", "Denmark",
    "Djibouti", "Dominican Republic", "Ecuador", "Egypt", "El Salvador", "Estonia",
    "Finland", "France", "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Guatemala",
    "Guinea", "Guinea Bissau", "Guyana", "Haiti", "Honduras", "Hong Kong SAR", "Hungary",
    "Iceland", "Indonesia", "Ireland", "Italy", "Jamaica", "Japan", "Jordan", "Kenya",
    "Kyrgyzstan", "Latvia", "Lebanon", "Lesotho", "Lithuania", "Macedonia", "Malawi",
    "Malaysia", "Mauritania", "Mauritius", "Mexico", "Mongolia", "Morocco", "Netherlands",
    "New Zealand", "Nicaragua", "Norway", "Pakistan", "Panama", "Paraguay", "Peru",
    "Philippines", "Poland", "Portugal", "Romania", "Sierra Leone", "Singapore",
    "Slovakia", "Slovenia", "South Africa", "South Korea", "Spain", "Swaziland",
    "Sweden", "Switzerland", "Tajikistan", "Thailand", "Trinidad and Tobago", "Tunisia",
    "Turkey", "Turkmenistan", "Uganda", "Ukraine", "United Kingdom", "United States",
    "Uruguay", "Venezuela", "Vietnam", "Yemen", "Zambia"
]

country_names_98 = [
    "Albania", "Argentina", "Armenia", "Australia", "Austria", "Azerbaijan", "Bahamas",
    "Belarus", "Bolivia", "Bosnia and Herzegovina", "Botswana", "Bulgaria", "Cambodia",
    "Canada", "Cape Verde", "Costa Rica", "Croatia", "Czech Republic", "Denmark",
    "Djibouti", "Dominican Republic", "Ecuador", "Egypt", "El Salvador", "Estonia",
    "Finland", "France", "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Guatemala",
    "Guinea", "Guinea Bissau", "Guyana", "Haiti", "Honduras", "Hong Kong SAR", "Hungary",
    "Iceland", "Indonesia", "Ireland", "Italy", "Jamaica", "Japan", "Jordan", "Kenya",
    "Kyrgyzstan", "Latvia", "Lebanon", "Lesotho", "Lithuania", "Macedonia", "Malawi",
    "Malaysia", "Mauritania", "Mauritius", "Mexico", "Mongolia", "Morocco", "Netherlands",
    "New Zealand", "Nicaragua", "Norway", "Pakistan", "Panama", "Paraguay", "Peru",
    "Philippines", "Poland", "Portugal", "Romania", "Sierra Leone", "Singapore",
    "Slovakia", "Slovenia", "South Africa", "South Korea", "Spain", "Swaziland",
    "Sweden", "Switzerland", "Tajikistan", "Thailand", "Trinidad and Tobago", "Tunisia",
    "Turkey", "Turkmenistan", "Uganda", "Ukraine", "United Kingdom", "United States",
    "Uruguay", "Venezuela", "Vietnam", "Yemen", "Zambia"
]

cc = coco.CountryConverter()

# Convert to ISO3
iso3_list_186 = cc.convert(names=country_names_186, to='ISO3')
iso3_list_110 = cc.convert(names=country_names_110, to='ISO3')
iso3_list_98 = cc.convert(names=country_names_98, to='ISO3')

set_186 = set(iso3_list_186)
set_110 = set(iso3_list_110)
set_98 = set(iso3_list_98)

# Create dummy variables
# df_standardized['in_186_sample'] = df_standardized['ISO3'].apply(lambda x: 1 if x in set_186 else 0)
# df_standardized['in_110_sample'] = df_standardized['ISO3'].apply(lambda x: 1 if x in set_110 else 0)
# df_standardized['in_98_sample'] = df_standardized['ISO3'].apply(lambda x: 1 if x in set_98 else 0)
#
# df_standardized['in_186_sample'] = df_standardized['ISO3'].isin(set_186).astype(int)
# df_standardized['in_110_sample'] = df_standardized['ISO3'].isin(set_110).astype(int)
# df_standardized['in_98_sample'] = df_standardized['ISO3'].isin(set_98).astype(int)