"""Step 2 (code): evidence. Collects everything the AI may use and every number the analyst sees. No AI here."""
import re
import sqlite3
from datetime import date, timedelta

from app.data import queries
from app.models import Complaint, Evidence, Intake, InvestigationItem, RecallItem, Stats

# A recall number as written in recall texts: 24V-868, 11E-016, 24V868000. The letter is the recall type; these six
# are the ones in NHTSA's recall files.
RECALL_NUMBER = re.compile(r"\b(\d{2})\s?-?\s?([VETCIX])\s?-?\s?(\d{3})(?:\s?-?\s?000)?\b", re.I)
SENTENCE_END = re.compile(r"(?<=[.;])(?<!\bno\.)\s+", re.I)  # not after "Recall No."
NUMBER_AHEAD = r"(?=\s*\d{2}\s?-?\s?[VETCIX]\s?-?\s?\d{3})"
# How recall texts state a replacement, checked in this order per sentence. Each rule says which recalls the sentence
# names (all in the sentence, or those after the phrase) and whether they are newer or older than this recall.
REPLACEMENT_RULES = [
    # "18V-122 was superseded by this recall", "that recall will be superseded by this one": named ones are older
    (re.compile(r"(?:superseded|replaced) by this\b", re.I), "sentence", "older"),
    # "Recall 21V469 supersedes this recall", "a new recall, number 21V-504 that supersedes this recall"
    (re.compile(r"(?:supersedes?|replaces?) this\b", re.I), "sentence", "newer"),
    # "superseded by safety recall campaign 11E-016", "HAS BEEN SUPERSEDED (PLEASE SEE 07V401)",
    # "replaced by NHTSA recall number 24V-868", "replaced by 25V798". "replaced by" needs a recall word or number
    # next, so "parts replaced by GM dealers as part of recall 14V-047" does not count.
    (re.compile(r"\bsuperseded\b|replaced by (?:the )?(?:NHTSA |safety )?(?:recall|campaign)|replaced by"
                + NUMBER_AHEAD, re.I), "after", "newer"),
    # "supersedes recalls 13V-029 and 14V-147", "WILL SUPERSEDE AND EXPAND A PREVIOUS SAFETY RECALL (PLEASE SEE
    # 07V-104)", "supersedes and expands NHTSA recall number 22V-486"
    (re.compile(r"\bsupersed(?:e|es|ing)\b", re.I), "after", "older"),
]


def replacement_mentions(text: str) -> tuple[list[str], list[str]]:
    """Recalls a recall text names as its replacement (newer) and as replaced by it (older), per sentence."""
    found: dict[str, list[str]] = {"newer": [], "older": []}
    for sentence in SENTENCE_END.split(text):
        for pattern, where, direction in REPLACEMENT_RULES:
            match = pattern.search(sentence)
            if match is None:
                continue
            named = sentence if where == "sentence" else sentence[match.end():]
            for yy, kind, nnn in RECALL_NUMBER.findall(named):
                found[direction].append(f"{yy}{kind.upper()}{nnn}000")
            break
    return found["newer"], found["older"]


def link_replacements(recalls: list[RecallItem]) -> None:
    """Mark candidates replaced by another candidate, from either recall's own wording. A replacement is never filed
    before the recall it replaces, and two recalls never replace each other."""
    by_campno = {recall.campno: recall for recall in recalls}

    def link(older_campno: str, newer_campno: str) -> None:
        older = by_campno.get(older_campno)
        newer = by_campno.get(newer_campno)
        if older is None or newer is None or older is newer or newer.filed < older.filed:
            return
        if newer.replaced_by == older.campno:
            return
        older.replaced_by = newer.campno

    for recall in recalls:
        newer_campnos, older_campnos = replacement_mentions(f"{recall.remedy} {recall.defect}")
        for newer_campno in newer_campnos:
            link(recall.campno, newer_campno)
        for older_campno in older_campnos:
            link(older_campno, recall.campno)


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
    built = queries.recall_build_dates(con, campnos, vehicle)
    for recall in recalls:
        recall.model_years = years_by_campno.get(recall.campno, [])
        recall.built_from, recall.built_to = built.get(recall.campno, (None, None))

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
