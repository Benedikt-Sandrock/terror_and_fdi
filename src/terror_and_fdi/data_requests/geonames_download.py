from urllib.request import urlretrieve
from zipfile import ZipFile
from terror_and_fdi.config import RAW

GEONAMES_URL = "https://download.geonames.org/export/dump/"

GEONAMES_PATH = RAW / "geonames"
GEONAMES_PATH.mkdir(parents=True, exist_ok=True)

FILES = [
    "allCountries.zip",
    "alternateNamesV2.zip",
    "countryInfo.txt",
    "featureCodes_en.txt",
    "admin1CodesASCII.txt",
    "admin2Codes.txt",
]


def download_geonames():
    for filename in FILES:
        output_path = GEONAMES_PATH / filename

        if output_path.exists():
            print(f"{filename} existiert bereits.")
            continue

        url = GEONAMES_URL + filename
        print(f"Lade {filename} herunter ...")
        urlretrieve(url, output_path)

    for filename in ["allCountries.zip", "alternateNamesV2.zip"]:
        zip_path = GEONAMES_PATH / filename

        print(f"Entpacke {filename} ...")
        with ZipFile(zip_path, "r") as zip_file:
            zip_file.extractall(GEONAMES_PATH)


download_geonames()