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
# A quote starting right after one of these can flip the meaning: "[Zero] airbags were deployed" (found in a live run)
NEGATIONS = {"no", "not", "zero", "never", "without", "none", "nor", "neither", "cannot", "nothing"}


def normalize(s: str) -> str:
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def quote_problem(quote: str, source: str) -> str | None:
    """None if the quote is fine, else why not: too short, quotes the mask, not found, cuts a word, drops a negation."""
    q = normalize(quote).strip(" .,;:!?\"'…")
    if len(q.split()) < MIN_QUOTE_WORDS:
        return f"shorter than {MIN_QUOTE_WORDS} words"
    if MASK.lower() in q:
        return "quotes the removed recall number"
    src = normalize(source)
    starts = [m.start() for m in re.finditer(re.escape(q), src)]
    if not starts:
        return "not found word for word"
    for s in starts:
        e = s + len(q)
        if (s > 0 and src[s - 1].isalnum()) or (e < len(src) and src[e].isalnum()):
            continue  # cuts a word in half here; try the next occurrence
        before = src[:s].split()[-1:] if s else []
        if before and (before[0].strip("\"'(,;:") in NEGATIONS or before[0].endswith("n't")):
            return f"drops the word '{before[0]}' right before it, which changes the meaning"
        return None
    return "starts or ends in the middle of a word"


def quote_ok(quote: str, source: str) -> bool:
    return quote_problem(quote, source) is None


def recall_text(ev: Evidence, campno: str) -> str:
    r = ev.recall(campno)
    return f"{r.defect}\n{r.consequence}\n{r.remedy}" if r else ""


def check_quote(issues: list[Issue], where: str, quote: str, source: str) -> None:
    if problem := quote_problem(quote, source):
        code = "quote_drops_negation" if problem.startswith("drops") else "quote_not_found"
        issues.append(Issue(code=code, message=f"{where}: quote {quote!r} {problem}"))


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
        check_quote(issues, f"{ch.campno} complaint_quote (from the complaint)", ch.complaint_quote, it.text)
        check_quote(issues, f"{ch.campno} recall_quote (from that recall)", ch.recall_quote,
                    recall_text(ev, ch.campno))
    for s in j.similar:
        if s.odino not in found:
            issues.append(Issue(code="unknown_complaint", message=f"complaint {s.odino} was not returned by "
                                                                  "search_complaints"))
        else:
            check_quote(issues, f"similar complaint {s.odino}", s.quote, found[s.odino])

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
