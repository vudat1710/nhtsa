"""What the analyst sees for one ticket: what it is, why (in field-quality terms), the pattern, and what to do.

Built from a verified Result only: every quote shown here already passed the verifier; every number comes from the
evidence step. The wording is deliberately the analyst's ("covered by recall", "the owner says"), not the system's.
"""
import re
from typing import Literal

from pydantic import BaseModel

from app.models import Complaint, RecallCheck, RecallItem, Result
from app.store.tickets import IssueKind, Tickets
from app.workspace.messages import covers, display_campno, owner_info_request, owner_recall_reply, plain_defect

ActionId = Literal["link_close", "request_info", "add_to_issue", "new_issue", "monitor", "close_no_action"]


class QuotePair(BaseModel):
    owner: str
    recall: str


class Why(BaseModel):
    text: str
    quotes: list[QuotePair] = []
    owner_quotes: list[dict] = []        # earlier complaints: {odino, quote}


class RecallCard(BaseModel):
    campno: str
    display: str
    filed: str
    covers: str
    problem: str
    consequence: str
    remedy: str
    units: int | None
    replaced: list[str] = []             # older recalls this one replaced


class Pattern(BaseModel):
    sentence: str
    total: int
    before_recall: int | None
    after_recall: int | None
    last_12_months: int
    crash: int
    fire: int
    injury: int


class ActionOption(BaseModel):
    id: ActionId
    label: str
    primary: bool = False
    campno: str | None = None
    issue_id: int | None = None
    issue_title: str | None = None
    issue_kind: IssueKind | None = None
    issue_comp: str | None = None
    message: str | None = None


class Suggestion(BaseModel):
    result_id: str
    outcome: str
    headline: str
    confidence: str
    check_note: str | None               # shown when the analyst should double-check (rules only / medium / low)
    severity: list[str]
    summary: str
    recall: RecallCard | None
    why: list[Why]
    pattern: Pattern | None
    questions: list[str]
    actions: list[ActionOption]


def part(comp: str) -> str:
    return comp.lower() if comp else "this part"


def gist(text: str, limit: int = 75) -> str:
    """The first clause of a recall's problem sentence, short enough for an inbox line."""
    first = text.split(". ")[0].split(", which")[0].rstrip(".")
    return first if len(first) <= limit else first[:limit].rsplit(" ", 1)[0] + "…"


def checks_for(r: Result, campno: str | None, verdict: str | None = None) -> list[RecallCheck]:
    if not r.judgment or not campno:
        return []
    return [c for c in r.judgment.checks if c.campno == campno and (verdict is None or c.verdict == verdict)]


def pairs(checks: list[RecallCheck]) -> list[QuotePair]:
    return [QuotePair(owner=c.complaint_quote, recall=c.recall_quote) for c in checks]


def recall_card(r: RecallItem, c: Complaint, replaced: list[str]) -> RecallCard:
    return RecallCard(campno=r.campno, display=display_campno(r.campno), filed=r.filed, covers=covers(r, c),
                      problem=plain_defect(r.defect), consequence=r.consequence, remedy=r.remedy, units=r.units,
                      replaced=[display_campno(x) for x in replaced])


def main_comp(c: Complaint, fallback: str = "") -> str:
    comps = [x for x in c.comps if x != "UNKNOWN OR OTHER"]
    return comps[0] if comps else fallback


def issue_option(tickets: Tickets, kind: IssueKind, c: Complaint, comp: str, campno: str | None,
                 primary: bool) -> ActionOption:
    existing = tickets.matching_issue(kind, c.make, c.model, comp, campno)
    if existing:
        return ActionOption(id="add_to_issue", primary=primary, issue_id=existing.id, issue_title=existing.title,
                            issue_kind=kind, label=f"Escalate: add to “{existing.title}” "
                                                   f"({len(existing.complaints)} complaints)")
    title = (f"Recall {display_campno(campno)}: complaints after the remedy ({c.make.title()} {c.model.title()})"
             if kind == "remedy_concern" else f"{c.make.title()} {c.model.title()} {part(comp)}: possible new defect")
    return ActionOption(id="new_issue", primary=primary, issue_title=title, issue_kind=kind, issue_comp=comp,
                        campno=campno, label=f"Escalate: open emerging issue “{title}”")


def pattern_of(r: Result, recall: RecallItem | None, comp: str) -> Pattern | None:
    c, d, s = r.complaint, r.decision, r.evidence.stats
    if not s.total:
        return None
    before = after = None
    if recall and recall.same_component and d.outcome == "known_recall":
        before, after = s.total - recall.complaints_since, recall.complaints_since
        sentence = (f"{s.total} earlier complaints on the {c.make.title()} {c.model.title()} about the "
                    f"{part(comp)}: {before} before recall {display_campno(recall.campno)}, {after} after it.")
        if "after_remedy" in d.flags:
            sentence += (" Complaints keep coming after the fix was released: it may not be holding, or cars are not "
                         "being repaired (the data can't tell which).")
    else:
        sentence = (f"{s.total} earlier complaints on this model year about the {part(comp)}, "
                    f"{s.last_12_months} in the 12 months before this one.")
    return Pattern(sentence=sentence, total=s.total, before_recall=before, after_recall=after,
                   last_12_months=s.last_12_months, crash=s.crash, fire=s.fire, injury=s.injury)


PATTERN_MIN = 3        # similar complaints on this model year in 12 months before an unmatched complaint is escalated
SIMILAR_MIN = 2        # earlier complaints the AI found describing the same failure (one is not yet a pattern)
SHARED_WORDS_MIN = 3   # uncommon words an other-year recall must share with the complaint ("factory-installed" ≠ same)
# Thresholds are product judgments; tune them on the share of escalations engineers confirm.
GENERIC = set("""vehicle vehicles recall recalling certain manufactured equipped affected failure problem warning
increase increases increasing driving electrical electronic software module system systems control controller
replace replaced dealers condition conditions without operation operating potentially resulting factory installed
standard federal comply requirements""".split())
GENERIC_ACRONYMS = {"VIN", "NHTSA", "MPH", "USA", "LLC", "DTC", "FMVSS", "OEM", "SUV"}


def shares_failure_words(complaint: str, defect: str, vehicle_words: set[str] = frozenset()) -> bool:
    """Cheap code check that an other-year recall is about the same thing: a shared acronym (e.g. 'ICCU') or two
    shared uncommon long words. Only gates 'possibly related' context; the analyst decides."""
    def shouting(t: str) -> bool:  # older NHTSA texts are ALL CAPS: every word would look like an acronym
        letters = [ch for ch in t if ch.isalpha()]
        return bool(letters) and sum(ch.isupper() for ch in letters) / len(letters) > 0.5

    def acronyms(t: str) -> set[str]:
        if shouting(t):
            return set()
        return {w for w in re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", t)
                if w not in GENERIC_ACRONYMS and w.lower() not in vehicle_words}

    def long_words(t: str) -> set[str]:
        return {w for w in re.findall(r"[a-z]{7,}", t.lower()) if w not in GENERIC and w not in vehicle_words}
    return (bool(acronyms(complaint) & acronyms(defect))
            or len(long_words(complaint) & long_words(defect)) >= SHARED_WORDS_MIN)


def related_other_years(r: Result, candidates: list[dict], keep: int = 3) -> list[dict]:
    """Filter first, then keep the newest few: a popular model has many unrelated recalls on a broad component
    (the 2022-2024 ICCU recall was crowded out of a top-5 list before this filter ran)."""
    c = r.complaint
    vehicle_words = {w.lower() for w in re.findall(r"[A-Za-z0-9]+", f"{c.make} {c.model}")}
    return [x for x in candidates if shares_failure_words(c.text, x["defect"], vehicle_words)][:keep]


def escalation_reasons(r: Result, related: list[dict]) -> list[str]:
    """Why an unmatched complaint deserves engineering's time. None of these -> record and watch instead.
    Escalating every unmatched complaint would drown engineers (most single reports are isolated)."""
    c, s = r.complaint, r.evidence.stats
    reasons = []
    if c.crash or c.fire or c.injured:
        reasons.append("the owner reports a crash, fire or injury")
    if s.last_12_months >= PATTERN_MIN:
        reasons.append(f"{s.last_12_months} similar complaints on this model year in the last 12 months")
    if r.judgment and len(r.judgment.similar) >= SIMILAR_MIN:
        reasons.append(f"{len(r.judgment.similar)} earlier owners described the same failure")
    if related:
        reasons.append("the same part is recalled on other model years (the recall may need to be extended)")
    return reasons


def suggest(r: Result, tickets: Tickets, related: list[dict] = ()) -> Suggestion:
    """related: recalls on the same make/model/part but other model years (queries.recalls_other_years)."""
    c, d, ev, j = r.complaint, r.decision, r.evidence, r.judgment
    severity = [x for x, on in (("crash", c.crash), ("fire", c.fire), ("injury", c.injured)) if on]
    why: list[Why] = []
    actions: list[ActionOption] = []
    recall = ev.recall(d.campno) if d.campno else None
    replaced = [x.campno for x in ev.recalls if recall and x.replaced_by == recall.campno]
    card = recall_card(recall, c, replaced) if recall else None
    comp = main_comp(c, recall.comps[0] if recall else "")

    if d.outcome == "known_recall" and recall:
        disp = display_campno(recall.campno)
        headline = f"Covered by recall {disp}: {gist(plain_defect(recall.defect))}"
        why.append(Why(text=f"This vehicle is covered: the {c.year} {c.model.title()} is in recall {disp} "
                            f"({card.covers})."))
        why.append(Why(text="Same problem: what the owner describes is what the recall says can happen.",
                       quotes=pairs(checks_for(r, recall.campno, "same"))))
        if replaced:
            why.append(Why(text=f"Recall {', '.join(card.replaced)} was replaced by {disp}: use {disp}'s remedy."))
        if not recall.same_component:
            why.append(Why(text=f"The owner filed it under {', '.join(c.comps) or 'no component'}; the recall lists "
                                f"{', '.join(recall.comps)}. Owners often pick a different part."))
        link = ActionOption(id="link_close", primary=True, campno=recall.campno,
                            label=f"Link to recall {disp} and reply to the owner",
                            message=owner_recall_reply(c, recall, "after_remedy" in d.flags))
        if "after_remedy" in d.flags:
            flag = issue_option(tickets, "remedy_concern", c, comp, recall.campno, primary=False)
            link.issue_id, link.issue_title, link.issue_kind, link.issue_comp = (flag.issue_id, flag.issue_title,
                                                                                  "remedy_concern", comp)
            link.label += " + flag the remedy to engineering"
        actions.append(link)
        actions.append(issue_option(tickets, "new_defect", c, comp, None, primary=False))
    elif d.outcome in ("related_different", "possible_new"):
        if d.outcome == "related_different":
            diff = next((ch for ch in (j.checks if j else []) if ch.verdict == "different"), None)
            other = ev.recall(diff.campno) if diff else None
            disp = display_campno(other.campno) if other else "?"
            comp = other.comps[0] if other else comp
            what = f"Not covered: recall {disp} is a different {part(comp)} failure"
            why.append(Why(text=f"Recall {disp} covers the {part(comp)} on this vehicle, but describes a different "
                                "failure than the owner reports.", quotes=pairs([diff] if diff else [])))
            why.append(Why(text="No other recall on this vehicle describes what the owner reports."))
        else:
            what = "No recall covers this"
            n = len(ev.recalls)
            why.append(Why(text=f"None of the {n} recalls on the {c.year} {c.model.title()} describes this failure."
                           if n else f"No recall covered the {c.year} {c.model.title()} when this complaint arrived."))
        if j and j.similar:
            why.append(Why(text="Other owners described the same failure before this complaint:",
                           owner_quotes=[{"odino": x.odino, "quote": x.quote} for x in j.similar]))
        for rel in related:
            years = rel["years"][0] if len(rel["years"]) == 1 else f"{rel['years'][0]}–{rel['years'][-1]}"
            why.append(Why(text=f"Possibly related: recall {display_campno(rel['campno'])} covers the {part(comp)} on "
                                f"{years} {c.model.title()}, not the {c.year}. Its problem: "
                                f"{gist(plain_defect(rel['defect']), 140)}. Check whether it is the same failure."))
        reasons = escalation_reasons(r, related)
        if reasons:
            headline = f"{what}: possible new defect" + ("" if d.outcome == "related_different" else f" ({part(comp)})")
            why.append(Why(text="Worth engineering's time: " + "; ".join(reasons) + "."))
            actions.append(issue_option(tickets, "new_defect", c, comp, None, primary=True))
            actions.append(ActionOption(id="monitor", label="Record and watch instead (no escalation yet)"))
        else:
            headline = f"{what}: single report, record and watch"
            n12, ns = ev.stats.last_12_months, len(j.similar) if j else 0
            why.append(Why(text=f"Not enough yet to involve engineering: no crash, fire or injury; {n12} similar "
                                f"complaint{'' if n12 == 1 else 's'} on this model year in 12 months (escalate at "
                                f"{PATTERN_MIN}); {ns} earlier owner{'' if ns == 1 else 's'} describing the same "
                                f"failure (escalate at {SIMILAR_MIN}). If more owners report it, it will be suggested "
                                "for escalation."))
            actions.append(ActionOption(id="monitor", primary=True,
                                        label="Record and watch for more reports (no escalation yet)"))
            actions.append(issue_option(tickets, "new_defect", c, comp, None, primary=False))
    else:  # needs_info
        probable = ev.recall(d.campno) if d.campno else None
        headline = "Not enough detail to tell" + (f": possibly recall {display_campno(probable.campno)}"
                                                  if probable else "")
        if "unknown_year" in r.intake.flags:
            why.append(Why(text="The model year is missing, so we can't tell which recalls cover this vehicle."))
        else:
            why.append(Why(text="The owner's description is too short or too general to match it to a recall."))
        if probable:
            why.append(Why(text=f"It may be recall {display_campno(probable.campno)}:",
                           quotes=pairs(checks_for(r, probable.campno))))
            card = recall_card(probable, c, [])
        actions.append(ActionOption(id="request_info", primary=True, label="Ask the owner for details",
                                    message=owner_info_request(c, j.questions if j else [])))
        if probable:
            actions.append(ActionOption(id="link_close", campno=probable.campno,
                                        label=f"Link to recall {display_campno(probable.campno)} anyway",
                                        message=owner_recall_reply(c, probable, False)))

    if d.outcome != "needs_info":
        actions.append(ActionOption(id="request_info", label="Ask the owner for details",
                                    message=owner_info_request(c, j.questions if j else [])))
    actions.append(ActionOption(id="close_no_action", label="Close: not a safety defect"))

    if d.source == "fallback":
        check_note = ("The AI could not complete this check; this suggestion is based on simple rules only. "
                      "Please read the complaint and the recall before acting.")
    elif d.source == "rules":
        check_note = "Suggestion based on simple rules only. Please check before acting."
    elif d.confidence != "high":
        check_note = f"{d.confidence.title()} confidence: please confirm before acting."
    else:
        check_note = None
    return Suggestion(result_id=r.id, outcome=d.outcome, headline=headline, confidence=d.confidence,
                      check_note=check_note, severity=severity, summary=j.summary if j else " ".join(d.reasons),
                      recall=card, why=why, pattern=pattern_of(r, recall, comp),
                      questions=j.questions if j else [], actions=actions)
