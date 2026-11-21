"""queries.py: the as_of rule (no look-ahead) and query safety."""
from conftest import V

from app.data import queries


def test_recalls_only_before_as_of_and_same_component_first(con):
    recalls, total = queries.recalls_for(con, V, "2025-02-01", ["ELECTRICAL SYSTEM"])
    assert [r["campno"] for r in recalls] == ["24V868000", "24V204000", "25V001000"]  # 26V001000 is in the future
    assert total == 3


def test_recall_filed_on_complaint_day_is_not_visible(con):
    recalls, _ = queries.recalls_for(con, V, "2024-11-18", ["ELECTRICAL SYSTEM"])
    assert "24V868000" not in [r["campno"] for r in recalls]


def test_recall_groups_components_even_with_commas(con):
    recalls, _ = queries.recalls_for(con, V, "2025-02-01", ["ELECTRICAL SYSTEM"])
    r = next(r for r in recalls if r["campno"] == "24V868000")
    assert r["components"] == ["ELECTRICAL SYSTEM:Y", "POWER TRAIN:A, B"]
    assert r["comps"] == ["ELECTRICAL SYSTEM", "POWER TRAIN"]


def test_complaint_counts_exclude_self_future_and_other_components(con):
    c = queries.complaint_counts(con, V, ["ELECTRICAL SYSTEM"], as_of="2025-02-01", exclude=3)
    assert (c["total"], c["crash"], c["injury"], c["first"]) == (7, 1, 1, "2024-01-10")
    assert queries.complaint_counts(con, V, ["ELECTRICAL SYSTEM"], "2025-03-01", since="2024-11-18")["total"] == 6


def test_search_is_as_of_and_ignores_fts_syntax(con):
    hits = queries.search_complaints(con, V, 'ICCU" OR text:* NEAR(', as_of="2024-07-01")
    assert {h["odino"] for h in hits} == {1, 2}
    assert queries.search_complaints(con, V, "!!", as_of="2025-01-01") == []


def test_investigations_before_as_of_listed_once_with_this_vehicles_recall(con):
    found = queries.investigations_for(con, V, "2025-01-01")
    assert [i["action"] for i in found] == ["PE23011"]
    assert found[0]["campno"] == "24V204000"  # the Ioniq's line, not the Kia line listed first
    assert found[0]["closed"] == "2024-04-17"
    assert queries.investigations_for(con, V, "2023-01-01") == []


def test_investigation_outcome_after_as_of_is_hidden(con):
    # Opened 2023-06-08, recall 24V204000 filed 2024-03-15, closed 2024-04-17: on 2024-01-01 it was still open.
    found = queries.investigations_for(con, V, "2024-01-01")
    assert [i["action"] for i in found] == ["PE23011"]
    assert found[0]["closed"] is None and found[0]["campno"] is None
    found = queries.investigations_for(con, V, "2024-04-01")  # recall filed, investigation not yet closed
    assert found[0]["campno"] == "24V204000" and found[0]["closed"] is None
