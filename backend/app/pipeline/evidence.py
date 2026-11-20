"""Step 2 (code): evidence. Collects everything the AI may use and every number the analyst sees. No AI here."""
import re
import sqlite3
from datetime import date, timedelta

from app.data import queries
from app.models import Complaint, Evidence, Intake, InvestigationItem, RecallItem, Stats

CAMPNO = r"(\d{2})\s?V\s?-?\s?(\d{3})"
# "replaced by NHTSA recall number 22V-635" / "superseded by recall 16V-352" -> this recall was replaced by that one.
# Requires "by (NHTSA) recall" so "parts replaced by GM dealers as part of recall 14V-047" does not count.
REPLACED_BY = re.compile(r"(?:replaced|superseded) by (?:NHTSA )?recall(?: number| campaign)? " + CAMPNO, re.I)
# "supersedes previous recall campaign 11V-594" / "expands and supersedes recall 14V-809": that one was replaced.
SUPERSEDES = re.compile(r"supersedes (?:the )?(?:previous )?recall(?: campaign)? " + CAMPNO, re.I)


def link_replacements(recalls: list[RecallItem]) -> None:
    """Mark candidates replaced by another candidate, from either recall's own wording."""
    ids = {r.campno for r in recalls}
    for r in recalls:
        text = f"{r.remedy} {r.defect}"
        for yy, nnn in REPLACED_BY.findall(text):
            if (newer := f"{yy}V{nnn}000") in ids and newer != r.campno:
                r.replaced_by = newer
        for yy, nnn in SUPERSEDES.findall(text):
            older = next((o for o in recalls if o.campno == f"{yy}V{nnn}000"), None)
            if older and older.campno != r.campno:
                older.replaced_by = r.campno


def gather(con: sqlite3.Connection, c: Complaint, it: Intake) -> Evidence:
    v = queries.Vehicle(c.make, c.model, c.year)
    comps = [x for x in c.comps if x != "UNKNOWN OR OTHER"]
    rows, total = ([], 0) if "unknown_year" in it.flags else queries.recalls_for(con, v, c.received, comps)
    recalls = [RecallItem(
        campno=r["campno"], filed=r["filed"], influenced_by=r["influenced_by"] or "",
        units=int(r["units"]) if r["units"] else None, components=r["components"], comps=r["comps"],
        same_component=bool(set(r["comps"]) & set(comps)), defect=r["defect"] or "",
        consequence=r["consequence"] or "", remedy=r["remedy"] or "") for r in rows]
    link_replacements(recalls)

    dates = earlier_complaint_dates(con, v, comps, c.received, c.odino)
    for r in recalls:
        r.complaints_since = sum(d >= r.filed for d in dates) if r.same_component else 0
    year_ago = (date.fromisoformat(c.received) - timedelta(days=365)).isoformat()
    counts = queries.complaint_counts(con, v, comps, c.received, exclude=c.odino) if comps else \
        {"total": 0, "crash": 0, "fire": 0, "injury": 0, "first": None, "last": None}
    invs = [] if "unknown_year" in it.flags else queries.investigations_for(con, v, c.received)
    return Evidence(
        recalls=recalls, recalls_total=total,
        investigations=[InvestigationItem(action=i["action"], opened=i["opened"], closed=i["closed"],
                                          campno=i["campno"], subject=(i["subject"] or "").strip()) for i in invs],
        stats=Stats(**counts, last_12_months=sum(d >= year_ago for d in dates)))


def earlier_complaint_dates(con: sqlite3.Connection, v: queries.Vehicle, comps: list[str], as_of: str,
                            exclude: int | None) -> list[str]:
    if not comps:
        return []
    marks = ",".join("?" * len(comps))
    return [r[0] for r in con.execute(
        f"""SELECT DISTINCT c.received, c.odino FROM complaints c JOIN complaint_components cc USING (odino)
            WHERE c.make = ? AND c.model = ? AND c.year = ? AND c.received < ? AND c.odino != ?
              AND cc.comp IN ({marks})""", (v.make, v.model, v.year, as_of, exclude or -1, *comps))]
