"""Download the NHTSA flat files (public domain, US government) into data/raw."""
import urllib.request

from app.data.ingest import RAW

BASE = "https://static.nhtsa.gov/odi/ffdd/"
FILES = ["cmpl/FLAT_CMPL.zip", "rcl/FLAT_RCL_POST_2010.zip", "inv/FLAT_INV.zip"]


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        target = RAW / f.split("/")[1]
        print(f"downloading {BASE + f} -> {target}")
        urllib.request.urlretrieve(BASE + f, target)


if __name__ == "__main__":
    main()
