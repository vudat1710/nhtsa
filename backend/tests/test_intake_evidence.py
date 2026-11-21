"""Steps 1-2: intake masking/flags and evidence (replacements, complaints after the remedy, stats)."""
import pytest

from app.models import Complaint, RecallItem
from app.pipeline.evidence import gather, link_replacements, replacement_mentions
from app.pipeline.intake import MASK, cited_recalls, intake, mask_recall_numbers


@pytest.mark.parametrize("written", ["24V868", "24V-868", "24 V 868", "24v868000", "24V-868-000"])
def test_recall_numbers_are_masked_however_written(written):
    assert cited_recalls(f"see recall {written} please") == ["24V868000"]
    c = Complaint(make="X", model="Y", year="2024", received="2025-01-01",
                  text=f"I had recall {written} done but the car still stalls on the highway")
    assert intake(c).text == f"I had recall {MASK} done but the car still stalls on the highway"


def test_masking_also_removes_the_component_named_after_the_number():
    """Hotline staff write the recall's component in brackets after its number: that would leak the answer."""
    text = "The contact related the failure to NHTSA Campaign Number: 16V248000 (Power Train). It stalled."
    assert mask_recall_numbers(text) == f"The contact related the failure to NHTSA Campaign Number: {MASK}. It stalled."
    assert mask_recall_numbers("Recall 24V868 done (twice)") == f"Recall {MASK} done (twice)"  # only right after


def test_flags():
    c = Complaint(make="X", model="Y", year="9999", received="2025-01-01", crash=1, text="car broke",
                  components=["UNKNOWN OR OTHER"])
    assert intake(c).flags == ["unknown_year", "unknown_component", "short_text", "severe"]


def test_evidence_links_replacement_and_counts_complaints_after_remedy(con, iccu_complaint):
    ev = gather(con, iccu_complaint, intake(iccu_complaint))
    by = {r.campno: r for r in ev.recalls}
    assert list(by) == ["24V868000", "24V204000", "25V001000"]      # same component first, newest first
    assert by["24V204000"].replaced_by == "24V868000"
    assert by["24V868000"].replaced_by is None
    assert by["24V868000"].complaints_since == 6                    # 5 in Dec 2024 + 1 in Feb 2025
    assert by["25V001000"].same_component is False
    assert (ev.stats.total, ev.stats.last_12_months, ev.stats.crash) == (8, 7, 1)  # complaint 1 is > 12 months old
    assert [i.action for i in ev.investigations] == ["PE23011"]


def test_build_dates_are_the_widest_published_range_or_none(con, iccu_complaint):
    by = {r.campno: r for r in gather(con, iccu_complaint, intake(iccu_complaint)).recalls}
    assert (by["24V868000"].built_from, by["24V868000"].built_to) == ("2021-10-04", "2024-10-09")  # over 2 lines
    assert (by["25V001000"].built_from, by["25V001000"].built_to) == (None, None)  # end before start: not usable


def test_unknown_year_gathers_no_recalls(con, iccu_complaint):
    c = iccu_complaint.model_copy(update={"year": "9999"})
    ev = gather(con, c, intake(c))
    assert ev.recalls == [] and ev.investigations == []


# Real wordings from NHTSA recall texts (recall that says it in brackets): (newer, older) recalls named.
@pytest.mark.parametrize("text, newer, older", [
    ("This recall is replaced by NHTSA recall number 24V-868. Vehicles already repaired",  # 24V204000
     ["24V868000"], []),
    ("THIS CAMPAIGN HAS BEEN SUPERSEDED BY CAMPAIGN NO. 02V-295. DEALERS", ["02V295000"], []),  # 00V025000
    ("THIS RECALL HAS BEEN SUPERSEDED (REPLACED) BY RECALL 07V302 (FL-504).", ["07V302000"], []),  # 06V205000
    ("THIS RECALL HAS BEEN SUPERSEDED (PLEASE SEE 07V401/SC0324).", ["07V401000"], []),  # 06V392000
    ("THIS RECALL HAS BEEN SUPERSEDED BY SAFETY RECALL CAMPAIGN 11E-016.", ["11E016000"], []),  # 10E058000
    ("This recall was replaced by 25V798.", ["25V798000"], []),  # 25V376000
    ("Recall 21V469 supersedes this recall.", ["21V469000"], []),  # 20V394000
    ("Note: GM filed a new recall, number 21V-504 that supersedes this recall.", ["21V504000"], []),  # 20V736000
    ("This recall campaign supersedes previous recall campaign 11V-594.", [], ["11V594000"]),  # 12V370000
    ("Note: This recall supersedes recalls 13V-029 and 14V-147. Vehicles", [], ["13V029000", "14V147000"]),
    ("This recall supersedes and expands NHTSA recall number 22V-486.", [], ["22V486000"]),  # 22V556000
    ("THIS ACTION WILL SUPERSEDE AND EXPAND A PREVIOUS SAFETY RECALL (PLEASE SEE 07V-104).", [], ["07V104000"]),
    ("Note: 18V-122 was superseded by this recall.", [], ["18V122000"]),  # 18V685000
    ("The remedy will also remedy recall 16V-073, therefore that recall will be superseded by this one.",
     [], ["16V073000"]),  # 16V951000
    # not a replacement: a part replaced by dealers under another recall (14E021000, 22V431000)
    ("Any switches already installed will be replaced by GM dealers as part of NHTSA recall 14V-047.", [], []),
    ("This recall excludes wheel rims previously replaced by warranty and/or under NHTSA Recall No. 13V-507.", [], []),
])
def test_replacement_wordings(text, newer, older):
    assert replacement_mentions(text) == (newer, older)


def recall(campno: str, filed: str, remedy: str = "") -> RecallItem:
    return RecallItem(campno=campno, filed=filed, influenced_by="MFR", units=None, components=[], comps=[],
                      same_component=True, defect="", consequence="", remedy=remedy)


def test_replacements_link_only_candidates_and_never_backwards_in_time():
    older = recall("13V029000", "2013-01-10")
    newer = recall("15V043000", "2015-01-20", "This recall supersedes recalls 13V-029 and 14V-147.")
    link_replacements([older, newer])  # 14V147000 is not a candidate: ignored
    assert older.replaced_by == "15V043000" and newer.replaced_by is None

    claims_newer = recall("22V100000", "2022-05-01", "This recall was replaced by 21V900.")
    filed_before = recall("21V900000", "2021-05-01")
    link_replacements([claims_newer, filed_before])  # the "replacement" was filed earlier: not linked
    assert claims_newer.replaced_by is None and filed_before.replaced_by is None
