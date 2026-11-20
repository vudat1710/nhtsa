"""Step 4 (code): check the AI's judgment against the evidence before anything is shown or decided.

A judgment passes only if every recall it cites is a candidate, every quote appears word for word in its source,
every complaint it cites came from its own search, its proposed outcome is consistent with its checks, and every
number in its summary appears in the evidence. Issues go back to the AI once (repair), then the fallback answers.
"""
import json
import re

from app.models import MIN_QUOTE_WORDS, Complaint, Evidence, Intake, Issue, Judgment
from app.pipeline.intake import MASK

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def normalize(s: str) -> str:
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def quote_ok(quote: str, source: str) -> bool:
    q = normalize(quote).strip(" .,;:!?\"'…")
    return len(q.split()) >= MIN_QUOTE_WORDS and MASK.lower() not in q and q in normalize(source)


def recall_text(ev: Evidence, campno: str) -> str:
    r = ev.recall(campno)
    return f"{r.defect}\n{r.consequence}\n{r.remedy}" if r else ""


def verify(j: Judgment, c: Complaint, it: Intake, ev: Evidence, found: dict[int, str]) -> list[Issue]:
    issues: list[Issue] = []
    seen: set[str] = set()
    for ch in j.checks:
        if ev.recall(ch.campno) is None:
            issues.append(Issue(code="unknown_recall", message=f"{ch.campno} is not one of the candidate recalls"))
            continue
        if ch.campno in seen:
            issues.append(Issue(code="duplicate_check", message=f"{ch.campno} is checked twice"))
        seen.add(ch.campno)
        if not quote_ok(ch.complaint_quote, it.text):
            issues.append(Issue(code="quote_not_found", message=f"{ch.campno}: complaint_quote is not an exact quote "
                                f"of at least {MIN_QUOTE_WORDS} words from the complaint: {ch.complaint_quote!r}"))
        if not quote_ok(ch.recall_quote, recall_text(ev, ch.campno)):
            issues.append(Issue(code="quote_not_found", message=f"{ch.campno}: recall_quote is not an exact quote of "
                                f"at least {MIN_QUOTE_WORDS} words from that recall: {ch.recall_quote!r}"))
    for s in j.similar:
        if s.odino not in found:
            issues.append(Issue(code="unknown_complaint", message=f"complaint {s.odino} was not returned by "
                                                                  "search_complaints"))
        elif not quote_ok(s.quote, found[s.odino]):
            issues.append(Issue(code="quote_not_found", message=f"complaint {s.odino}: quote not found: {s.quote!r}"))

    verdicts = {ch.verdict for ch in j.checks}
    if j.proposed == "known_recall" and "same" not in verdicts:
        issues.append(Issue(code="inconsistent", message="proposed known_recall but no check has verdict 'same'"))
    if j.proposed in ("possible_new", "related_different") and "same" in verdicts:
        issues.append(Issue(code="inconsistent", message=f"proposed {j.proposed} but a check has verdict 'same'"))
    if j.proposed == "related_different" and "different" not in verdicts:
        issues.append(Issue(code="inconsistent", message="proposed related_different but no check has verdict "
                                                         "'different'"))
    if j.proposed == "needs_info" and not j.questions:
        issues.append(Issue(code="inconsistent", message="proposed needs_info but asked no questions"))

    allowed = " ".join([it.text, c.year, c.received, json.dumps(ev.model_dump(), ensure_ascii=False),
                        *found.values()])
    allowed_numbers = set(NUMBER.findall(allowed))
    for n in NUMBER.findall(j.summary):
        if n not in allowed_numbers:
            issues.append(Issue(code="unsupported_number", message=f"summary says {n}, which is not in the evidence"))
    return issues
