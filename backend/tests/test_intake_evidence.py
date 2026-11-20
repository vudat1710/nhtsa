"""Steps 1-2: intake masking/flags and evidence (replacements, complaints after the remedy, stats)."""
import pytest

from app.models import Complaint
from app.pipeline.evidence import gather
from app.pipeline.intake import MASK, cited_recalls, intake


@pytest.mark.parametrize("written", ["24V868", "24V-868", "24 V 868", "24v868000", "24V-868-000"])
def test_recall_numbers_are_masked_however_written(written):
    assert cited_recalls(f"see recall {written} please") == ["24V868000"]
    c = Complaint(make="X", model="Y", year="2024", received="2025-01-01",
                  text=f"I had recall {written} done but the car still stalls on the highway")
    assert intake(c).text == f"I had recall {MASK} done but the car still stalls on the highway"


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


def test_unknown_year_gathers_no_recalls(con, iccu_complaint):
    c = iccu_complaint.model_copy(update={"year": "9999"})
    ev = gather(con, c, intake(c))
    assert ev.recalls == [] and ev.investigations == []
