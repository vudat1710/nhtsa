"""Agreement with owners' beliefs: the AI and the simple "newest recall on the same part" rule, with one yardstick."""
from test_workflow import GOOD, go

from app.eval.agreement import agreement, shortcut


def test_the_ai_and_the_simple_rule_are_scored_against_the_owners_recall(con, iccu_complaint):
    r = go(con, iccu_complaint, [GOOD])[0]            # the AI matches 24V-868
    rule = shortcut(r)
    assert rule == r.evidence.recalls[0].campno and r.evidence.recalls[0].same_component

    same = agreement([r], [{"odino": r.complaint.odino, "truth_campno": "24V868000"}], [])["a"]
    assert (same["ai_names_the_owners"]["k"], same["ai_names_a_different"]["k"]) == (1, 0)

    other = agreement([r], [{"odino": r.complaint.odino, "truth_campno": "24V204000"}], [])["a"]
    assert (other["ai_names_the_owners"]["k"], other["ai_names_a_different"]["k"]) == (0, 1)
    assert other["rule_names_a_different"]["k"] == int(rule != "24V204000")


def test_known_recall_when_none_existed_is_counted(con, iccu_complaint):
    r = go(con, iccu_complaint, [GOOD])[0]
    b = agreement([r], [], [{"odino": r.complaint.odino}])["b"]
    assert (b["ai_says_known_recall"]["k"], b["ai_escalates"]["k"], b["ai_escalates"]["n"]) == (1, 0, 1)
