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
    candidate_ids = {recall.campno for recall in recalls}
    for recall in recalls:
        text = f"{recall.remedy} {recall.defect}"
        # "replaced by recall X": this recall was replaced by the newer X
        for yy, nnn in REPLACED_BY.findall(text):
            newer = f"{yy}V{nnn}000"
            if newer in candidate_ids and newer != recall.campno:
                recall.replaced_by = newer
        # "supersedes recall X": the older X was replaced by this recall
        for yy, nnn in SUPERSEDES.findall(text):
            older_campno = f"{yy}V{nnn}000"
            older = next((other for other in recalls if other.campno == older_campno), None)
            if older and older.campno != recall.campno:
                older.replaced_by = recall.campno


def gather(con: sqlite3.Connection, complaint: Complaint, intake: Intake) -> Evidence:
    vehicle = queries.Vehicle(complaint.make, complaint.model, complaint.year)
    comps = [comp for comp in complaint.comps if comp != "UNKNOWN OR OTHER"]
    # With the model year unknown we cannot tell which recalls or investigations cover this vehicle.
    year_unknown = "unknown_year" in intake.flags

    # Candidate recalls
    if year_unknown:
        rows, total = [], 0
    else:
        rows, total = queries.recalls_for(con, vehicle, complaint.received, comps)
    recalls = []
    for row in rows:
        units = int(row["units"]) if row["units"] else None
        same_component = bool(set(row["comps"]) & set(comps))
        recalls.append(RecallItem(
            campno=row["campno"], filed=row["filed"], influenced_by=row["influenced_by"] or "", units=units,
            components=row["components"], comps=row["comps"], same_component=same_component,
            defect=row["defect"] or "", consequence=row["consequence"] or "", remedy=row["remedy"] or ""))
    link_replacements(recalls)
    campnos = [recall.campno for recall in recalls]
    years_by_campno = queries.recall_model_years(con, campnos, complaint.make, complaint.model)
    for recall in recalls:
        recall.model_years = years_by_campno.get(recall.campno, [])

    # Earlier complaints on this vehicle and component: how many arrived after each recall was filed
    dates = earlier_complaint_dates(con, vehicle, comps, complaint.received, complaint.odino)
    for recall in recalls:
        if recall.same_component:
            recall.complaints_since = len([d for d in dates if d >= recall.filed])
        else:
            recall.complaints_since = 0

    # Complaint statistics
    year_ago = (date.fromisoformat(complaint.received) - timedelta(days=365)).isoformat()
    if comps:
        counts = queries.complaint_counts(con, vehicle, comps, complaint.received, exclude=complaint.odino)
    else:
        counts = {"total": 0, "crash": 0, "fire": 0, "injury": 0, "first": None, "last": None}
    last_12_months = len([d for d in dates if d >= year_ago])

    # Investigations
    investigation_rows = [] if year_unknown else queries.investigations_for(con, vehicle, complaint.received)
    investigations = []
    for row in investigation_rows:
        investigations.append(InvestigationItem(action=row["action"], opened=row["opened"], closed=row["closed"],
                                                campno=row["campno"], subject=(row["subject"] or "").strip()))

    return Evidence(recalls=recalls, recalls_total=total, investigations=investigations,
                    stats=Stats(**counts, last_12_months=last_12_months))


def earlier_complaint_dates(con: sqlite3.Connection, vehicle: queries.Vehicle, comps: list[str], as_of: str,
                            exclude: int | None) -> list[str]:
    """Received dates of earlier complaints on this vehicle sharing a component, one per complaint."""
    if not comps:
        return []
    marks = ",".join("?" * len(comps))
    rows = con.execute(
        f"""SELECT DISTINCT c.received, c.odino FROM complaints c JOIN complaint_components cc USING (odino)
            WHERE c.make = ? AND c.model = ? AND c.year = ? AND c.received < ? AND c.odino != ?
              AND cc.comp IN ({marks})""", (vehicle.make, vehicle.model, vehicle.year, as_of, exclude or -1, *comps))
    return [row[0] for row in rows]
