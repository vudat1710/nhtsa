"""Build data/nhtsa.db from the NHTSA flat files in data/raw (download with `python -m app.data.fetch`).

Field meanings follow NHTSA's own descriptions, which ship with the data: data/raw/CMPL.txt, RCL.txt, INV.txt.

Tables (text is kept exactly as published, only mis-decoded UTF-8 is repaired, because quotes are verified verbatim):
  complaints(odino, make, model, year, received, failed, crash, fire, injured, deaths, miles, state, source,
             cmpl_type, vehicles, text)
  complaint_components(odino, component, comp)       one row per component the owner selected (for its vehicle)
  recalls(campno, filed, influenced_by, manufacturer, units, defect, consequence, remedy)
  recall_vehicles(campno, make, model, year, component, comp)
  investigations(action, opened, closed, campno, subject, summary)
  investigation_vehicles(action, make, model, year, component, comp)
  complaints_fts                                      full-text index over complaints.text
`comp` = top-level component ("AIR BAGS:FRONTAL" -> "AIR BAGS"); dates are ISO strings so they compare as text.
"""
import sqlite3
import time
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "nhtsa.db"
COMPLAINTS_FROM = "2020-01-01"
HOTLINE = "EVOQ"  # CMPL_TYPE for complaints taken by NHTSA's hotline (CMPL.txt: "EVOQ = HOTLINE VOQ")

CMPL = ["CMPLID", "ODINO", "MFR_NAME", "MAKETXT", "MODELTXT", "YEARTXT", "CRASH", "FAILDATE", "FIRE", "INJURED",
        "DEATHS", "COMPDESC", "CITY", "STATE", "VIN", "DATEA", "LDATE", "MILES", "OCCURENCES", "CDESCR", "CMPL_TYPE"]
RCL = ["RECORD_ID", "CAMPNO", "MAKETXT", "MODELTXT", "YEARTXT", "MFGCAMPNO", "COMPNAME", "MFGNAME", "BGMAN", "ENDMAN",
       "RCLTYPECD", "POTAFF", "ODATE", "INFLUENCED_BY", "MFGTXT", "RCDATE", "DATEA", "RPNO", "FMVSS", "DESC_DEFECT",
       "CONEQUENCE_DEFECT", "CORRECTIVE_ACTION"]
INV = ["ACTION", "MAKE", "MODEL", "YEAR", "COMPNAME", "MFR_NAME", "ODATE", "CDATE", "CAMPNO", "SUBJECT", "SUMMARY"]

SCHEMA = """
CREATE TABLE complaints (odino INTEGER PRIMARY KEY, make TEXT, model TEXT, year TEXT, received TEXT, failed TEXT,
  crash INTEGER, fire INTEGER, injured INTEGER, deaths INTEGER, miles REAL, state TEXT, source TEXT, cmpl_type TEXT,
  vehicles INTEGER, text TEXT);
CREATE TABLE complaint_components (odino INTEGER, component TEXT, comp TEXT);
CREATE TABLE recalls (campno TEXT PRIMARY KEY, filed TEXT, influenced_by TEXT, manufacturer TEXT, units REAL,
  defect TEXT, consequence TEXT, remedy TEXT);
CREATE TABLE recall_vehicles (campno TEXT, make TEXT, model TEXT, year TEXT, component TEXT, comp TEXT);
CREATE TABLE investigations (action TEXT PRIMARY KEY, opened TEXT, closed TEXT, campno TEXT, subject TEXT,
  summary TEXT);
CREATE TABLE investigation_vehicles (action TEXT, make TEXT, model TEXT, year TEXT, component TEXT, comp TEXT);
CREATE VIRTUAL TABLE complaints_fts USING fts5(text, content='complaints', content_rowid='odino');
"""


def read_flat(zip_name: str, names: list[str]) -> pd.DataFrame:
    """Read the single tab-delimited file inside a zip: no header, no quoting, every value kept as a string.
    Read as latin-1 (which never fails); fix_text() later repairs the UTF-8 per field."""
    with zipfile.ZipFile(RAW / zip_name) as archive, archive.open(archive.namelist()[0]) as fh:
        return pd.read_csv(fh, sep="\t", header=None, names=names, usecols=range(len(names)), dtype=str,
                           quoting=3, encoding="latin-1", on_bad_lines="skip", keep_default_na=False)


def fix_text(s: str) -> str:
    """'â\\x80\\x9cInsufficient' -> '“Insufficient': bytes were UTF-8 but decoded as latin-1."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def iso(s: pd.Series) -> pd.Series:
    """'20240318' -> '2024-03-18'; unparseable dates become None."""
    dates = pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    return dates.dt.strftime("%Y-%m-%d").where(dates.notna(), None)


def top(component: pd.Series) -> pd.Series:
    """'AIR BAGS:FRONTAL' -> 'AIR BAGS'."""
    return component.str.split(":").str[0].str.strip()


def save(con: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    df.to_sql(table, con, index=False, if_exists="append")


def num(s: pd.Series) -> pd.Series:
    """Text to int; blank or invalid values become 0."""
    return pd.to_numeric(s, errors="coerce").fillna(0).astype(int)


def build_complaints(con: sqlite3.Connection) -> None:
    rows = read_flat("FLAT_CMPL.zip", CMPL)  # one row per complaint x component (CMPL.txt, ODINO)
    rows["received"] = iso(rows.LDATE)
    rows = rows[rows.received >= COMPLAINTS_FROM]
    first = rows.drop_duplicates("ODINO")  # one row per complaint: its first line
    text = first.CDESCR.map(fix_text)
    is_hotline = first.CMPL_TYPE == HOTLINE

    # NHTSA documents ODINO repeating once per component. About 1% of complaints also name more than one vehicle or
    # product on their lines. The system judges one vehicle per complaint, so a complaint keeps its first line's
    # vehicle and only that vehicle's components; `vehicles` records how many it named.
    vehicle_columns = ["MAKETXT", "MODELTXT", "YEARTXT"]
    vehicles_named = rows.drop_duplicates(["ODINO", *vehicle_columns]).groupby("ODINO").size()
    own_vehicle_lines = rows.merge(first[["ODINO", *vehicle_columns]], on=["ODINO", *vehicle_columns])

    complaints = pd.DataFrame({
        "odino": first.ODINO.astype(int),
        "make": first.MAKETXT,
        "model": first.MODELTXT,
        "year": first.YEARTXT,
        "received": first.received,
        "failed": iso(first.FAILDATE),
        "crash": (first.CRASH == "Y").astype(int),
        "fire": (first.FIRE == "Y").astype(int),
        "injured": num(first.INJURED),
        "deaths": num(first.DEATHS),
        "miles": pd.to_numeric(first.MILES, errors="coerce"),
        "state": first.STATE,
        "source": is_hotline.map({True: "hotline", False: "owner"}),
        "cmpl_type": first.CMPL_TYPE,
        "vehicles": first.ODINO.map(vehicles_named).astype(int),
        "text": text,
    })
    save(con, "complaints", complaints)

    components = pd.DataFrame({
        "odino": own_vehicle_lines.ODINO.astype(int),
        "component": own_vehicle_lines.COMPDESC,
        "comp": top(own_vehicle_lines.COMPDESC),
    })
    save(con, "complaint_components", components.drop_duplicates())

    repaired = (text != first.CDESCR).sum()
    multi_vehicle = (complaints.vehicles > 1).sum()
    print(f"complaints {len(first):,} (since {COMPLAINTS_FROM}), component rows {len(own_vehicle_lines):,}, "
          f"text repaired {repaired:,}, hotline {is_hotline.sum():,}, naming several vehicles {multi_vehicle:,}")


def build_recalls(con: sqlite3.Connection) -> None:
    rows = read_flat("FLAT_RCL_POST_2010.zip", RCL)  # one row per recall x vehicle x component
    first = rows.drop_duplicates("CAMPNO")  # one row per recall

    recalls = pd.DataFrame({
        "campno": first.CAMPNO,
        "filed": iso(first.RCDATE),
        "influenced_by": first.INFLUENCED_BY,
        "manufacturer": first.MFGNAME,
        "units": pd.to_numeric(first.POTAFF, errors="coerce"),
        "defect": first.DESC_DEFECT.map(fix_text),
        "consequence": first.CONEQUENCE_DEFECT.map(fix_text),
        "remedy": first.CORRECTIVE_ACTION.map(fix_text),
    })
    save(con, "recalls", recalls)

    vehicles = pd.DataFrame({
        "campno": rows.CAMPNO,
        "make": rows.MAKETXT,
        "model": rows.MODELTXT,
        "year": rows.YEARTXT,
        "component": rows.COMPNAME,
        "comp": top(rows.COMPNAME),
    })
    save(con, "recall_vehicles", vehicles.drop_duplicates())

    print(f"recalls {len(first):,}, vehicle rows {len(rows):,}")


def build_investigations(con: sqlite3.Connection) -> None:
    rows = read_flat("FLAT_INV.zip", INV)  # one row per investigation x vehicle
    # 1,278 investigations (mostly 1970s-80s defect petitions) name no vehicle at all; they could never match a
    # complaint's vehicle, so they are left out.
    rows = rows[rows.MAKE != ""]
    first = rows.drop_duplicates("ACTION")  # one row per investigation

    investigations = pd.DataFrame({
        "action": first.ACTION,
        "opened": iso(first.ODATE),
        "closed": iso(first.CDATE),
        "campno": first.CAMPNO.replace("", None),
        "subject": first.SUBJECT.map(fix_text),
        "summary": first.SUMMARY.map(fix_text),
    })
    save(con, "investigations", investigations)

    vehicles = pd.DataFrame({
        "action": rows.ACTION,
        "make": rows.MAKE,
        "model": rows.MODEL,
        "year": rows.YEAR,
        "component": rows.COMPNAME,
        "comp": top(rows.COMPNAME),
    })
    save(con, "investigation_vehicles", vehicles.drop_duplicates())

    print(f"investigations {len(first):,}, vehicle rows {len(rows):,}")


INDEXES = """
CREATE INDEX ix_cc ON complaint_components(odino);
CREATE INDEX ix_complaints_vehicle ON complaints(make, model, year, received);
CREATE INDEX ix_rv_vehicle ON recall_vehicles(make, model, year);
CREATE INDEX ix_rv_campno ON recall_vehicles(campno);
CREATE INDEX ix_iv_vehicle ON investigation_vehicles(make, model, year);
INSERT INTO complaints_fts(rowid, text) SELECT odino, text FROM complaints;
"""


def main() -> None:
    started = time.time()
    # Build into a temporary file and swap it in at the end, so a failed build never leaves a half-built database.
    tmp = DB.with_suffix(".building.db")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    build_complaints(con)
    build_recalls(con)
    build_investigations(con)
    con.executescript(INDEXES)
    con.commit()
    con.execute("VACUUM")
    con.close()
    tmp.replace(DB)
    print(f"built {DB.name} ({DB.stat().st_size / 1e6:,.0f} MB) in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
