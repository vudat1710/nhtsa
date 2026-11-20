"""How the agent investigated one complaint, told step by step in the analyst's words (from a stored Result).

Every step is something the system did or observed: what it looked at, the agent's own search queries, its verdict
and stated reason per recall, the verification result, and the rule that decided. The model's reasoning summary is
included when it gave one, clearly labelled: it is the model's own account, not evidence.
"""
from typing import Literal

from pydantic import BaseModel

from app.models import Result
from app.workspace.messages import display_campno, plain_defect
from app.workspace.suggest import QuotePair, gist

Kind = Literal["read", "look", "think", "search", "compare", "check", "decide"]


class Step(BaseModel):
    kind: Kind
    title: str
    lines: list[str] = []
    quotes: list[QuotePair] = []
    status: Literal["ok", "warn", "info"] = "info"


VERDICT = {"same": "same failure", "partial": "possibly (too vague to tell)",
           "different": "same part, different failure"}


def trail(r: Result) -> list[Step]:
    c, it, ev, j, d = r.complaint, r.intake, r.evidence, r.judgment, r.decision
    steps: list[Step] = []

    notes = [f"Owner chose: {', '.join(c.components) or 'no component'}."]
    if it.masked:
        notes.append(f"{it.masked} recall number(s) the owner cited were hidden from the agent, so it judges the "
                     "failure itself, not the owner's belief.")
    flag_text = {"unknown_year": "Model year is unknown.", "short_text": "The description is very short.",
                 "severe": "Crash, fire or injury reported.", "unknown_component": "No component chosen."}
    notes += [flag_text[f] for f in it.flags if f in flag_text]
    steps.append(Step(kind="read", title="Read the complaint", lines=notes))

    look = [f"{len(ev.recalls)} recall(s) covered the {c.year} {c.make.title()} {c.model.title()} on {c.received}"
            + (f" ({ev.recalls_total - len(ev.recalls)} more not shown)" if ev.recalls_total > len(ev.recalls) else "")
            + ("." if ev.recalls else "; nothing to compare against.")]
    look += [f"{display_campno(x.campno)} ({x.comps[0].lower() if x.comps else '?'}): "
             f"{gist(plain_defect(x.defect), 90)}" for x in ev.recalls[:8]]
    look.append(f"{ev.stats.total} earlier complaints on this model year about the same part, "
                f"{ev.stats.last_12_months} in the last 12 months.")
    if ev.investigations:
        look.append("NHTSA investigations: " + "; ".join(f"{i.action} ({i.opened}) {i.subject}"
                                                       for i in ev.investigations[:3]))
    steps.append(Step(kind="look", title="Looked up what was known on that date", lines=look))

    reasoning = next((a.reasoning for a in reversed(r.attempts) if a.reasoning), "")
    if reasoning:
        steps.append(Step(kind="think", title="The agent's reasoning (its own summary, not evidence)",
                          lines=[p.replace("**", "") for p in reasoning.split("\n\n") if p.strip()][:6]))

    cited = {s.odino: s.quote for s in (j.similar if j else [])}
    for call in r.tool_calls:
        query = str(call.get("arguments", {}).get("query", ""))
        used = [o for o in call.get("results", []) if o in cited]
        lines = [f"{len(call.get('results', []))} found; {len(used)} describe the same failure:"
                 if call.get("results") else "Nothing found."]
        lines += [f"“{cited[o]}” (complaint {o})" for o in used]
        steps.append(Step(kind="search", title=f"Decided to search earlier complaints for “{query}”", lines=lines))

    if j:
        judged = {ch.campno for ch in j.checks}
        compare = [f"{display_campno(ch.campno)}: {VERDICT[ch.verdict]}. {ch.reason}" for ch in j.checks]
        aside = [display_campno(x.campno) for x in ev.recalls if x.campno not in judged]
        if aside:
            compare.append(f"Set aside as unrelated: {', '.join(aside)}.")
        steps.append(Step(kind="compare", title="Compared the complaint with each recall", lines=compare,
                          quotes=[QuotePair(owner=ch.complaint_quote, recall=ch.recall_quote) for ch in j.checks]))

    for a in r.attempts:
        if a.error:
            steps.append(Step(kind="check", status="warn", title=f"The AI did not answer (attempt {a.n})",
                              lines=[a.error]))
        elif a.issues:
            steps.append(Step(kind="check", status="warn", title=f"Double-check failed (attempt {a.n})",
                              lines=[i.message for i in a.issues][:4] + ["Sent back to the agent to correct."
                                                                          if a.n == 1 else ""]))
        else:
            n_quotes = 2 * len(j.checks) + len(j.similar) if j else 0
            steps.append(Step(kind="check", status="ok", title="Double-checked against the records",
                              lines=[f"{n_quotes} quote(s) found word for word in their sources; every recall cited is "
                                     "one that covered this vehicle; no number was invented."]))
    if d.source == "fallback":
        steps.append(Step(kind="check", status="warn", title="Fell back to simple rules",
                          lines=["The AI's answer could not be used; the suggestion below is rules-only."]))

    steps.append(Step(kind="decide", title="Decided by the rules (the agent only proposes)", lines=d.reasons,
                      status="ok" if d.source.startswith("ai") else "warn"))
    return steps
