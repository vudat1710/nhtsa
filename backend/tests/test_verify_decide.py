"""Steps 4-5: the verifier catches every kind of unsupported claim; the rules decide outcome and confidence."""
import pytest

from app.models import Judgment, RecallCheck, SimilarComplaint
from app.pipeline.decide import decide
from app.pipeline.evidence import gather
from app.pipeline.intake import intake
from app.pipeline.verify import quote_problem, verify

SAME_868 = RecallCheck(campno="24V868000", verdict="same", complaint_quote="would not accelerate. The ICCU failed",
                       recall_quote="may become damaged and stop charging", reason="Same ICCU failure.")
SAME_204 = SAME_868.model_copy(update={"campno": "24V204000"})
AIRBAG_DIFF = RecallCheck(campno="25V001000", verdict="different", complaint_quote="Car said Stop Vehicle",
                          recall_quote="failing to suppress the air bag", reason="Different system.")


@pytest.fixture
def case(con, iccu_complaint):
    it = intake(iccu_complaint)
    return iccu_complaint, it, gather(con, iccu_complaint, it)


def judgment(*checks, proposed="known_recall", **kw) -> Judgment:
    return Judgment(checks=list(checks), proposed=proposed, summary=kw.pop("summary", "Matches the ICCU recall."),
                    **kw)


# ---------- verify ----------

def test_good_judgment_passes(case):
    assert verify(judgment(SAME_868, SAME_204), *case, found={}) == []


@pytest.mark.parametrize("change, code", [
    ({"campno": "99V999000"}, "unknown_recall"),
    ({"complaint_quote": "the car exploded on the highway"}, "quote_not_found"),
    ({"recall_quote": "may become damaged and catch fire"}, "quote_not_found"),
    ({"complaint_quote": "ICCU failed"}, "quote_not_found"),                     # fewer than 3 words
    ({"complaint_quote": "Recall [recall no. removed] was"}, "quote_not_found"),  # quoting the mask
])
def test_verifier_catches(case, change, code):
    issues = verify(judgment(SAME_868.model_copy(update=change)), *case, found={})
    assert code in {i.code for i in issues}


def test_quotes_ignore_case_spacing_and_curly_quotes(case):
    check = SAME_868.model_copy(update={"complaint_quote": "WOULD  NOT accelerate.  the iccu failed"})
    assert verify(judgment(check), *case, found={}) == []


@pytest.mark.parametrize("source, quote, problem", [
    ("Zero airbags were deployed with either impact.", "airbags were deployed with either impact", "drops"),
    ("The car didn't stop when braking hard.", "stop when braking hard", "drops"),
    ("No warning lights came on at all.", "warning lights came on", "drops"),
    ("The airbags deployed with no warning at all.", "airbags deployed with", None),
    ("It was unbelievable how it stalled.", "believable how it", "middle of a word"),
])
def test_quote_cannot_cut_off_a_negation_or_a_word(source, quote, problem):
    found = quote_problem(quote, source)
    assert (found is None) if problem is None else (problem in found)


def test_similar_complaints_must_come_from_the_search(case):
    j = judgment(SAME_868, similar=[SimilarComplaint(odino=1, quote="car lost power on")])
    assert {i.code for i in verify(j, *case, found={})} == {"unknown_complaint"}
    assert verify(j, *case, found={1: "ICCU failed, car lost power on the highway"}) == []


def test_inconsistent_proposal_and_invented_numbers(case):
    assert "inconsistent" in {i.code for i in verify(judgment(AIRBAG_DIFF), *case, found={})}
    assert "inconsistent" in {i.code for i in verify(judgment(proposed="needs_info"), *case, found={})}
    j = judgment(SAME_868, summary="Matches; 4,812 similar complaints.")
    assert {i.code for i in verify(j, *case, found={})} == {"unsupported_number"}
    assert verify(judgment(SAME_868, summary="Failed at 16,000 miles."), *case, found={}) == []


# ---------- decide ----------

def test_known_recall_prefers_the_replacement_and_flags_complaints_after_remedy(case):
    d = decide(*case, judgment(SAME_868, SAME_204), "ai_verified")
    assert (d.outcome, d.campno, d.confidence) == ("known_recall", "24V868000", "high")
    assert {"superseded", "after_remedy"} <= set(d.flags) and d.escalate


def test_two_recalls_that_fit_lower_confidence(case):
    c, it, ev = case
    ev.recalls[1].replaced_by = None
    assert decide(c, it, ev, judgment(SAME_868, SAME_204), "ai_verified").confidence == "medium"


def test_partial_or_short_text_asks_for_info(case):
    partial = SAME_868.model_copy(update={"verdict": "partial"})
    d = decide(*case, judgment(partial, proposed="needs_info", questions=["When did it happen?"]), "ai_verified")
    assert (d.outcome, d.campno) == ("needs_info", "24V868000")
    c, it, ev = case
    it.flags.append("short_text")
    assert decide(c, it, ev, judgment(SAME_868), "ai_verified").outcome == "needs_info"


def test_same_part_different_failure_is_escalated(case):
    d = decide(*case, judgment(AIRBAG_DIFF, proposed="related_different"), "ai_verified")
    assert (d.outcome, d.escalate) == ("related_different", True)


def test_nothing_fits_is_a_possible_new_issue_with_pattern(case):
    d = decide(*case, judgment(proposed="possible_new"), "ai_verified")
    assert (d.outcome, d.confidence, d.escalate) == ("possible_new", "medium", True)
    assert "pattern" in d.flags


def test_rules_override_the_ai_and_say_so(case):
    d = decide(*case, judgment(SAME_868, proposed="possible_new"), "ai_verified")
    assert d.outcome == "known_recall" and "ai_disagreed" in d.flags


def test_unknown_year_needs_info_whatever_the_ai_says(case):
    c, it, ev = case
    it.flags.append("unknown_year")
    assert decide(c, it, ev, judgment(SAME_868), "ai_verified").outcome == "needs_info"


def test_baseline_picks_newest_same_component_not_a_replaced_one(case):
    d = decide(*case, None, "fallback")
    assert (d.outcome, d.campno, d.confidence) == ("known_recall", "24V868000", "low")
    assert d.reasons[0].startswith("Not AI-verified")
