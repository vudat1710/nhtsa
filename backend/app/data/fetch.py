"""Download the NHTSA flat files (public domain, US government) into data/raw."""
import urllib.request

from app.data.ingest import RAW

BASE = "https://static.nhtsa.gov/odi/ffdd/"
FILES = ["cmpl/FLAT_CMPL.zip", "rcl/FLAT_RCL_POST_2010.zip", "inv/FLAT_INV.zip"]


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for path in FILES:
        url = BASE + path
        target = RAW / path.split("/")[1]  # "cmpl/FLAT_CMPL.zip" -> data/raw/FLAT_CMPL.zip
        print(f"downloading {url} -> {target}")
        urllib.request.urlretrieve(url, target)


if __name__ == "__main__":
    main()
