"""API: queue, streamed case run, typed complaint, review rules, health. Uses the test DB and a scripted model."""
import json

import pytest
from fastapi.testclient import TestClient

from app.ai.clients import LlmSetup, ScriptedChatClient
from app.api import cases, deps
from app.main import app
from app.store.results import Store

GOOD = json.dumps({
    "checks": [{"campno": "24V868000", "verdict": "same", "complaint_quote": "ICCU failed again after",
                "recall_quote": "result in a loss of drive power", "reason": "Same failure."}],
    "proposed": "known_recall", "summary": "Matches the ICCU recall."})


@pytest.fixture
def client(con, tmp_path, monkeypatch):
    turns: list = []
    monkeypatch.setattr(deps, "con", lambda: con)
    store = Store(tmp_path / "app.db")
    monkeypatch.setattr(deps, "store", lambda: store)
    monkeypatch.setattr(deps, "llm", lambda: LlmSetup(client=ScriptedChatClient(turns)))
    monkeypatch.setattr(cases, "demo_cases", lambda: [{"odino": 3, "title": "demo one"}])
    c = TestClient(app)
    c.turns = turns
    return c


def events(resp) -> list[dict]:
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def test_run_streams_progress_then_stores_the_result(client):
    client.turns.append(GOOD)
    ev = events(client.post("/api/cases/3/run"))
    assert [e["step"] for e in ev if e["type"] == "step"] == ["intake", "evidence", "judge", "verify", "decide"]
    done = ev[-1]
    assert done["type"] == "done" and done["result"]["decision"]["campno"] == "24V868000"
    queue = client.get("/api/queue").json()
    assert queue[0]["odino"] == 3 and queue[0]["demo"] == "demo one"
    assert queue[0]["result"]["outcome"] == "known_recall"
    assert client.get("/api/cases/3").json()["result"]["id"] == done["result"]["id"]


def test_model_failure_still_answers_with_fallback(client):
    done = events(client.post("/api/cases/3/run", params={"fault": "llm_down"}))[-1]
    assert done["result"]["decision"]["source"] == "fallback"


def test_unknown_fault_and_missing_complaint_are_rejected(client):
    assert client.post("/api/cases/3/run", params={"fault": "nope"}).status_code == 422
    assert client.post("/api/cases/999/run").status_code == 404


def test_typed_complaint_runs_through_the_same_pipeline(client):
    client.turns.append(GOOD)
    body = {"make": "HYUNDAI", "model": "IONIQ 5", "year": "2024", "received": "2025-03-01",
            "components": ["ELECTRICAL SYSTEM"],
            "text": "The ICCU failed again after the dealer visit and the car lost power."}
    done = events(client.post("/api/complaints/run", json=body))[-1]
    assert done["result"]["decision"]["outcome"] == "known_recall" and done["result"]["complaint"]["odino"] is None


def test_review_queue_and_review_rules(client):
    no_match = json.dumps({"checks": [], "proposed": "possible_new", "summary": "Nothing fits."})
    client.turns.append(no_match)
    rid = events(client.post("/api/cases/3/run"))[-1]["result"]["id"]
    assert [r["result_id"] for r in client.get("/api/reviews").json()] == [rid]
    assert client.post(f"/api/results/{rid}/review", json={"result_id": rid, "action": "link_recall"}).status_code \
        == 422
    bad = {"result_id": rid, "action": "link_recall", "campno": "99V999000"}
    assert client.post(f"/api/results/{rid}/review", json=bad).status_code == 422
    ok = client.post(f"/api/results/{rid}/review", json={"result_id": rid, "action": "confirm_new", "note": "real"})
    assert ok.status_code == 200
    assert client.get("/api/reviews").json()[0]["review"]["action"] == "confirm_new"


def test_health(client):
    assert client.get("/api/health").json()["live_model"] is False
