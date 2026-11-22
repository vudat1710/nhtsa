"""API: the analyst's workspace (check, suggestion, actions, emerging issues) and the operations portal (drills, runs).
Uses the test DB and a scripted model."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.ai.clients import LlmSetup, ScriptedChatClient
from app.api import deps, workspace
from app.data import queries
from app.main import app
from app.store.results import Store

GOOD = json.dumps({
    "checks": [{"campno": "24V868000", "verdict": "same", "complaint_quote": "ICCU failed again after",
                "recall_quote": "result in a loss of drive power", "reason": "Same failure."}],
    "proposed": "known_recall", "summary": "Matches the ICCU recall."})
NOTHING = json.dumps({"checks": [], "proposed": "possible_new", "summary": "Nothing fits."})


@pytest.fixture
def client(con, tmp_path, monkeypatch):
    turns: list = []
    store = Store(tmp_path / "app.db")
    monkeypatch.setattr(deps, "con", lambda: con)
    monkeypatch.setattr(deps, "store", lambda: store)
    monkeypatch.setattr(deps, "llm", lambda: LlmSetup(client=ScriptedChatClient(turns)))
    monkeypatch.setattr(deps, "vehicles", lambda: queries.vehicle_catalog(con))
    monkeypatch.setattr(deps, "components", lambda: queries.vehicle_components(con, min_complaints=1))
    monkeypatch.setattr(workspace, "demo_cases", lambda: [{"odino": 3, "title": "demo one"}])
    c = TestClient(app)
    c.turns = turns
    return c


def events(resp) -> list[dict]:
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def check(client, odino=3, answer=GOOD) -> dict:
    client.turns.append(answer)
    done = events(client.post(f"/api/tickets/{odino}/check"))[-1]
    assert done["type"] == "done"
    return client.get(f"/api/tickets/{odino}").json()


def test_check_gives_the_analyst_a_suggestion_in_their_terms(client):
    t = check(client)
    s = t["suggestion"]
    assert t["status"]["status"] == "suggested"
    assert s["headline"].startswith("Matches recall 24V-868")
    assert s["recall"]["covers"] == "2024 Hyundai Ioniq 5" and s["recall"]["replaced"] == ["24V-204"]
    assert s["recall"]["built"] == "2024 models built October 4, 2021 – October 9, 2024"
    assert "confirm with the VIN" in s["why"][0]["text"] and "is covered" not in s["why"][0]["text"]
    assert s["why"][1]["quotes"][0] == {"owner": "ICCU failed again after", "recall": "result in a loss of drive power"}
    assert "5 after it" in s["pattern"]["sentence"]  # 5 complaints after the remedy -> remedy concern
    primary = next(a for a in s["actions"] if a["primary"])
    assert primary["id"] == "link_close" and primary["issue_kind"] == "remedy_concern"
    assert "Dealers will inspect and replace the ICCU" in primary["message"]  # remedy text copied, not written
    assert "may be covered" in primary["message"] and "nhtsa.gov/recalls" in primary["message"]
    assert "is covered" not in primary["message"]  # only the VIN shows whether this car was built in range
    item = client.get("/api/inbox").json()[0]
    assert item["demo"] == "demo one" and item["suggestion"]["headline"] == s["headline"]


def test_link_and_close_flags_the_remedy_and_the_next_ticket_joins_the_same_issue(client):
    s = check(client)["suggestion"]
    primary = next(a for a in s["actions"] if a["primary"])
    body = {k: primary[k] for k in ("campno", "issue_title", "issue_kind", "issue_comp", "message")}
    status = client.post("/api/tickets/3/actions", json={"action": "link_close", "result_id": s["result_id"],
                                                         "suggested": shown(s), **body}).json()
    assert status["status"] == "resolved" and status["campno"] == "24V868000"
    issues = client.get("/api/issues").json()
    assert len(issues) == 1 and issues[0]["kind"] == "remedy_concern" and issues[0]["count"] == 1
    again = next(a for a in check(client)["suggestion"]["actions"] if a["primary"])
    assert again["issue_id"] == issues[0]["id"]  # suggested: add to the existing issue, not a duplicate
    history = [h["action"] for h in client.get("/api/tickets/3").json()["history"]]
    assert history == ["linked_recall", "reply_drafted"]   # drafted: nothing is sent to the owner


def shown(s: dict) -> dict | None:
    """The suggested action as the screen shows it, sent back with every action."""
    primary = next((a for a in s["actions"] if a["primary"]), None)
    return primary and {"action": primary["id"], "campno": primary["campno"], "issue_id": primary["issue_id"]}


def act(client, odino=3, **body):
    """An action on the run and suggestion the analyst is looking at."""
    s = client.get(f"/api/tickets/{odino}").json()["suggestion"]
    return client.post(f"/api/tickets/{odino}/actions", json={"result_id": s["result_id"], "suggested": shown(s),
                                                               **body})


def test_actions_are_validated(client):
    check(client)
    assert act(client, action="link_close", campno="99V999000", reason="x").status_code == 422
    assert act(client, action="close_no_action").status_code == 422            # needs a reason
    assert act(client, action="request_info", message=" ", reason="x").status_code == 422
    assert act(client, action="link_close", campno="24V868000").status_code == 422   # no reply and no reason
    assert act(client, action="close_no_action", reason="x").status_code == 200
    assert client.post("/api/tickets/4/actions", json={"action": "close_no_action", "reason": "x", "result_id": "r",
                                                       "suggested": None}).status_code == 409   # never checked


def test_a_rejected_action_leaves_no_trace(client):
    """Regression (review of 0eb81e1): a 422 still saved the 'disagreed' log entry."""
    check(client)
    assert act(client, action="link_close", campno="99V999000", reason="I disagree").status_code == 422
    t = client.get("/api/tickets/3").json()
    assert t["history"] == [] and t["status"]["status"] == "suggested"


def test_disagreeing_is_decided_by_the_server_not_the_client(client):
    check(client)   # suggests linking 24V-868
    s = client.get("/api/tickets/3").json()["suggestion"]
    other = client.post("/api/tickets/3/actions", json={"action": "close_no_action", "reason": "",
                                                        "result_id": s["result_id"], "suggested": shown(s),
                                                        "disagrees": False})
    assert other.status_code == 422                                      # the client saying "agrees" changes nothing
    assert act(client, action="link_close", campno="24V204000", message="Hi").status_code == 422  # another recall
    assert act(client, action="link_close", campno="24V204000", message="Hi", reason="older recall fits").json()
    assert [h["action"] for h in client.get("/api/tickets/3").json()["history"]][0] == "disagreed"


def test_an_action_on_a_suggestion_that_was_replaced_is_refused(client):
    """Regression (review of 0eb81e1): the action was logged against the newest run, not the one the analyst saw."""
    seen = check(client)["suggestion"]
    check(client, answer=NOTHING)                                         # checked again meanwhile
    stale = client.post("/api/tickets/3/actions", json={"action": "close_no_action", "reason": "x",
                                                        "result_id": seen["result_id"], "suggested": shown(seen)})
    assert stale.status_code == 409 and "checked again" in stale.json()["detail"]
    assert client.get("/api/tickets/3").json()["history"] == []


def test_an_action_on_a_suggestion_that_changed_is_refused(client):
    """Regression (own review): the run was the same, but a colleague opened a matching emerging issue meanwhile, so
    the suggestion became "add to the existing issue". The analyst who clicked what they saw was told they disagreed,
    and with a reason a second issue with the same title was opened."""
    s = check(client, answer=NOTHING)["suggestion"]
    seen = next(a for a in s["actions"] if a["primary"])
    tickets = deps.store().tickets
    with tickets.transaction():                                           # the colleague's escalation
        colleague = tickets.create_issue(seen["issue_title"], "new_defect", "HYUNDAI", "IONIQ 5", seen["issue_comp"],
                                         None)
    body = {"action": "new_issue", "result_id": s["result_id"], "suggested": shown(s), "issue_kind": "new_defect",
            "issue_title": seen["issue_title"], "issue_comp": seen["issue_comp"]}
    changed = client.post("/api/tickets/3/actions", json=body)
    assert changed.status_code == 409 and "suggestion changed" in changed.json()["detail"]
    assert client.get("/api/tickets/3").json()["history"] == []           # nothing recorded
    now = next(a for a in client.get("/api/tickets/3").json()["suggestion"]["actions"] if a["primary"])
    assert (now["id"], now["issue_id"]) == ("add_to_issue", colleague)    # the reloaded screen shows the new one
    assert act(client, action="add_to_issue", issue_id=colleague, issue_kind="new_defect").status_code == 200
    history = [h["action"] for h in client.get("/api/tickets/3").json()["history"]]
    assert history == ["escalated"]                                       # followed the suggestion: no "disagreed"
    assert [i["id"] for i in client.get("/api/issues").json()] == [colleague]   # one issue, not two


def test_a_closed_ticket_must_be_reopened_first_and_a_double_click_does_nothing(client):
    check(client, answer=NOTHING)
    assert act(client, action="monitor", reason="x").status_code == 200   # not the suggestion, so a reason
    assert act(client, action="monitor", reason="x").status_code == 200   # the same click again: no second entry
    assert [h["action"] for h in client.get("/api/tickets/3").json()["history"]].count("monitoring") == 1
    assert act(client, action="close_no_action", reason="not a defect").status_code == 200
    assert act(client, action="monitor", reason="x").status_code == 409   # resolved: reopen first
    assert act(client, action="reopen").status_code == 422                # with a reason
    assert act(client, action="reopen", reason="owner called back").json()["status"] == "suggested"


def test_an_emerging_issue_for_another_vehicle_needs_a_reason(client):
    check(client, answer=NOTHING)
    other = deps.store().tickets
    with other.transaction():
        issue_id = other.create_issue("Toyota Camry brakes", "new_defect", "TOYOTA", "CAMRY", "SERVICE BRAKES", None)
    assert act(client, action="add_to_issue", issue_id=issue_id, issue_kind="new_defect").status_code == 422
    ok = act(client, action="add_to_issue", issue_id=issue_id, issue_kind="new_defect", reason="same supplier part")
    assert ok.json()["status"] == "escalated"


def test_no_recall_fits_escalates_to_a_new_emerging_issue(client):
    s = check(client, answer=NOTHING)["suggestion"]
    assert s["headline"].startswith("No matching recall found")
    primary = next(a for a in s["actions"] if a["primary"])
    assert primary["id"] == "new_issue" and primary["issue_kind"] == "new_defect"
    st = act(client, action="new_issue", issue_title=primary["issue_title"], issue_kind="new_defect").json()
    assert st["status"] == "escalated"
    assert client.get(f"/api/issues/{st['issue_id']}").json()["complaint_details"][0]["odino"] == 3


def test_a_single_unmatched_report_is_recorded_not_escalated(client):
    """No crash/fire/injury, no similar complaints, nothing recalled elsewhere: don't spend engineering's time yet."""
    s = check(client, odino=4, answer=NOTHING)["suggestion"]
    assert s["headline"].endswith("single report, record and watch")
    primary = next(a for a in s["actions"] if a["primary"])
    assert primary["id"] == "monitor"
    assert act(client, odino=4, action="monitor").json()["status"] == "monitoring"


def test_other_year_recall_counts_only_if_it_shares_failure_words():
    from app.workspace.suggest import shares_failure_words
    iccu = "The Integrated Charging Control Unit (ICCU) may become damaged and stop charging the 12-volt battery."
    assert shares_failure_words("ICCU failed without any notification, we were stranded", iccu)
    assert not shares_failure_words("The electrical system warning came on while driving", iccu)
    shouting = "TOYOTA IS RECALLING CERTAIN TACOMA VEHICLES FOR FAILING TO COMPLY WITH TIRE LOAD LABELING."
    assert not shares_failure_words("Regarding FALKEN WILDPEAK tires on our TACOMA, worn out early", shouting,
                                    {"toyota", "tacoma"})


def test_ops_drill_never_changes_what_the_analyst_sees(client):
    check(client)
    done = events(client.post("/api/ops/drill/3", params={"fault": "llm_down"}))[-1]
    run = client.get(f"/api/ops/runs/{done['result_id']}").json()
    assert run["decision"]["source"] == "fallback" and run["fault"] == "llm_down"
    assert client.get("/api/tickets/3").json()["suggestion"]["check_note"] is None  # still the AI-verified answer
    assert {r["label"] for r in client.get("/api/ops/runs").json()} == {"queue", "ops"}
    assert client.post("/api/ops/drill/3", params={"fault": "nope"}).status_code == 422


def test_fallback_tells_the_analyst_to_check(client):
    events(client.post("/api/tickets/3/check"))  # no scripted answer -> the model "fails" -> fallback
    s = client.get("/api/tickets/3").json()["suggestion"]
    assert "Nothing was compared" in s["check_note"] and s["headline"].startswith("Not checked by the AI")
    assert [a["id"] for a in s["actions"] if a["primary"]] == ["recheck"]   # a model is configured: check again
    assert all(not (a["id"] == "link_close" and a["primary"]) for a in s["actions"])


def test_without_a_model_checks_use_the_rules(client, monkeypatch):
    monkeypatch.setattr(deps, "llm", lambda: None)
    assert events(client.post("/api/tickets/3/check"))[-1]["type"] == "done"
    s = client.get("/api/tickets/3").json()["suggestion"]
    assert "The AI is off" in s["check_note"] and "recheck" not in [a["id"] for a in s["actions"]]
    assert client.get("/api/ops/health").json()["model"] is None
    # nothing is suggested (no AI, no crash/fire/injury): the inbox shows no action instead of failing
    item = next(i for i in client.get("/api/inbox").json() if i["odino"] == 3)
    assert item["suggestion"]["action"] is None


NEW = {"make": "HYUNDAI", "model": "IONIQ 5", "year": "2024", "component": "ELECTRICAL SYSTEM",
       "text": "Stop Vehicle Immediately came on and the car lost drive power. The ICCU failed again after the recall "
               "repair last month.", "injured": 0}


def test_the_form_offers_nhtsa_names_only(client):
    assert client.get("/api/vehicles").json() == ["HYUNDAI"]
    assert client.get("/api/vehicles", params={"make": "HYUNDAI"}).json() == ["IONIQ 5"]
    assert client.get("/api/vehicles", params={"make": "HYUNDAI", "model": "IONIQ 5"}).json() == ["2024"]
    assert "ELECTRICAL SYSTEM" in client.get("/api/components").json()


def test_a_typed_complaint_is_a_ticket_like_any_other(client):
    odino = client.post("/api/complaints", json=NEW).json()["odino"]
    assert odino == -1                                           # negative: never an NHTSA id
    assert client.get("/api/inbox").json()[0]["odino"] == -1    # newest typed complaint first
    t = check(client, odino=-1)
    assert t["complaint"]["received"] == date.today().isoformat()
    assert t["suggestion"]["headline"].startswith("Matches recall 24V-868")
    assert [s["kind"] for s in t["trail"]][0] == "read"
    st = act(client, odino=-1, action="new_issue", issue_title="ICCU again", issue_kind="new_defect",
             reason="fix not holding").json()
    assert client.get(f"/api/issues/{st['issue_id']}").json()["complaint_details"][0]["odino"] == -1
    assert client.get("/api/issues").json()[0]["count"] == 1
    done = events(client.post("/api/ops/drill/-1", params={"fault": "llm_down"}))[-1]
    assert done["type"] == "done"


@pytest.mark.parametrize("change", [{"model": "IONIQ5"}, {"year": "2019"}, {"component": "ENGINE STUFF"},
                                    {"text": "   "}, {"text": ""}])
def test_a_typed_complaint_must_name_an_nhtsa_vehicle_and_say_something(client, change):
    assert client.post("/api/complaints", json=NEW | change).status_code == 422

def test_a_new_run_waits_while_an_action_is_being_checked_and_saved(client):
    """Own review: the checks ran outside the lock, so a re-check could land between "this is the run the analyst
    saw" and the save. A run is now saved under the same lock the whole action holds."""
    import threading

    check(client)
    store = deps.store()
    run = store.latest("queue")[3].model_copy(update={"id": "newer"})
    with store.tickets.lock:                                  # an action is being checked and saved
        saver = threading.Thread(target=store.save, args=(run, "queue"))
        saver.start()
        saver.join(timeout=0.3)
        assert saver.is_alive()                               # the new run waits
        assert store.latest("queue")[3].id != "newer"
    saver.join(timeout=5)
    assert store.latest("queue")[3].id == "newer"             # and lands right after
