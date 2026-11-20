"""Step 5 (code): the final outcome and confidence. The AI proposes; these rules decide, from verified evidence only.

Each rule is one plain sentence in `reasons`, so an analyst (and a reviewer) can see exactly why.
"""
from app.models import Complaint, Decision, Evidence, Intake, Judgment

AFTER_REMEDY_MIN = 5   # similar complaints after a recall was filed before we flag "the fix may not hold"
PATTERN_MIN = 3        # similar complaints in the last 12 months before a new issue counts as a pattern


def decide(c: Complaint, it: Intake, ev: Evidence, j: Judgment | None, source: str) -> Decision:
    flags = ["severe"] if "severe" in it.flags else []
    if "unknown_year" in it.flags:
        return Decision(outcome="needs_info", confidence="high", flags=flags, escalate=False, source=source,
                        reasons=["The model year is unknown, so we cannot tell which recalls cover this vehicle."])
    if j is None:
        return baseline(it, ev, flags, source)

    reasons: list[str] = []
    same = [ch for ch in j.checks if ch.verdict == "same"]
    same_ids = {ch.campno for ch in same}
    replaced = [ch for ch in same if ev.recall(ch.campno).replaced_by in same_ids]
    if replaced:
        flags.append("superseded")
        reasons += [f"{ch.campno} was replaced by {ev.recall(ch.campno).replaced_by}; the newer recall applies."
                    for ch in replaced]
        same = [ch for ch in same if ch not in replaced]
    partial = [ch for ch in j.checks if ch.verdict == "partial"]
    different = [ch for ch in j.checks if ch.verdict == "different"]

    if same and "short_text" not in it.flags:
        best = ev.recall(same[0].campno)
        confidence = "high"
        reasons.append(f"The complaint describes the failure in recall {best.campno} (quotes verified).")
        if len(same) > 1:
            confidence = "medium"
            reasons.append(f"{len(same)} recalls fit; the analyst should confirm which one.")
        if not best.same_component:
            confidence = "medium"
            reasons.append("The recall is filed under a different component than the owner chose.")
        escalate = False
        if best.complaints_since >= AFTER_REMEDY_MIN:
            flags.append("after_remedy")
            escalate = True
            reasons.append(f"{best.complaints_since} similar complaints arrived after this recall was filed: the fix "
                           "may not hold, or cars are not being repaired. The data cannot tell which.")
        outcome, campno = "known_recall", best.campno
    elif same or partial:
        probable = (same or partial)[0].campno
        outcome, confidence, campno, escalate = "needs_info", "medium", probable, False
        reasons.append(f"Recall {probable} may fit, but the complaint lacks the detail to confirm it.")
    elif "short_text" in it.flags:
        # found on test set C: "car broke" was escalated as a possible new defect; too little to escalate on
        outcome, confidence, campno, escalate = "needs_info", "high", None, False
        reasons.append("The description is too short to compare with any recall or to escalate.")
    elif different:
        outcome, confidence, campno, escalate = "related_different", "medium", None, True
        reasons.append(f"Recall {different[0].campno} involves the same part but describes a different failure.")
    else:
        outcome, campno, escalate = "possible_new", None, True
        if not ev.recalls:
            confidence = "high"
            reasons.append("No recall covered this vehicle when the complaint arrived.")
        elif ev.recalls_total > len(ev.recalls):
            confidence = "low"
            reasons.append(f"None of the {len(ev.recalls)} recalls shown fits, but {ev.recalls_total} exist; "
                           "some were not reviewed.")
        else:
            confidence = "medium"
            reasons.append(f"None of the {len(ev.recalls)} recalls on this vehicle describes this failure.")
    if outcome == "possible_new" and ev.stats.last_12_months >= PATTERN_MIN:
        flags.append("pattern")
        reasons.append(f"{ev.stats.last_12_months} earlier complaints on this vehicle and component in the last "
                       "12 months.")
    if j.proposed != outcome:
        flags.append("ai_disagreed")
        reasons.append(f"The AI proposed {j.proposed}; the rules above decided {outcome}.")
    return Decision(outcome=outcome, confidence=confidence, campno=campno, reasons=reasons, flags=flags,
                    escalate=escalate, source=source)


def baseline(it: Intake, ev: Evidence, flags: list[str], source: str) -> Decision:
    """No AI: newest recall on the same component, if any (also the evaluation baseline). Always low confidence."""
    ids = {r.campno for r in ev.recalls}
    same = [r for r in ev.recalls if r.same_component and r.replaced_by not in ids]
    note = "Not AI-verified: " if source == "fallback" else ""
    if same:
        return Decision(outcome="known_recall", confidence="low", campno=same[0].campno, flags=flags, escalate=False,
                        source=source, reasons=[f"{note}{same[0].campno} is the newest recall on the same component; "
                                                "the failure itself was not compared."])
    return Decision(outcome="possible_new", confidence="low", flags=flags, escalate=True, source=source,
                    reasons=[f"{note}no recall on this vehicle shares the complaint's component."])
