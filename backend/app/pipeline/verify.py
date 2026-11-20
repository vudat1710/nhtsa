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


def normalize(text: str) -> str:
    """Lowercase, straight quotes, single spaces: so a quote matches its source however the quote marks were typed."""
    text = text.lower()
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


def quote_problem(quote: str, source: str) -> str | None:
    """None if the quote is fine, else why not: too short, quotes the mask, not found, cuts a word, drops a negation."""
    quoted = normalize(quote).strip(" .,;:!?\"'…")
    if len(quoted.split()) < MIN_QUOTE_WORDS:
        return f"shorter than {MIN_QUOTE_WORDS} words"
    if MASK.lower() in quoted:
        return "quotes the removed recall number"
    text = normalize(source)
    starts = [match.start() for match in re.finditer(re.escape(quoted), text)]
    if not starts:
        return "not found word for word"
    for start in starts:
        end = start + len(quoted)
        cuts_word_at_start = start > 0 and text[start - 1].isalnum()
        cuts_word_at_end = end < len(text) and text[end].isalnum()
        if cuts_word_at_start or cuts_word_at_end:
            continue  # cuts a word in half here; try the next occurrence
        words_before = text[:start].split()
        if words_before:
            word_before = words_before[-1]
            if word_before.strip("\"'(,;:") in NEGATIONS or word_before.endswith("n't"):
                return f"drops the word '{word_before}' right before it, which changes the meaning"
        return None
    return "starts or ends in the middle of a word"


def recall_text(evidence: Evidence, campno: str) -> str:
    recall = evidence.recall(campno)
    if not recall:
        return ""
    return f"{recall.defect}\n{recall.consequence}\n{recall.remedy}"


def check_quote(issues: list[Issue], where: str, quote: str, source: str) -> None:
    if problem := quote_problem(quote, source):
        code = "quote_drops_negation" if problem.startswith("drops") else "quote_not_found"
        issues.append(Issue(code=code, message=f"{where}: quote {quote!r} {problem}"))


def verify(judgment: Judgment, complaint: Complaint, intake: Intake, evidence: Evidence,
           found: dict[int, str]) -> list[Issue]:
    issues: list[Issue] = []

    # Each recall check: a candidate, checked once, both quotes word for word from their sources
    checked: set[str] = set()
    for check in judgment.checks:
        if evidence.recall(check.campno) is None:
            issues.append(Issue(code="unknown_recall", message=f"{check.campno} is not one of the candidate recalls"))
            continue
        if check.campno in checked:
            issues.append(Issue(code="duplicate_check", message=f"{check.campno} is checked twice"))
        checked.add(check.campno)
        check_quote(issues, f"{check.campno} complaint_quote (from the complaint)", check.complaint_quote,
                    intake.text)
        check_quote(issues, f"{check.campno} recall_quote (from that recall)", check.recall_quote,
                    recall_text(evidence, check.campno))

    # Each similar complaint: returned by the search tool, quote word for word from it
    for similar in judgment.similar:
        if similar.odino not in found:
            issues.append(Issue(code="unknown_complaint",
                                message=f"complaint {similar.odino} was not returned by search_complaints"))
        else:
            check_quote(issues, f"similar complaint {similar.odino}", similar.quote, found[similar.odino])

    # The proposed outcome agrees with the verdicts
    verdicts = {check.verdict for check in judgment.checks}
    proposed = judgment.proposed
    if proposed == "known_recall" and "same" not in verdicts:
        issues.append(Issue(code="inconsistent", message="proposed known_recall but no check has verdict 'same'"))
    if proposed in ("possible_new", "related_different") and "same" in verdicts:
        issues.append(Issue(code="inconsistent", message=f"proposed {proposed} but a check has verdict 'same'"))
    if proposed == "related_different" and "different" not in verdicts:
        issues.append(Issue(code="inconsistent",
                            message="proposed related_different but no check has verdict 'different'"))
    if proposed == "needs_info" and not judgment.questions:
        issues.append(Issue(code="inconsistent", message="proposed needs_info but asked no questions"))

    # Every number in the summary appears somewhere in what the AI was given or found
    evidence_json = json.dumps(evidence.model_dump(), ensure_ascii=False)
    allowed_text = " ".join([intake.text, complaint.year, complaint.received, evidence_json, *found.values()])
    allowed_numbers = set(NUMBER.findall(allowed_text))
    for number in NUMBER.findall(judgment.summary):
        if number not in allowed_numbers:
            issues.append(Issue(code="unsupported_number",
                                message=f"summary says {number}, which is not in the evidence"))
    return issues
