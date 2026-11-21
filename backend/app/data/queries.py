"""Read-only queries. Every evidence query takes `as_of` (the complaint's received date) and only returns records that
existed strictly before it, so the system never sees the future (no look-ahead). This is the only place that rule lives.
"""
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.data.ingest import DB
from app.models import Complaint

MAX_RECALLS = 15  # 90% of complaints have <= 13 candidate recalls; more are cut, and the cut is reported


@dataclass(frozen=True)
class Vehicle:
    make: str
    model: str
    year: str


def connect(path: Path = DB) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def complaint(con: sqlite3.Connection, odino: int) -> Complaint | None:
    row = con.execute("SELECT * FROM complaints WHERE odino = ?", (odino,)).fetchone()
    if row is None:
        return None
    component_rows = con.execute("SELECT component FROM complaint_components WHERE odino = ? ORDER BY component",
                                 (odino,)).fetchall()
    components = [component_row[0] for component_row in component_rows]
    return Complaint(odino=row["odino"], make=row["make"], model=row["model"], year=row["year"],
                     received=row["received"], crash=row["crash"] or 0, fire=row["fire"] or 0,
                     injured=row["injured"] or 0, text=row["text"] or "", components=components)


def recalls_for(con: sqlite3.Connection, v: Vehicle, as_of: str, comps: list[str]) -> tuple[list[dict], int]:
    """Recalls covering this exact vehicle, filed before as_of. Same-component recalls first, then newest first.
    Returns (up to MAX_RECALLS recalls, total found)."""
    rows = con.execute(
        """SELECT r.*, rv.component, rv.comp FROM recall_vehicles rv JOIN recalls r USING (campno)
           WHERE rv.make = ? AND rv.model = ? AND rv.year = ? AND r.filed < ?""",
        (v.make, v.model, v.year, as_of)).fetchall()

    # SQL returns one row per (recall, component); merge them into one record per recall. Done here rather than with
    # SQL group_concat because component names can contain commas.
    recalls: dict[str, dict] = {}
    for row in rows:
        rec = recalls.get(row["campno"])
        if rec is None:
            rec = {key: row[key] for key in row.keys() if key not in ("component", "comp")}
            rec["components"], rec["comps"] = [], []
            recalls[row["campno"]] = rec
        if row["component"] not in rec["components"]:
            rec["components"].append(row["component"])
        if row["comp"] not in rec["comps"]:
            rec["comps"].append(row["comp"])

    def shares_component(rec: dict) -> bool:
        return bool(set(rec["comps"]) & set(comps))

    # Same-component recalls first, then newest first within each group.
    ordered = sorted(recalls.values(), key=lambda rec: (shares_component(rec), rec["filed"]), reverse=True)
    return ordered[:MAX_RECALLS], len(ordered)


def recall_model_years(con: sqlite3.Connection, campnos: list[str], make: str, model: str) -> dict[str, list[str]]:
    """Which model years of this make/model each recall covers (for 'your 2024 IONIQ 5 is covered: 2022-2024')."""
    if not campnos:
        return {}
    placeholders = ",".join("?" * len(campnos))
    rows = con.execute(f"""SELECT DISTINCT campno, year FROM recall_vehicles WHERE make = ? AND model = ?
                           AND campno IN ({placeholders}) ORDER BY year""", (make, model, *campnos))
    years_by_campno: dict[str, list[str]] = {}
    for campno, year in rows:
        if campno not in years_by_campno:
            years_by_campno[campno] = []
        years_by_campno[campno].append(year)
    return years_by_campno


def recall_build_dates(con: sqlite3.Connection, campnos: list[str], v: Vehicle) -> dict[str, tuple[str, str]]:
    """The build dates each recall covers for this exact vehicle (make, model, year), when NHTSA publishes them:
    earliest start and latest end over the recall's lines. Recalls without published dates are left out, and so are
    lines whose end is before their start (271 such lines are published)."""
    if not campnos:
        return {}
    placeholders = ",".join("?" * len(campnos))
    rows = con.execute(f"""SELECT campno, min(built_from), max(built_to) FROM recall_vehicles
                           WHERE make = ? AND model = ? AND year = ? AND campno IN ({placeholders})
                             AND built_from IS NOT NULL AND built_to IS NOT NULL AND built_to >= built_from
                           GROUP BY campno""", (v.make, v.model, v.year, *campnos)).fetchall()
    return {campno: (start, end) for campno, start, end in rows}


def recalls_other_years(con: sqlite3.Connection, v: Vehicle, comps: list[str], as_of: str) -> list[dict]:
    """Recalls on the same make/model and component but other model years, filed before as_of. Context for a
    possible recall-scope gap (e.g. the ICCU recall covers 2022-2024; this complaint is a 2027). Not shown to the AI."""
    if not comps:
        return []
    placeholders = ",".join("?" * len(comps))
    rows = con.execute(
        f"""SELECT r.campno, r.filed, r.defect, group_concat(DISTINCT rv.year) AS years
            FROM recall_vehicles rv JOIN recalls r USING (campno)
            WHERE rv.make = ? AND rv.model = ? AND rv.comp IN ({placeholders}) AND r.filed < ?
              AND r.campno NOT IN (SELECT campno FROM recall_vehicles WHERE make = ? AND model = ? AND year = ?)
            GROUP BY r.campno ORDER BY r.filed DESC LIMIT 50""",
        (v.make, v.model, *comps, as_of, v.make, v.model, v.year)).fetchall()
    recalls = []
    for row in rows:
        recall = dict(row)
        # group_concat returns one unordered string ("2024,2022"); turn it into a sorted list.
        recall["years"] = sorted(row["years"].split(","))
        recalls.append(recall)
    return recalls


def investigations_for(con: sqlite3.Connection, v: Vehicle, as_of: str) -> list[dict]:
    """Investigations on this vehicle opened before as_of. The recall each led to (campno) is taken from this vehicle's
    own lines: an investigation covering several manufacturers can lead to a different recall for each.
    The closing date and the resulting recall are only returned when they too are before as_of: an investigation
    open on that date had no outcome yet."""
    rows = con.execute(
        """SELECT i.action, i.opened, CASE WHEN i.closed < ? THEN i.closed END AS closed, max(r.campno) AS campno,
                  i.subject, i.summary
           FROM investigation_vehicles iv JOIN investigations i USING (action)
           LEFT JOIN recalls r ON r.campno = iv.campno AND r.filed < ?
           WHERE iv.make = ? AND iv.model = ? AND iv.year = ? AND i.opened < ?
           GROUP BY i.action ORDER BY i.opened DESC""",
        (as_of, as_of, v.make, v.model, v.year, as_of)).fetchall()
    return [dict(row) for row in rows]


def complaint_counts(con: sqlite3.Connection, v: Vehicle, comps: list[str], as_of: str, since: str | None = None,
                     exclude: int | None = None) -> dict:
    """Earlier complaints on the same vehicle that share a top-level component (optionally only those since a date)."""
    if comps:
        placeholders = ",".join("?" * len(comps))
    else:
        placeholders = "''"  # no components: compare against '' rather than leave the IN list empty
    # Neutral values when the optional filters are not given: every ISO date is >= "", and no complaint has odino -1.
    received_from = since or ""
    excluded_odino = exclude or -1
    row = con.execute(
        f"""SELECT count(*) AS total, coalesce(sum(crash), 0) AS crash, coalesce(sum(fire), 0) AS fire,
                   coalesce(sum(injured > 0), 0) AS injury, min(received) AS first, max(received) AS last
            FROM complaints c WHERE make = ? AND model = ? AND year = ? AND received < ? AND received >= ?
              AND odino != ? AND EXISTS (SELECT 1 FROM complaint_components cc
                                         WHERE cc.odino = c.odino AND cc.comp IN ({placeholders}))""",
        (v.make, v.model, v.year, as_of, received_from, excluded_odino, *comps)).fetchone()
    return dict(row)


WORD = re.compile(r"[A-Za-z0-9]{3,}")


def search_complaints(con: sqlite3.Connection, v: Vehicle, query: str, as_of: str, exclude: int | None = None,
                      limit: int = 5) -> list[dict]:
    """Full-text search among earlier complaints on the same vehicle. The query is reduced to plain quoted words,
    so free text (from the AI or a complaint) can never inject FTS syntax."""
    words = WORD.findall(query)[:12]
    if not words:
        return []
    match = " OR ".join(f'"{word}"' for word in words)
    excluded_odino = exclude or -1  # -1: no complaint has that id, so nothing is excluded
    rows = con.execute(
        """SELECT c.odino, c.received, c.crash, c.fire, snippet(complaints_fts, 0, '[', ']', ' … ', 24) AS snippet
           FROM complaints_fts JOIN complaints c ON c.odino = complaints_fts.rowid
           WHERE complaints_fts MATCH ? AND c.make = ? AND c.model = ? AND c.year = ? AND c.received < ?
             AND c.odino != ?
           ORDER BY bm25(complaints_fts) LIMIT ?""",
        (match, v.make, v.model, v.year, as_of, excluded_odino, limit)).fetchall()
    return [dict(row) for row in rows]
