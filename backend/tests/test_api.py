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
    status = client.post("/api/tickets/3/actions", json={"action": "link_close", **body}).json()
    assert status["status"] == "resolved" and status["campno"] == "24V868000"
    issues = client.get("/api/issues").json()
    assert len(issues) == 1 and issues[0]["kind"] == "remedy_concern" and issues[0]["count"] == 1
    again = next(a for a in check(client)["suggestion"]["actions"] if a["primary"])
    assert again["issue_id"] == issues[0]["id"]  # suggested: add to the existing issue, not a duplicate
    history = [h["action"] for h in client.get("/api/tickets/3").json()["history"]]
    assert history == ["linked_recall", "replied_to_owner"]


def test_actions_are_validated(client):
    check(client)
    post = lambda body: client.post("/api/tickets/3/actions", json=body)  # noqa: E731
    assert post({"action": "link_close", "campno": "99V999000"}).status_code == 422
    assert post({"action": "close_no_action"}).status_code == 422            # needs a reason
    assert post({"action": "request_info", "message": " "}).status_code == 422
    assert post({"action": "close_no_action", "reason": "x", "disagrees": True, }).status_code == 200
    assert post({"action": "request_info", "message": "When?", "disagrees": True}).status_code == 422
    assert client.post("/api/tickets/4/actions", json={"action": "close_no_action", "reason": "x"}).status_code == 409


def test_no_recall_fits_escalates_to_a_new_emerging_issue(client):
    s = check(client, answer=NOTHING)["suggestion"]
    assert s["headline"].startswith("No recall covers this")
    primary = next(a for a in s["actions"] if a["primary"])
    assert primary["id"] == "new_issue" and primary["issue_kind"] == "new_defect"
    st = client.post("/api/tickets/3/actions", json={"action": "new_issue", "issue_title": primary["issue_title"],
                                                     "issue_kind": "new_defect"}).json()
    assert st["status"] == "escalated"
    assert client.get(f"/api/issues/{st['issue_id']}").json()["complaint_details"][0]["odino"] == 3


def test_a_single_unmatched_report_is_recorded_not_escalated(client):
    """No crash/fire/injury, no similar complaints, nothing recalled elsewhere: don't spend engineering's time yet."""
    s = check(client, odino=4, answer=NOTHING)["suggestion"]
    assert s["headline"].endswith("single report, record and watch")
    primary = next(a for a in s["actions"] if a["primary"])
    assert primary["id"] == "monitor"
    assert client.post("/api/tickets/4/actions", json={"action": "monitor"}).json()["status"] == "monitoring"


def test_other_year_recall_counts_only_if_it_shares_failure_words():
    from app.workspace.suggest import shares_failure_words
    iccu = "The Integrated Charging Control Unit (ICCU) may become damaged and stop charging the 12-volt battery."
    assert shares_failure_words("ICCU failed without any notification, we were stranded", iccu)
    assert not shares_failure_words("The electrical system warning came on while driving", iccu)
    shouting = "TOYOTA IS RECALLING CERTAIN TACOMA VEHICLES FOR FAILING TO COMPLY WITH TIRE LOAD LABELING."
    assert not shares_failure_words("Regarding FALKEN WILDPEAK tires on our TACOMA, worn out early", shouting,
                                    {"toyota", "tacoma"})


def test_ask_about_a_checked_ticket(client):
    assert client.post("/api/tickets/3/ask", json={"question": "Why this recall?"}).status_code == 409
    check(client)
    client.turns.append(json.dumps({"answer": "The records hold no repair history.", "citations": [],
                                    "scope": "not_in_records"}))
    turn = client.post("/api/tickets/3/ask", json={"question": "Was it repaired?"}).json()
    assert turn["verified"] and turn["answer"]["scope"] == "not_in_records"
    t = client.get("/api/tickets/3").json()
    assert [q["question"] for q in t["questions"]] == ["Was it repaired?"]
    assert [s["kind"] for s in t["trail"]][0] == "read"
    assert client.post("/api/tickets/3/ask", json={"question": "x"}).status_code == 422


def test_ops_drill_never_changes_what_the_analyst_sees(client):
    check(client)
    done = events(client.post("/api/ops/drill/3", params={"fault": "llm_down"}))[-1]
    run = client.get(f"/api/ops/runs/{done['result_id']}").json()
    assert run["decision"]["source"] == "fallback" and run["fault"] == "llm_down"
    assert client.get("/api/tickets/3").json()["suggestion"]["check_note"] is None  # still the AI-verified answer
    assert {r["label"] for r in client.get("/api/ops/runs").json()} == {"queue", "ops"}
    assert client.post("/api/ops/drill/3", params={"fault": "nope"}).status_code == 422


def test_fallback_tells_the_analyst_to_check(client):
    events(client.post("/api/tickets/3/check"))  # no scripted answer -> the model "fails" -> rules-only fallback
    assert "rules only" in client.get("/api/tickets/3").json()["suggestion"]["check_note"]


def test_without_a_model_checks_use_the_rules_and_questions_are_off(client, monkeypatch):
    monkeypatch.setattr(deps, "llm", lambda: None)
    assert events(client.post("/api/tickets/3/check"))[-1]["type"] == "done"
    assert "rules only" in client.get("/api/tickets/3").json()["suggestion"]["check_note"]
    assert client.post("/api/tickets/3/ask", json={"question": "Was it repaired?"}).status_code == 503
    assert client.get("/api/ops/health").json()["model"] is None


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
    client.turns.append(json.dumps({"answer": "The records hold no repair history.", "citations": [],
                                    "scope": "not_in_records"}))
    assert client.post("/api/tickets/-1/ask", json={"question": "Was it repaired?"}).json()["verified"]
    st = client.post("/api/tickets/-1/actions", json={"action": "new_issue", "issue_title": "ICCU again",
                                                      "issue_kind": "new_defect", "reason": "fix not holding",
                                                      "disagrees": True}).json()
    assert client.get(f"/api/issues/{st['issue_id']}").json()["complaint_details"][0]["odino"] == -1
    assert client.get("/api/issues").json()[0]["count"] == 1
    done = events(client.post("/api/ops/drill/-1", params={"fault": "llm_down"}))[-1]
    assert done["type"] == "done"


@pytest.mark.parametrize("change", [{"model": "IONIQ5"}, {"year": "2019"}, {"component": "ENGINE STUFF"},
                                    {"text": "   "}, {"text": ""}])
def test_a_typed_complaint_must_name_an_nhtsa_vehicle_and_say_something(client, change):
    assert client.post("/api/complaints", json=NEW | change).status_code == 422
