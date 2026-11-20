"""Build data/nhtsa.db from the NHTSA flat files in data/raw (download with `python -m app.data.fetch`).

Tables (text is kept exactly as published, only mis-decoded UTF-8 is repaired, because quotes are verified verbatim):
  complaints(odino, make, model, year, received, failed, crash, fire, injured, deaths, miles, state, source, text)
  complaint_components(odino, component, comp)       one row per component the owner selected
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

CMPL = ["CMPLID", "ODINO", "MFR_NAME", "MAKETXT", "MODELTXT", "YEARTXT", "CRASH", "FAILDATE", "FIRE", "INJURED",
        "DEATHS", "COMPDESC", "CITY", "STATE", "VIN", "DATEA", "LDATE", "MILES", "OCCURENCES", "CDESCR"]
RCL = ["RECORD_ID", "CAMPNO", "MAKETXT", "MODELTXT", "YEARTXT", "MFGCAMPNO", "COMPNAME", "MFGNAME", "BGMAN", "ENDMAN",
       "RCLTYPECD", "POTAFF", "ODATE", "INFLUENCED_BY", "MFGTXT", "RCDATE", "DATEA", "RPNO", "FMVSS", "DESC_DEFECT",
       "CONEQUENCE_DEFECT", "CORRECTIVE_ACTION"]
INV = ["ACTION", "MAKE", "MODEL", "YEAR", "COMPNAME", "MFR_NAME", "ODATE", "CDATE", "CAMPNO", "SUBJECT", "SUMMARY"]

SCHEMA = """
CREATE TABLE complaints (odino INTEGER PRIMARY KEY, make TEXT, model TEXT, year TEXT, received TEXT, failed TEXT,
  crash INTEGER, fire INTEGER, injured INTEGER, deaths INTEGER, miles REAL, state TEXT, source TEXT, text TEXT);
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
    """Tab-delimited, no header, no quoting. Read as latin-1 (never fails), repair UTF-8 later per field."""
    with zipfile.ZipFile(RAW / zip_name) as z, z.open(z.namelist()[0]) as fh:
        return pd.read_csv(fh, sep="\t", header=None, names=names, usecols=range(len(names)), dtype=str,
                           quoting=3, encoding="latin-1", on_bad_lines="skip", keep_default_na=False)


def fix_text(s: str) -> str:
    """'â\\x80\\x9cInsufficient' -> '“Insufficient': bytes were UTF-8 but decoded as latin-1."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def iso(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    return d.dt.strftime("%Y-%m-%d").where(d.notna(), None)


def top(component: pd.Series) -> pd.Series:
    return component.str.split(":").str[0].str.strip()


def save(con: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    df.to_sql(table, con, index=False, if_exists="append")


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0).astype(int)


def build_complaints(con: sqlite3.Connection) -> None:
    c = read_flat("FLAT_CMPL.zip", CMPL)
    c["received"] = iso(c.LDATE)
    c = c[c.received >= COMPLAINTS_FROM]
    one = c.drop_duplicates("ODINO")
    text = one.CDESCR.map(fix_text)
    save(con, "complaints", pd.DataFrame({
        "odino": one.ODINO.astype(int), "make": one.MAKETXT, "model": one.MODELTXT, "year": one.YEARTXT,
        "received": one.received, "failed": iso(one.FAILDATE), "crash": (one.CRASH == "Y").astype(int),
        "fire": (one.FIRE == "Y").astype(int), "injured": num(one.INJURED), "deaths": num(one.DEATHS),
        "miles": pd.to_numeric(one.MILES, errors="coerce"), "state": one.STATE,
        "source": one.CDESCR.str.startswith("TL*").map({True: "hotline", False: "owner"}), "text": text,
    }))
    save(con, "complaint_components", pd.DataFrame({
        "odino": c.ODINO.astype(int), "component": c.COMPDESC, "comp": top(c.COMPDESC),
    }).drop_duplicates())
    print(f"complaints {len(one):,} (since {COMPLAINTS_FROM}), component rows {len(c):,}, "
          f"text repaired {(text != one.CDESCR).sum():,}")


def build_recalls(con: sqlite3.Connection) -> None:
    r = read_flat("FLAT_RCL_POST_2010.zip", RCL)
    one = r.drop_duplicates("CAMPNO")
    save(con, "recalls", pd.DataFrame({
        "campno": one.CAMPNO, "filed": iso(one.RCDATE), "influenced_by": one.INFLUENCED_BY,
        "manufacturer": one.MFGNAME, "units": pd.to_numeric(one.POTAFF, errors="coerce"),
        "defect": one.DESC_DEFECT.map(fix_text), "consequence": one.CONEQUENCE_DEFECT.map(fix_text),
        "remedy": one.CORRECTIVE_ACTION.map(fix_text),
    }))
    save(con, "recall_vehicles", pd.DataFrame({
        "campno": r.CAMPNO, "make": r.MAKETXT, "model": r.MODELTXT, "year": r.YEARTXT,
        "component": r.COMPNAME, "comp": top(r.COMPNAME),
    }).drop_duplicates())
    print(f"recalls {len(one):,}, vehicle rows {len(r):,}")


def build_investigations(con: sqlite3.Connection) -> None:
    i = read_flat("FLAT_INV.zip", INV)
    i = i[i.MAKE != ""]  # a few administrative rows have no vehicle, date or subject
    one = i.drop_duplicates("ACTION")
    save(con, "investigations", pd.DataFrame({
        "action": one.ACTION, "opened": iso(one.ODATE), "closed": iso(one.CDATE),
        "campno": one.CAMPNO.replace("", None), "subject": one.SUBJECT.map(fix_text),
        "summary": one.SUMMARY.map(fix_text),
    }))
    save(con, "investigation_vehicles", pd.DataFrame({
        "action": i.ACTION, "make": i.MAKE, "model": i.MODEL, "year": i.YEAR,
        "component": i.COMPNAME, "comp": top(i.COMPNAME),
    }).drop_duplicates())
    print(f"investigations {len(one):,}, vehicle rows {len(i):,}")


INDEXES = """
CREATE INDEX ix_cc ON complaint_components(odino);
CREATE INDEX ix_complaints_vehicle ON complaints(make, model, year, received);
CREATE INDEX ix_rv_vehicle ON recall_vehicles(make, model, year);
CREATE INDEX ix_rv_campno ON recall_vehicles(campno);
CREATE INDEX ix_iv_vehicle ON investigation_vehicles(make, model, year);
INSERT INTO complaints_fts(rowid, text) SELECT odino, text FROM complaints;
"""


def main() -> None:
    t = time.time()
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
    print(f"built {DB.name} ({DB.stat().st_size / 1e6:,.0f} MB) in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
