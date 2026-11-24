"""Step 5 (code): the final outcome and confidence. The AI proposes; these rules decide, from checked citations only.

Each rule is one plain sentence in `reasons`, so an analyst (and a reviewer) can see exactly why.
"""
from app.models import Complaint, Decision, Evidence, Intake, Judgment

AFTER_REMEDY_MIN = 5   # similar complaints after a recall was filed before we flag "the fix may not hold"
PATTERN_MIN = 3        # similar complaints in the last 12 months before a new issue counts as a pattern


def decide(complaint: Complaint, intake: Intake, evidence: Evidence, judgment: Judgment | None,
           source: str) -> Decision:
    flags = ["severe"] if "severe" in intake.flags else []
    if "unknown_year" in intake.flags:
        return Decision(outcome="needs_info", confidence="high", flags=flags, escalate=False, source=source,
                        reasons=["The model year is unknown, so we cannot tell which recalls cover this vehicle."])
    if judgment is None:
        return baseline(intake, evidence, flags, source)

    reasons: list[str] = []

    # Group the AI's checks by verdict, in the AI's order: it lists its best fit first (in the evaluation, ordering by
    # evidence instead picked a recall other than the owner's in 3 cases where the AI's first was the owner's).
    # A 'same' recall replaced by another 'same' recall drops out: the newer applies.
    same = [check for check in judgment.checks if check.verdict == "same"]
    same_ids = {check.campno for check in same}
    replaced = [check for check in same if evidence.recall(check.campno).replaced_by in same_ids]
    if replaced:
        flags.append("superseded")
        for check in replaced:
            newer = evidence.recall(check.campno).replaced_by
            reasons.append(f"{check.campno} was replaced by {newer}; the newer recall applies.")
        same = [check for check in same if check not in replaced]
    partial = [check for check in judgment.checks if check.verdict == "partial"]
    different = [check for check in judgment.checks if check.verdict == "different"]

    # The outcome, from the strongest verdict down
    if same and "short_text" not in intake.flags:
        best = evidence.recall(same[0].campno)
        outcome = "known_recall"
        campno = best.campno
        confidence = "high"
        escalate = False
        reasons.append(f"The AI judged the complaint the same failure as recall {best.campno} (its quotes were found "
                       "word for word).")
        fitting = {check.campno for check in same}
        if len(fitting) > 1:
            confidence = "medium"
            reasons.append(f"{len(fitting)} recalls fit; the analyst should confirm which one.")
        if not best.same_component:
            confidence = "medium"
            reasons.append("The recall is filed under a different component than the owner chose.")
        if best.complaints_since >= AFTER_REMEDY_MIN:
            flags.append("after_remedy")
            escalate = True
            reasons.append(f"{best.complaints_since} similar complaints arrived after this recall was filed: the fix "
                           "may not hold, or cars are not being repaired. The data cannot tell which.")
    elif same or partial:
        probable = same[0].campno if same else partial[0].campno
        outcome = "needs_info"
        confidence = "medium"
        campno = probable
        escalate = False
        reasons.append(f"Recall {probable} may fit, but the complaint lacks the detail to confirm it.")
    elif "short_text" in intake.flags:
        # found on test set C: "car broke" was escalated as a possible new defect; too little to escalate on
        outcome = "needs_info"
        confidence = "high"
        campno = None
        escalate = False
        reasons.append("The description is too short to compare with any recall or to escalate.")
    elif different:
        outcome = "related_different"
        confidence = "medium"
        campno = None
        escalate = True
        reasons.append(f"Recall {different[0].campno} involves the same part but describes a different failure.")
    else:
        outcome = "possible_new"
        campno = None
        escalate = True
        shown = len(evidence.recalls)
        if not evidence.recalls:
            confidence = "high"
            reasons.append("No recall covered this vehicle when the complaint arrived.")
        elif evidence.recalls_total > shown:
            confidence = "low"
            reasons.append(f"None of the {shown} recalls shown fits, but {evidence.recalls_total} exist; "
                           "some were not reviewed.")
        else:
            confidence = "medium"
            reasons.append(f"None of the {shown} recalls on this vehicle describes this failure.")

    # Extra flags on top of the outcome
    if outcome in ("possible_new", "related_different") and evidence.recalls_total > len(evidence.recalls):
        # Only the first recalls were compared: "no recall matches" holds for those, not for the vehicle
        flags.append("incomplete_review")
    recent_complaints = evidence.stats.last_12_months
    if outcome == "possible_new" and recent_complaints >= PATTERN_MIN:
        flags.append("pattern")
        reasons.append(f"{recent_complaints} earlier complaints on this vehicle and component in the last 12 months.")
    if judgment.proposed != outcome:
        flags.append("ai_disagreed")
        reasons.append(f"The AI proposed {judgment.proposed}; the rules above decided {outcome}.")
    return Decision(outcome=outcome, confidence=confidence, campno=campno, reasons=reasons, flags=flags,
                    escalate=escalate, source=source)


def baseline(intake: Intake, evidence: Evidence, flags: list[str], source: str) -> Decision:
    """No checked AI answer (the AI failed, or is off): nothing was compared with the failure the owner describes, so
    no recall is matched and a person must look. Same-component recalls are only ranked as the ones to check first
    (matching by component alone is the shortcut that confuses opposite failures). A crash, fire or injury is still
    escalated, unless the text is too short to escalate on (the same rule as with the AI)."""
    why = "The AI could not check this complaint" if source == "fallback" else "The AI is off"
    flags = [*flags, "not_checked"]
    too_short = "short_text" in intake.flags
    escalate = "severe" in flags and not too_short
    if not evidence.recalls and not too_short:
        # Nothing to compare: the database already shows no recall covered this vehicle (a fact, not a judgment).
        return Decision(outcome="possible_new", confidence="low", flags=flags, escalate=True, source=source,
                        reasons=[f"{why}. No recall covered this vehicle when the complaint arrived."])
    if not evidence.recalls:
        # Too short to escalate on, as with the AI: ask the owner
        return Decision(outcome="needs_info", confidence="low", flags=flags, escalate=False, source=source,
                        reasons=[f"{why}. No recall covered this vehicle when the complaint arrived, and the "
                                 "description is too short to escalate on."])
    candidate_ids = {recall.campno for recall in evidence.recalls}
    # Same-component recalls that no other candidate replaced, newest first (the order evidence keeps them in)
    to_check = [recall.campno for recall in evidence.recalls
                if recall.same_component and recall.replaced_by not in candidate_ids]
    reasons = [f"{why}, so no recall was compared with what the owner describes."]
    if to_check:
        reasons.append(f"Recalls on the same component to check first: {', '.join(to_check[:3])}.")
    else:
        reasons.append(f"None of the {len(evidence.recalls)} recalls on this vehicle is filed under the same "
                       "component; read them before deciding.")
    if escalate:
        reasons.append("A crash, fire or injury is reported: sent to engineering without waiting for the check.")
    return Decision(outcome="needs_info", confidence="low", flags=flags, escalate=escalate, source=source,
                    reasons=reasons)
