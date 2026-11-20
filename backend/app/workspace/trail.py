"""How the agent investigated one complaint, told step by step in the analyst's words (from a stored Result).

Every step is something the system did or observed: what it looked at, the agent's own search queries, its verdict
and stated reason per recall, the verification result, and the rule that decided. Nothing here is narrated by the
model after the fact.
"""
from typing import Literal

from pydantic import BaseModel

from app.models import Result
from app.workspace.messages import display_campno, plain_defect
from app.workspace.suggest import QuotePair, gist, pairs

Kind = Literal["read", "look", "search", "compare", "check", "decide"]


class Step(BaseModel):
    kind: Kind
    title: str
    lines: list[str] = []
    quotes: list[QuotePair] = []
    status: Literal["ok", "warn", "info"] = "info"


VERDICT = {"same": "same failure", "partial": "possibly (too vague to tell)",
           "different": "same part, different failure"}


def trail(result: Result) -> list[Step]:
    complaint = result.complaint
    intake = result.intake
    evidence = result.evidence
    judgment = result.judgment
    decision = result.decision
    steps: list[Step] = []

    # Read: what the owner chose, and what intake noticed about the complaint.
    chosen = ", ".join(complaint.components) or "no component"
    notes = [f"Owner chose: {chosen}."]
    if intake.masked:
        notes.append(f"{intake.masked} recall number(s) the owner cited were hidden from the agent, so it judges the "
                     "failure itself, not the owner's belief.")
    flag_text = {"unknown_year": "Model year is unknown.", "short_text": "The description is very short.",
                 "severe": "Crash, fire or injury reported.", "unknown_component": "No component chosen."}
    notes += [flag_text[flag] for flag in intake.flags if flag in flag_text]
    steps.append(Step(kind="read", title="Read the complaint", lines=notes))

    # Look: the evidence that existed on the day the complaint arrived.
    shown = len(evidence.recalls)
    vehicle = f"{complaint.year} {complaint.make.title()} {complaint.model.title()}"
    found = f"{shown} recall(s) covered the {vehicle} on {complaint.received}"
    if evidence.recalls_total > shown:
        found += f" ({evidence.recalls_total - shown} more not shown)"
    if evidence.recalls:
        found += "."
    else:
        found += "; nothing to compare against."
    look = [found]
    for recall in evidence.recalls[:8]:
        comp = recall.comps[0].lower() if recall.comps else "?"
        look.append(f"{display_campno(recall.campno)} ({comp}): {gist(plain_defect(recall.defect), 90)}")
    look.append(f"{evidence.stats.total} earlier complaints on this model year about the same part, "
                f"{evidence.stats.last_12_months} in the last 12 months.")
    if evidence.investigations:
        investigations = [f"{inv.action} ({inv.opened}) {inv.subject}" for inv in evidence.investigations[:3]]
        look.append("NHTSA investigations: " + "; ".join(investigations))
    steps.append(Step(kind="look", title="Looked up what was known on that date", lines=look))

    # Search: each search the agent chose to run, with the results it later cited as the same failure.
    cited = {}
    if judgment:
        cited = {earlier.odino: earlier.quote for earlier in judgment.similar}
    for call in result.tool_calls:
        query = str(call.get("arguments", {}).get("query", ""))
        results = call.get("results", [])
        used = [odino for odino in results if odino in cited]
        if results:
            lines = [f"{len(results)} found; {len(used)} describe the same failure:"]
        else:
            lines = ["Nothing found."]
        lines += [f"“{cited[odino]}” (complaint {odino})" for odino in used]
        steps.append(Step(kind="search", title=f"Decided to search earlier complaints for “{query}”", lines=lines))

    # Compare: the agent's verdict and reason for each recall it judged.
    if judgment:
        compare = [f"{display_campno(check.campno)}: {VERDICT[check.verdict]}. {check.reason}"
                   for check in judgment.checks]
        judged = {check.campno for check in judgment.checks}
        aside = [display_campno(recall.campno) for recall in evidence.recalls if recall.campno not in judged]
        if aside:
            compare.append(f"Set aside as unrelated: {', '.join(aside)}.")
        steps.append(Step(kind="compare", title="Compared the complaint with each recall", lines=compare,
                          quotes=pairs(judgment.checks)))

    # Check: the verifier's result for each attempt.
    for attempt in result.attempts:
        if attempt.error:
            steps.append(Step(kind="check", status="warn", title=f"The AI did not answer (attempt {attempt.n})",
                              lines=[attempt.error]))
        elif attempt.issues:
            lines = [issue.message for issue in attempt.issues][:4]
            if attempt.n == 1:  # only the first attempt gets a second chance
                lines.append("Sent back to the agent to correct.")
            steps.append(Step(kind="check", status="warn", title=f"Double-check failed (attempt {attempt.n})",
                              lines=lines))
        else:
            # Two quotes per recall check (owner and recall), one per earlier complaint cited.
            quote_count = 0
            if judgment:
                quote_count = 2 * len(judgment.checks) + len(judgment.similar)
            steps.append(Step(kind="check", status="ok", title="Double-checked against the records",
                              lines=[f"{quote_count} quote(s) found word for word in their sources; every recall "
                                     "cited is one that covered this vehicle; no number was invented."]))
    if decision.source == "fallback":
        steps.append(Step(kind="check", status="warn", title="Fell back to simple rules",
                          lines=["The AI's answer could not be used; the suggestion below is rules-only."]))

    # Decide: the rules, not the agent, set the outcome.
    status = "ok" if decision.source.startswith("ai") else "warn"
    steps.append(Step(kind="decide", title="Decided by the rules (the agent only proposes)", lines=decision.reasons,
                      status=status))
    return steps
