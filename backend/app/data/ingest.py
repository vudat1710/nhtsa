"""Build data/nhtsa.db from the NHTSA flat files in data/raw (download with `python -m app.data.fetch`).

Field positions and meanings follow NHTSA's descriptions, kept in docs/nhtsa/ (CMPL.txt, RCL.txt, INV.txt). Each flat
file has one line per record x vehicle/product x component and no header; the split into two tables per file below is
ours: fields that are the same on every line of a record go in the first table, the rest in the second.

Tables (text is kept exactly as published, only mis-decoded UTF-8 is repaired, because quotes are verified verbatim):
  complaints(odino, make, model, year, received, failed, crash, fire, injured, deaths, miles, state, source,
             cmpl_type, prod_type, vehicles, other_products, text)
  complaint_components(odino, component, comp)       the components the owner selected for the judged product
  recalls(campno, filed, influenced_by, manufacturer, units, recall_type, do_not_drive, park_outside,
          defect, consequence, remedy)               all recalls: FLAT_RCL_PRE_2010 + FLAT_RCL_POST_2010
  recall_vehicles(campno, make, model, year, component, comp, built_from, built_to)
  investigations(action, opened, closed, subject, summary)
  investigation_vehicles(action, make, model, year, component, comp, campno)
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
HOTLINE = "EVOQ"   # CMPL_TYPE for complaints taken by NHTSA's hotline (CMPL.txt: "EVOQ = HOTLINE VOQ")
VEHICLE = "V"      # PROD_TYPE / RCLTYPECD for a vehicle (others: T tires, E equipment, C child restraint)
RECALL_FILES = ["FLAT_RCL_PRE_2010.zip", "FLAT_RCL_POST_2010.zip"]  # same 29 fields; no recall is in both

# Every documented field, in file order (the files have no header row).
CMPL = ["CMPLID", "ODINO", "MFR_NAME", "MAKETXT", "MODELTXT", "YEARTXT", "CRASH", "FAILDATE", "FIRE", "INJURED",
        "DEATHS", "COMPDESC", "CITY", "STATE", "VIN", "DATEA", "LDATE", "MILES", "OCCURENCES", "CDESCR", "CMPL_TYPE",
        "POLICE_RPT_YN", "PURCH_DT", "ORIG_OWNER_YN", "ANTI_BRAKES_YN", "CRUISE_CONT_YN", "NUM_CYLS", "DRIVE_TRAIN",
        "FUEL_SYS", "FUEL_TYPE", "TRANS_TYPE", "VEH_SPEED", "DOT", "TIRE_SIZE", "LOC_OF_TIRE", "TIRE_FAIL_TYPE",
        "ORIG_EQUIP_YN", "MANUF_DT", "SEAT_TYPE", "RESTRAINT_TYPE", "DEALER_NAME", "DEALER_TEL", "DEALER_CITY",
        "DEALER_STATE", "DEALER_ZIP", "PROD_TYPE", "REPAIRED_YN", "MEDICAL_ATTN", "VEHICLES_TOWED_YN",
        "STATE_OF_INCIDENT", "VEHICLE_OPERATOR"]
RCL = ["RECORD_ID", "CAMPNO", "MAKETXT", "MODELTXT", "YEARTXT", "MFGCAMPNO", "COMPNAME", "MFGNAME", "BGMAN", "ENDMAN",
       "RCLTYPECD", "POTAFF", "ODATE", "INFLUENCED_BY", "MFGTXT", "RCDATE", "DATEA", "RPNO", "FMVSS", "DESC_DEFECT",
       "CONEQUENCE_DEFECT", "CORRECTIVE_ACTION", "NOTES", "RCL_CMPT_ID", "MFR_COMP_NAME", "MFR_COMP_DESC",
       "MFR_COMP_PTNO", "DO_NOT_DRIVE", "PARK_OUTSIDE"]
INV = ["ACTION", "MAKE", "MODEL", "YEAR", "COMPNAME", "MFR_NAME", "ODATE", "CDATE", "CAMPNO", "SUBJECT", "SUMMARY"]
# The complaint fields we read. Not read: dealer contact, operator name and VIN (personal data), and the
# tire/child-seat/vehicle details the product does not use.
CMPL_USED = ["ODINO", "MAKETXT", "MODELTXT", "YEARTXT", "CRASH", "FAILDATE", "FIRE", "INJURED", "DEATHS", "COMPDESC",
             "STATE", "LDATE", "MILES", "CDESCR", "CMPL_TYPE", "PROD_TYPE"]

SCHEMA = """
CREATE TABLE complaints (odino INTEGER PRIMARY KEY, make TEXT, model TEXT, year TEXT, received TEXT, failed TEXT,
  crash INTEGER, fire INTEGER, injured INTEGER, deaths INTEGER, miles REAL, state TEXT, source TEXT, cmpl_type TEXT,
  prod_type TEXT, vehicles INTEGER, other_products INTEGER, text TEXT);
CREATE TABLE complaint_components (odino INTEGER, component TEXT, comp TEXT);
CREATE TABLE recalls (campno TEXT PRIMARY KEY, filed TEXT, influenced_by TEXT, manufacturer TEXT, units REAL,
  recall_type TEXT, do_not_drive INTEGER, park_outside INTEGER, defect TEXT, consequence TEXT, remedy TEXT);
CREATE TABLE recall_vehicles (campno TEXT, make TEXT, model TEXT, year TEXT, component TEXT, comp TEXT,
  built_from TEXT, built_to TEXT);
CREATE TABLE investigations (action TEXT PRIMARY KEY, opened TEXT, closed TEXT, subject TEXT, summary TEXT);
CREATE TABLE investigation_vehicles (action TEXT, make TEXT, model TEXT, year TEXT, component TEXT, comp TEXT,
  campno TEXT);
CREATE VIRTUAL TABLE complaints_fts USING fts5(text, content='complaints', content_rowid='odino');
"""


def read_flat(zip_name: str, names: list[str], keep: list[str] | None = None) -> pd.DataFrame:
    """Read the single tab-delimited file inside a zip: no header, no quoting, every value kept as a string.
    `names` are all documented fields in order; `keep` the ones to load (default all). Read as latin-1 (which never
    fails); fix_text() later repairs the UTF-8 per field. Blank lines (6 in the pre-2010 recalls) are skipped."""
    with zipfile.ZipFile(RAW / zip_name) as archive, archive.open(archive.namelist()[0]) as fh:
        return pd.read_csv(fh, sep="\t", header=None, names=names, usecols=keep or names, dtype=str,
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
    rows = read_flat("FLAT_CMPL.zip", CMPL, keep=CMPL_USED)  # one line per complaint x product x component
    rows["received"] = iso(rows.LDATE)
    rows = rows[rows.received >= COMPLAINTS_FROM].copy()

    # A complaint can name a vehicle and also tires, equipment or a child seat: one line per product (PROD_TYPE V, T,
    # E or C, CMPL.txt), each with its own make/model/year and components. The system judges vehicles, so a complaint
    # is judged on its first vehicle line; one without any vehicle line is kept on its first line (its make/model is
    # then a tire, equipment or child-seat product, and prod_type says so).
    rows["line"] = range(len(rows))
    rows["is_vehicle"] = rows.PROD_TYPE == VEHICLE
    vehicle_first = rows.sort_values(["is_vehicle", "line"], ascending=[False, True])
    judged = vehicle_first.drop_duplicates("ODINO").sort_values("line")  # one line per complaint, in file order
    text = judged.CDESCR.map(fix_text)
    is_hotline = judged.CMPL_TYPE == HOTLINE

    product_columns = ["MAKETXT", "MODELTXT", "YEARTXT", "PROD_TYPE"]
    judged_product_lines = rows.merge(judged[["ODINO", *product_columns]], on=["ODINO", *product_columns])
    vehicle_lines = rows[rows.is_vehicle].drop_duplicates(["ODINO", "MAKETXT", "MODELTXT", "YEARTXT"])
    other_product_lines = rows[~rows.is_vehicle].drop_duplicates(["ODINO", *product_columns])
    vehicles_named = vehicle_lines.groupby("ODINO").size()
    other_products_named = other_product_lines.groupby("ODINO").size()

    complaints = pd.DataFrame({
        "odino": judged.ODINO.astype(int),
        "make": judged.MAKETXT,
        "model": judged.MODELTXT,
        "year": judged.YEARTXT,
        "received": judged.received,
        "failed": iso(judged.FAILDATE),
        "crash": (judged.CRASH == "Y").astype(int),
        "fire": (judged.FIRE == "Y").astype(int),
        "injured": num(judged.INJURED),
        "deaths": num(judged.DEATHS),
        "miles": pd.to_numeric(judged.MILES, errors="coerce"),
        "state": judged.STATE,
        "source": is_hotline.map({True: "hotline", False: "owner"}),
        "cmpl_type": judged.CMPL_TYPE,
        "prod_type": judged.PROD_TYPE,
        "vehicles": judged.ODINO.map(vehicles_named).fillna(0).astype(int),
        "other_products": judged.ODINO.map(other_products_named).fillna(0).astype(int),
        "text": text,
    })
    save(con, "complaints", complaints)

    components = pd.DataFrame({
        "odino": judged_product_lines.ODINO.astype(int),
        "component": judged_product_lines.COMPDESC,
        "comp": top(judged_product_lines.COMPDESC),
    })
    save(con, "complaint_components", components.drop_duplicates())

    repaired = (text != judged.CDESCR).sum()
    not_vehicle = (complaints.prod_type != VEHICLE).sum()
    with_other = (complaints.other_products > 0).sum()
    several_vehicles = (complaints.vehicles > 1).sum()
    print(f"complaints {len(judged):,} (since {COMPLAINTS_FROM}), text repaired {repaired:,}, "
          f"hotline {is_hotline.sum():,}, about a vehicle {len(judged) - not_vehicle:,} "
          f"(of which {with_other:,} also name tires/equipment/child seats, {several_vehicles:,} several vehicles), "
          f"only a non-vehicle product {not_vehicle:,}")


def build_recalls(con: sqlite3.Connection) -> None:
    files = [read_flat(name, RCL) for name in RECALL_FILES]
    rows = pd.concat(files, ignore_index=True)  # one line per recall x vehicle/product x component
    first = rows.drop_duplicates("CAMPNO")  # one line per recall: these fields are the same on all its lines

    recalls = pd.DataFrame({
        "campno": first.CAMPNO,
        "filed": iso(first.RCDATE),
        "influenced_by": first.INFLUENCED_BY,
        "manufacturer": first.MFGNAME,
        "units": pd.to_numeric(first.POTAFF, errors="coerce"),
        "recall_type": first.RCLTYPECD,
        "do_not_drive": (first.DO_NOT_DRIVE == "Yes").astype(int),
        "park_outside": (first.PARK_OUTSIDE == "Yes").astype(int),
        "defect": first.DESC_DEFECT.map(fix_text),
        "consequence": first.CONEQUENCE_DEFECT.map(fix_text),
        "remedy": first.CORRECTIVE_ACTION.map(fix_text),
    })
    save(con, "recalls", recalls)

    # BGMAN / ENDMAN: the build dates the recall covers for this vehicle line (70% of vehicle recalls publish them on
    # at least one line). A model year alone does not prove a car is covered; the build date (from the VIN) does.
    vehicles = pd.DataFrame({
        "campno": rows.CAMPNO,
        "make": rows.MAKETXT,
        "model": rows.MODELTXT,
        "year": rows.YEARTXT,
        "component": rows.COMPNAME,
        "comp": top(rows.COMPNAME),
        "built_from": iso(rows.BGMAN),
        "built_to": iso(rows.ENDMAN),
    })
    save(con, "recall_vehicles", vehicles.drop_duplicates())

    by_file = ", ".join(f"{name} {frame.CAMPNO.nunique():,}" for name, frame in zip(RECALL_FILES, files, strict=True))
    print(f"recalls {len(first):,} ({by_file}), lines {len(rows):,}")


def build_investigations(con: sqlite3.Connection) -> None:
    rows = read_flat("FLAT_INV.zip", INV)  # one line per investigation x vehicle
    # 1,278 investigations (mostly 1970s-80s defect petitions) name no vehicle at all; they could never match a
    # complaint's vehicle, so they are left out.
    rows = rows[rows.MAKE != ""]
    first = rows.drop_duplicates("ACTION")  # one line per investigation

    investigations = pd.DataFrame({
        "action": first.ACTION,
        "opened": iso(first.ODATE),
        "closed": iso(first.CDATE),
        "subject": first.SUBJECT.map(fix_text),
        "summary": first.SUMMARY.map(fix_text),
    })
    save(con, "investigations", investigations)

    # CAMPNO (the recall the investigation led to) is per vehicle line: an investigation covering several
    # manufacturers can lead to a recall from each. INV.txt documents it as the 9-character recall number that links
    # to the recalls file, but 290 values are published without the trailing "000" ("24V204"); they are completed
    # so they link (289 then match a recall). Sub-numbers such as "02V027001" are kept as published.
    vehicles = pd.DataFrame({
        "action": rows.ACTION,
        "make": rows.MAKE,
        "model": rows.MODEL,
        "year": rows.YEAR,
        "component": rows.COMPNAME,
        "comp": top(rows.COMPNAME),
        "campno": rows.CAMPNO.map(lambda campno: campno + "000" if len(campno) == 6 else campno).replace("", None),
    })
    save(con, "investigation_vehicles", vehicles.drop_duplicates())

    print(f"investigations {len(first):,}, vehicle lines {len(rows):,}")


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
