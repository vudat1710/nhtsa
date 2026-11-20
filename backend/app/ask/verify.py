"""Check a follow-up answer before it is shown as fact: every citation points to a real source of this case and its
quote is in that source word for word (same rules as pipeline/verify.py), every number exists, and an 'answered'
reply cites at least one source."""
import json
import re

from app.ask.prompt import AskAnswer
from app.models import Result
from app.pipeline.verify import NUMBER, quote_problem, recall_text

CAMPNO = re.compile(r"(\d{2})\s?V\s?-?\s?(\d{3})", re.I)


def campno_of(ref: str) -> str:
    """A recall number as the agent wrote it ("24V-868", "recall 24 V 868") in its stored form (24V868000)."""
    match = CAMPNO.search(ref or "")
    return f"{match.group(1)}V{match.group(2)}000" if match else ref


def check(answer: AskAnswer, r: Result, earlier_texts: dict[int, str], question: str,
          related: list[dict] = ()) -> list[str]:
    """Every reason the answer cannot be shown as verified; an empty list means it passed."""
    other_years = {recall["campno"]: recall["defect"] for recall in related}
    issues = []
    for citation in answer.citations:
        source = None
        if citation.kind == "complaint":
            if citation.id.strip() in (str(r.complaint.odino), "this"):
                source = r.complaint.text
        elif citation.kind == "recall":
            campno = campno_of(citation.id)
            source = recall_text(r.evidence, campno) or other_years.get(campno)
        elif citation.id.strip().isdigit():  # earlier_complaint
            source = earlier_texts.get(int(citation.id))
        if source is None:
            issues.append(f"citation {citation.kind} {citation.id} is not a source of this case")
            continue
        problem = quote_problem(citation.quote, source)
        if problem:
            issues.append(f"citation {citation.kind} {citation.id}: quote {citation.quote!r} {problem}")
    if answer.scope == "answered" and not answer.citations:
        issues.append("an answered question needs at least one citation")

    # Every number in the answer must appear in what the agent was given: the case, its sources or the question.
    allowed = " ".join([json.dumps(r.model_dump(), ensure_ascii=False), *earlier_texts.values(), question,
                        json.dumps(list(related), ensure_ascii=False)])
    known = set(NUMBER.findall(allowed))
    for number in NUMBER.findall(answer.answer):
        if number not in known:
            issues.append(f"the answer says {number}, which is not in the records")
    return issues
