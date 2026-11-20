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
    m = CAMPNO.search(ref or "")
    return f"{m.group(1)}V{m.group(2)}000" if m else ref


def check(a: AskAnswer, r: Result, earlier_texts: dict[int, str], question: str,
          related: list[dict] = ()) -> list[str]:
    other_years = {x["campno"]: x["defect"] for x in related}
    issues = []
    for cit in a.citations:
        if cit.kind == "complaint":
            source = r.complaint.text if cit.id.strip() in (str(r.complaint.odino), "this") else None
        elif cit.kind == "recall":
            source = recall_text(r.evidence, campno_of(cit.id)) or other_years.get(campno_of(cit.id))
        else:
            source = earlier_texts.get(int(cit.id)) if cit.id.strip().isdigit() else None
        if source is None:
            issues.append(f"citation {cit.kind} {cit.id} is not a source of this case")
        elif problem := quote_problem(cit.quote, source):
            issues.append(f"citation {cit.kind} {cit.id}: quote {cit.quote!r} {problem}")
    if a.scope == "answered" and not a.citations:
        issues.append("an answered question needs at least one citation")
    allowed = " ".join([json.dumps(r.model_dump(), ensure_ascii=False), *earlier_texts.values(), question,
                        json.dumps(list(related), ensure_ascii=False)])
    known = set(NUMBER.findall(allowed))
    issues += [f"the answer says {n}, which is not in the records" for n in NUMBER.findall(a.answer) if n not in known]
    return issues
