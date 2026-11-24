"""What the analyst sees for one ticket: what it is, why (in field-quality terms), the pattern, and what to do.

Built from a verified Result only: every quote shown here already passed the verifier; every number comes from the
evidence step. The wording is deliberately the analyst's ("covered by recall", "the owner says"), not the system's.
"""
import re
from typing import Literal

from pydantic import BaseModel

from app.models import Complaint, RecallCheck, RecallItem, Result
from app.store.tickets import IssueKind, Tickets
from app.workspace.messages import (
    build_window,
    covers,
    display_campno,
    owner_info_request,
    owner_recall_reply,
    plain_defect,
)

ActionId = Literal["link_close", "request_info", "add_to_issue", "new_issue", "monitor", "close_no_action", "recheck",
                   "reopen"]


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
    built: str | None = None             # '2024 models built October 4, 2021 – October 9, 2024', when published
    problem: str
    consequence: str
    remedy: str
    units: int | None
    replaced: list[str] = []             # older recalls this one replaced


class Pattern(BaseModel):
    sentence: str
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
    summary_by: Literal["ai", "rules"] = "rules"   # "ai": the AI's own words; only its quotes and numbers were checked
    recall: RecallCard | None
    why: list[Why]
    pattern: Pattern | None
    questions: list[str]
    actions: list[ActionOption]


def part(comp: str) -> str:
    return comp.lower() if comp else "this part"


def gist(text: str, limit: int = 75) -> str:
    """The first clause of a recall's problem sentence, short enough for an inbox line."""
    first_sentence = text.split(". ")[0]
    first_clause = first_sentence.split(", which")[0].rstrip(".")
    if len(first_clause) <= limit:
        return first_clause
    # Too long: cut at the last whole word that fits.
    return first_clause[:limit].rsplit(" ", 1)[0] + "…"


def checks_for(result: Result, campno: str | None, verdict: str | None = None) -> list[RecallCheck]:
    """The AI's checks of one recall, optionally only those with the given verdict."""
    if not result.judgment or not campno:
        return []
    matching = []
    for check in result.judgment.checks:
        if check.campno != campno:
            continue
        if verdict is None or check.verdict == verdict:
            matching.append(check)
    return matching


def pairs(checks: list[RecallCheck]) -> list[QuotePair]:
    return [QuotePair(owner=check.complaint_quote, recall=check.recall_quote) for check in checks]


def recall_card(recall: RecallItem, complaint: Complaint, replaced: list[str]) -> RecallCard:
    return RecallCard(campno=recall.campno,
                      display=display_campno(recall.campno),
                      filed=recall.filed,
                      covers=covers(recall, complaint),
                      built=build_window(recall, complaint),
                      problem=plain_defect(recall.defect),
                      consequence=recall.consequence,
                      remedy=recall.remedy,
                      units=recall.units,
                      replaced=[display_campno(campno) for campno in replaced])


def main_comp(complaint: Complaint, fallback: str = "") -> str:
    comps = [comp for comp in complaint.comps if comp != "UNKNOWN OR OTHER"]
    return comps[0] if comps else fallback


def issue_option(tickets: Tickets, kind: IssueKind, complaint: Complaint, comp: str, campno: str | None,
                 primary: bool) -> ActionOption:
    """Escalate to the open emerging issue this complaint belongs to, or propose opening a new one."""
    vehicle = f"{complaint.make.title()} {complaint.model.title()}"
    existing = tickets.matching_issue(kind, complaint.make, complaint.model, comp, campno)
    if existing:
        label = f"Escalate: add to “{existing.title}” ({len(existing.complaints)} complaints)"
        return ActionOption(id="add_to_issue", primary=primary, issue_id=existing.id, issue_title=existing.title,
                            issue_kind=kind, label=label)

    if kind == "remedy_concern":
        title = f"Recall {display_campno(campno)}: complaints after the remedy ({vehicle})"
    else:
        title = f"{vehicle} {part(comp)}: possible new defect"
    return ActionOption(id="new_issue", primary=primary, issue_title=title, issue_kind=kind, issue_comp=comp,
                        campno=campno, label=f"Escalate: open emerging issue “{title}”")


def pattern_of(result: Result, recall: RecallItem | None, comp: str) -> Pattern | None:
    complaint = result.complaint
    decision = result.decision
    stats = result.evidence.stats
    if not stats.total:
        return None

    if recall and recall.same_component and decision.outcome == "known_recall":
        # Same part as the recall: split the earlier complaints into before and after it was filed.
        after = recall.complaints_since
        before = stats.total - after
        vehicle = f"{complaint.make.title()} {complaint.model.title()}"
        sentence = (f"{stats.total} earlier complaints on the {vehicle} about the {part(comp)}: "
                    f"{before} before recall {display_campno(recall.campno)}, {after} after it.")
        if "after_remedy" in decision.flags:
            sentence += (" Complaints keep coming after the fix was released: it may not be holding, or cars are not "
                         "being repaired (the data can't tell which).")
    else:
        sentence = (f"{stats.total} earlier complaints on this model year about the {part(comp)}, "
                    f"{stats.last_12_months} in the 12 months before this one.")
    return Pattern(sentence=sentence, crash=stats.crash, fire=stats.fire, injury=stats.injury)


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
    """Cheap code check that an other-year recall is about the same thing: a shared acronym (e.g. 'ICCU') or at least
    SHARED_WORDS_MIN shared uncommon long words. Only gates 'possibly related' context; the analyst decides.
    vehicle_words (the make and model, e.g. 'ioniq') never count as shared failure words."""
    def shouting(text: str) -> bool:
        letters = [ch for ch in text if ch.isalpha()]
        if not letters:
            return False
        uppercase = [ch for ch in letters if ch.isupper()]
        return len(uppercase) / len(letters) > 0.5

    def acronyms(text: str) -> set[str]:
        # Older NHTSA texts are ALL CAPS: every word would look like an acronym.
        if shouting(text):
            return set()
        found = set()
        for word in re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", text):
            if word in GENERIC_ACRONYMS or word.lower() in vehicle_words:
                continue
            found.add(word)
        return found

    def long_words(text: str) -> set[str]:
        found = set()
        for word in re.findall(r"[a-z]{7,}", text.lower()):
            if word in GENERIC or word in vehicle_words:
                continue
            found.add(word)
        return found

    if acronyms(complaint) & acronyms(defect):
        return True
    shared_long_words = long_words(complaint) & long_words(defect)
    return len(shared_long_words) >= SHARED_WORDS_MIN


def related_other_years(result: Result, candidates: list[dict], keep: int = 3) -> list[dict]:
    """Filter first, then keep the newest few: a popular model has many unrelated recalls on a broad component
    (the 2022-2024 ICCU recall was crowded out of a top-5 list before this filter ran)."""
    complaint = result.complaint
    vehicle_name = f"{complaint.make} {complaint.model}"
    vehicle_words = {word.lower() for word in re.findall(r"[A-Za-z0-9]+", vehicle_name)}
    related = []
    for candidate in candidates:
        if shares_failure_words(complaint.text, candidate["defect"], vehicle_words):
            related.append(candidate)
    return related[:keep]


def escalation_reasons(result: Result, related: list[dict]) -> list[str]:
    """Why an unmatched complaint deserves engineering's time. None of these -> record and watch instead.
    Escalating every unmatched complaint would drown engineers (most single reports are isolated)."""
    complaint = result.complaint
    stats = result.evidence.stats
    reasons = []
    if complaint.crash or complaint.fire or complaint.injured:
        reasons.append("the owner reports a crash, fire or injury")
    if stats.last_12_months >= PATTERN_MIN:
        reasons.append(f"{stats.last_12_months} similar complaints on this model year in the last 12 months")
    if result.judgment and len(result.judgment.similar) >= SIMILAR_MIN:
        reasons.append(f"{len(result.judgment.similar)} earlier owners described the same failure")
    if related:
        reasons.append("the same part is recalled on other model years (the recall may need to be extended)")
    return reasons


def also_fitting(result: Result, matched: RecallItem) -> list[RecallItem]:
    """Other recalls the AI also judged the same failure, in the AI's order (its best fit first, as the rules pick).
    A recall replaced by another fitting one is left out: the "replaced by" line already explains it."""
    if not result.judgment:
        return []
    same_ids = [check.campno for check in result.judgment.checks if check.verdict == "same"]
    others = []
    for campno in dict.fromkeys(same_ids):
        recall = result.evidence.recall(campno)
        if recall and campno != matched.campno and recall.replaced_by not in same_ids:
            others.append(recall)
    return others


def recalls_to_check(result: Result) -> list[RecallItem]:
    """Without a checked AI answer: the same-component recalls no other candidate replaced, newest first (at most 3).
    Read first, never a match."""
    evidence = result.evidence
    candidate_ids = {recall.campno for recall in evidence.recalls}
    return [recall for recall in evidence.recalls
            if recall.same_component and recall.replaced_by not in candidate_ids][:3]


def not_checked(result: Result, tickets: Tickets, can_recheck: bool, why: list[Why],
                actions: list[ActionOption]) -> str:
    """No checked AI answer: say so, list the same-component recalls as the ones to read first (never as a match),
    and offer to check again. Returns the headline."""
    complaint = result.complaint
    decision = result.decision
    evidence = result.evidence
    failed = "could not check" if decision.source == "fallback" else "is off and did not check"
    why.append(Why(text=f"The AI {failed} this complaint, so no recall was compared with what the owner describes. "
                        "A recall on the same part can still be about a different failure."))
    to_check = recalls_to_check(result)
    if to_check:
        listed = "; ".join(f"{display_campno(recall.campno)}: {gist(plain_defect(recall.defect))}"
                           for recall in to_check)
        why.append(Why(text=f"Recalls on the same part, to read first: {listed}."))
    else:
        why.append(Why(text=f"None of the {len(evidence.recalls)} recalls on this vehicle is filed under the same "
                            "part; read them before deciding."))
    comp = main_comp(complaint)
    if decision.escalate:
        why.append(Why(text="A crash, fire or injury is reported: send it to engineering now; the recall check can "
                            "follow."))
        actions.append(issue_option(tickets, "new_defect", complaint, comp, None, primary=True))
    if can_recheck:
        actions.append(ActionOption(id="recheck", primary=not decision.escalate, label="Check it again with the AI"))
    for recall in to_check:
        actions.append(ActionOption(id="link_close", campno=recall.campno,
                                    label=f"Link to recall {display_campno(recall.campno)} (after comparing it "
                                          "yourself)",
                                    message=owner_recall_reply(complaint, recall, False)))
    actions.append(ActionOption(id="request_info", label="Ask the owner for details",
                                message=owner_info_request(complaint, [])))
    if not decision.escalate:
        actions.append(issue_option(tickets, "new_defect", complaint, comp, None, primary=False))
    return "Not checked by the AI: compare the recalls yourself"


def suggest(result: Result, tickets: Tickets, related: list[dict] = (), can_recheck: bool = False) -> Suggestion:
    """related: recalls on the same make/model/part but other model years (queries.recalls_other_years).
    can_recheck: a model is configured, so an answer the AI did not check can be checked again."""
    complaint = result.complaint
    decision = result.decision
    evidence = result.evidence
    judgment = result.judgment
    questions = judgment.questions if judgment else []
    after_remedy = "after_remedy" in decision.flags

    severity = []
    if complaint.crash:
        severity.append("crash")
    if complaint.fire:
        severity.append("fire")
    if complaint.injured:
        severity.append("injury")

    # The recall the rules settled on (for needs_info: the recall that may fit), if any.
    recall = evidence.recall(decision.campno) if decision.campno else None
    replaced = []
    if recall:
        replaced = [older.campno for older in evidence.recalls if older.replaced_by == recall.campno]
    card = recall_card(recall, complaint, replaced) if recall else None
    recall_comp = recall.comps[0] if recall else ""
    comp = main_comp(complaint, recall_comp)

    why: list[Why] = []
    actions: list[ActionOption] = []
    if decision.outcome == "needs_info" and "not_checked" in decision.flags:
        headline = not_checked(result, tickets, can_recheck, why, actions)
    elif decision.outcome == "known_recall" and recall:
        # Matches a recall: link it and reply to the owner with the recall's own remedy. "Matches", not "covered":
        # a recall covers certain build dates, and only the VIN shows whether this car is one of them.
        display = display_campno(recall.campno)
        headline = f"Matches recall {display}: {gist(plain_defect(recall.defect))}"
        scope = card.covers + (f"; {card.built}" if card.built else "")
        why.append(Why(text=f"The {complaint.year} {complaint.model.title()} is in recall {display} ({scope}). "
                            "Whether this car is included depends on its build date: confirm with the VIN."))
        why.append(Why(text="The AI judged it the same problem: what the owner describes matches what the recall says "
                            "can happen. The quotes below were found word for word; please confirm they mean the "
                            "same failure.",
                       quotes=pairs(checks_for(result, recall.campno, "same"))))
        others = also_fitting(result, recall)
        for other in others:
            why.append(Why(text=f"Recall {display_campno(other.campno)} ({covers(other, complaint)}) also fits: the AI "
                                "judged it the same problem too. Check which one applies to this car before linking.",
                           quotes=pairs(checks_for(result, other.campno, "same"))))
        if replaced:
            why.append(Why(text=f"Recall {', '.join(card.replaced)} was replaced by {display}: use {display}'s "
                                "remedy."))
        if not recall.same_component:
            owner_comps = ", ".join(complaint.comps) or "no component"
            why.append(Why(text=f"The owner filed it under {owner_comps}; the recall lists "
                                f"{', '.join(recall.comps)}. Owners often pick a different part."))

        link = ActionOption(id="link_close", primary=True, campno=recall.campno,
                            label=f"Link to recall {display} and reply to the owner",
                            message=owner_recall_reply(complaint, recall, after_remedy))
        if after_remedy:
            # Complaints keep arriving after the fix: the same click also flags the remedy to engineering.
            flag = issue_option(tickets, "remedy_concern", complaint, comp, recall.campno, primary=False)
            link.issue_id = flag.issue_id
            link.issue_title = flag.issue_title
            link.issue_kind = "remedy_concern"
            link.issue_comp = comp
            link.label += " + flag the remedy to engineering"
        actions.append(link)
        for other in others:
            actions.append(ActionOption(id="link_close", campno=other.campno,
                                        label=f"Link to recall {display_campno(other.campno)} instead and reply to the "
                                              "owner",
                                        message=owner_recall_reply(complaint, other, False)))
        actions.append(issue_option(tickets, "new_defect", complaint, comp, None, primary=False))

    elif decision.outcome in ("related_different", "possible_new"):
        # No match: a recall on this part describes a different failure, or no recall matches at all. When the
        # candidate list was cut, that holds for the recalls reviewed, not for the vehicle.
        reviewed = len(evidence.recalls)
        incomplete = evidence.recalls_total > reviewed
        vehicle = f"{complaint.year} {complaint.model.title()}"
        if decision.outcome == "related_different":
            checks = judgment.checks if judgment else []
            different = None
            for check in checks:
                if check.verdict == "different":
                    different = check
                    break
            other = evidence.recall(different.campno) if different else None
            if other:
                display = display_campno(other.campno)
                comp = other.comps[0]  # talk about the part that recall covers
            else:
                display = "?"
            what = f"Not recall {display}: a different {part(comp)} failure"
            why.append(Why(text=f"Recall {display} covers the {part(comp)} on this vehicle, but the AI judged that it "
                                "describes a different failure than the owner reports.",
                           quotes=pairs([different] if different else [])))
            if incomplete:
                why.append(Why(text=f"No other recall among the {reviewed} of {evidence.recalls_total} reviewed "
                                    "describes what the owner reports."))
            else:
                why.append(Why(text="No other recall on this vehicle describes what the owner reports."))
        elif not reviewed:
            what = "No recall covered this vehicle"
            why.append(Why(text=f"No recall covered the {vehicle} when this complaint arrived."))
        elif incomplete:
            what = f"No match among the {reviewed} of {evidence.recalls_total} recalls reviewed"
            why.append(Why(text=f"None of the {reviewed} recalls reviewed on the {vehicle} describes this failure."))
        else:
            what = "No matching recall found"
            why.append(Why(text=f"None of the {reviewed} recalls on the {vehicle} describes this failure."))
        if incomplete:
            why.append(Why(text=f"{evidence.recalls_total - reviewed} more recalls on this vehicle were not reviewed "
                                f"(the list stops at {reviewed}, same part and newest first). Check them before "
                                "concluding that no recall covers this."))

        if judgment and judgment.similar:
            earlier = [{"odino": owner.odino, "quote": owner.quote} for owner in judgment.similar]
            why.append(Why(text="Other owners described the same failure before this complaint:",
                           owner_quotes=earlier))
        for other_year in related:
            years = other_year["years"]
            span = years[0] if len(years) == 1 else f"{years[0]}–{years[-1]}"
            why.append(Why(text=f"Possibly related: recall {display_campno(other_year['campno'])} covers the "
                                f"{part(comp)} on {span} {complaint.model.title()}, not the {complaint.year}. "
                                f"Its problem: {gist(plain_defect(other_year['defect']), 140)}. "
                                "Check whether it is the same failure."))

        reasons = escalation_reasons(result, related)
        if reasons:
            headline = f"{what}: possible new defect"
            if decision.outcome != "related_different":
                headline += f" ({part(comp)})"
            why.append(Why(text="Worth engineering's time: " + "; ".join(reasons) + "."))
            actions.append(issue_option(tickets, "new_defect", complaint, comp, None, primary=True))
            actions.append(ActionOption(id="monitor", label="Record and watch instead (no escalation yet)"))
        else:
            headline = f"{what}: single report, record and watch"
            recent = evidence.stats.last_12_months
            similar = len(judgment.similar) if judgment else 0
            complaints_word = "complaint" if recent == 1 else "complaints"
            owners_word = "owner" if similar == 1 else "owners"
            why.append(Why(text=f"Not enough yet to involve engineering: no crash, fire or injury; {recent} similar "
                                f"{complaints_word} on this model year in 12 months (escalate at {PATTERN_MIN}); "
                                f"{similar} earlier {owners_word} describing the same failure (escalate at "
                                f"{SIMILAR_MIN}). If more owners report it, it will be suggested for escalation."))
            actions.append(ActionOption(id="monitor", primary=True,
                                        label="Record and watch for more reports (no escalation yet)"))
            actions.append(issue_option(tickets, "new_defect", complaint, comp, None, primary=False))

    else:
        # needs_info (also reached by a known_recall whose recall is missing from the evidence): ask the owner.
        headline = "Not enough detail to tell"
        if recall:
            headline += f": possibly recall {display_campno(recall.campno)}"
        if "unknown_year" in result.intake.flags:
            why.append(Why(text="The model year is missing, so we can't tell which recalls cover this vehicle."))
        else:
            why.append(Why(text="The owner's description is too short or too general to match it to a recall."))
        if recall:
            why.append(Why(text=f"It may be recall {display_campno(recall.campno)}:",
                           quotes=pairs(checks_for(result, recall.campno))))
        actions.append(ActionOption(id="request_info", primary=True, label="Ask the owner for details",
                                    message=owner_info_request(complaint, questions)))
        if recall:
            actions.append(ActionOption(id="link_close", campno=recall.campno,
                                        label=f"Link to recall {display_campno(recall.campno)} anyway",
                                        message=owner_recall_reply(complaint, recall, False)))

    # Always on offer, below the suggested action.
    if decision.outcome != "needs_info":
        actions.append(ActionOption(id="request_info", label="Ask the owner for details",
                                    message=owner_info_request(complaint, questions)))
    actions.append(ActionOption(id="close_no_action", label="Close: not a safety defect"))

    if decision.source == "fallback":
        check_note = ("The AI could not complete this check. Nothing was compared: read the complaint and the recalls "
                      "before acting.")
    elif decision.source == "rules":
        check_note = "The AI is off. Nothing was compared: read the complaint and the recalls before acting."
    elif decision.confidence != "high":
        check_note = f"{decision.confidence.title()} confidence: please confirm before acting."
    else:
        check_note = None

    summary = judgment.summary if judgment else " ".join(decision.reasons)
    summary_by = "ai" if judgment else "rules"
    return Suggestion(result_id=result.id, outcome=decision.outcome, headline=headline,
                      confidence=decision.confidence, check_note=check_note, severity=severity, summary=summary,
                      summary_by=summary_by, recall=card, why=why, pattern=pattern_of(result, recall, comp),
                      questions=questions, actions=actions)
