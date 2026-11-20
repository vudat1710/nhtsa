"""Read-only queries. Every evidence query takes `as_of` (the complaint's received date) and only returns records that
existed strictly before it, so the system never sees the future (no look-ahead). This is the only place that rule lives.
"""
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.data.ingest import DB

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


def complaint(con: sqlite3.Connection, odino: int) -> dict | None:
    row = con.execute("SELECT * FROM complaints WHERE odino = ?", (odino,)).fetchone()
    if row is None:
        return None
    comps = con.execute("SELECT component, comp FROM complaint_components WHERE odino = ? ORDER BY component",
                        (odino,)).fetchall()
    return {**dict(row), "components": [r["component"] for r in comps], "comps": sorted({r["comp"] for r in comps})}


def recalls_for(con: sqlite3.Connection, v: Vehicle, as_of: str, comps: list[str]) -> tuple[list[dict], int]:
    """Recalls covering this exact vehicle, filed before as_of. Same-component recalls first, then newest first.
    Returns (up to MAX_RECALLS recalls, total found)."""
    rows = con.execute(
        """SELECT r.*, rv.component, rv.comp FROM recall_vehicles rv JOIN recalls r USING (campno)
           WHERE rv.make = ? AND rv.model = ? AND rv.year = ? AND r.filed < ?""",
        (v.make, v.model, v.year, as_of)).fetchall()
    by_campno: dict[str, dict] = {}
    for r in rows:  # one row per (recall, component); component names can contain commas, so group here, not in SQL
        rec = by_campno.setdefault(r["campno"], {**dict(r), "components": [], "comps": []})
        for key, value in (("components", r["component"]), ("comps", r["comp"])):
            if value not in rec[key]:
                rec[key].append(value)
    out = [{k: v for k, v in rec.items() if k not in ("component", "comp")} for rec in by_campno.values()]
    same = [r for r in out if set(r["comps"]) & set(comps)]
    other = [r for r in out if not set(r["comps"]) & set(comps)]
    ordered = sorted(same, key=lambda r: r["filed"], reverse=True) + sorted(other, key=lambda r: r["filed"],
                                                                            reverse=True)
    return ordered[:MAX_RECALLS], len(ordered)


def investigations_for(con: sqlite3.Connection, v: Vehicle, as_of: str) -> list[dict]:
    rows = con.execute(
        """SELECT DISTINCT i.* FROM investigation_vehicles iv JOIN investigations i USING (action)
           WHERE iv.make = ? AND iv.model = ? AND iv.year = ? AND i.opened < ? ORDER BY i.opened DESC""",
        (v.make, v.model, v.year, as_of)).fetchall()
    return [dict(r) for r in rows]


def complaint_counts(con: sqlite3.Connection, v: Vehicle, comps: list[str], as_of: str, since: str | None = None,
                     exclude: int | None = None) -> dict:
    """Earlier complaints on the same vehicle that share a top-level component (optionally only those since a date)."""
    marks = ",".join("?" * len(comps)) or "''"
    row = con.execute(
        f"""SELECT count(*) AS total, coalesce(sum(crash), 0) AS crash, coalesce(sum(fire), 0) AS fire,
                   coalesce(sum(injured > 0), 0) AS injury, min(received) AS first, max(received) AS last
            FROM complaints c WHERE make = ? AND model = ? AND year = ? AND received < ? AND received >= ?
              AND odino != ? AND EXISTS (SELECT 1 FROM complaint_components cc
                                         WHERE cc.odino = c.odino AND cc.comp IN ({marks}))""",
        (v.make, v.model, v.year, as_of, since or "", exclude or -1, *comps)).fetchone()
    return dict(row)


WORD = re.compile(r"[A-Za-z0-9]{3,}")


def search_complaints(con: sqlite3.Connection, v: Vehicle, query: str, as_of: str, exclude: int | None = None,
                      limit: int = 5) -> list[dict]:
    """Full-text search among earlier complaints on the same vehicle. The query is reduced to plain quoted words,
    so free text (from the AI or a complaint) can never inject FTS syntax."""
    words = WORD.findall(query)[:12]
    if not words:
        return []
    match = " OR ".join(f'"{w}"' for w in words)
    rows = con.execute(
        """SELECT c.odino, c.received, c.crash, c.fire, snippet(complaints_fts, 0, '[', ']', ' … ', 24) AS snippet
           FROM complaints_fts JOIN complaints c ON c.odino = complaints_fts.rowid
           WHERE complaints_fts MATCH ? AND c.make = ? AND c.model = ? AND c.year = ? AND c.received < ?
             AND c.odino != ?
           ORDER BY bm25(complaints_fts) LIMIT ?""",
        (match, v.make, v.model, v.year, as_of, exclude or -1, limit)).fetchall()
    return [dict(r) for r in rows]
