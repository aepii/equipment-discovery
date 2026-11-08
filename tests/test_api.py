"""The web API, with the mock model (see conftest.py)."""

import json

import pytest
from fastapi.testclient import TestClient

import store
from api import main, presentation, service

SCAFFOLD = presentation.EXAMPLES[1]["question"]


@pytest.fixture
def saved(monkeypatch):
    """Rows the API logs, instead of writing them anywhere."""
    rows = []
    monkeypatch.setattr(store, "save", lambda tab, row, background=True: rows.append((tab, row)))
    service.reset()
    return rows


@pytest.fixture
def client(saved):
    return TestClient(main.app)


def test_health_examples_equipment(client):
    assert client.get("/api/health").json()["provider"] == "mock"
    assert client.get("/api/examples").json() == presentation.EXAMPLES
    equipment = client.get("/api/equipment").json()
    assert equipment[0]["id"] == "EQ01" and "techniques" in equipment[0]


def test_ask_live_then_cache(client, saved):
    body = {"question": "How stiff is my porous scaffold in compression?", "session_id": "s1"}
    first = client.post("/api/ask", json=body).json()
    assert first["source"] == "live" and not first["rewritten"]
    result = first["result"]
    assert result["mode_label"] == "Equipment Finder"
    assert [c["id"] for c in result["primary"]] == ["EQ15"]
    assert result["removed_count"] == 1  # the mock's made-up EQ99
    assert result["plan"]["instrument_id"] == "EQ15"
    assert first["graph_dot"].startswith("digraph")
    assert client.post("/api/ask", json=body).json()["source"] == "cache"
    row = saved[0][1]
    assert row["source"] == "web" and row["session_id"] == "s1" and row["turn"] == 1


def test_naive_mode(client):
    reply = client.post("/api/ask", json={"question": "compress my scaffold", "mode": "naive"}).json()
    assert reply["result"]["mode_label"] == "General AI (no guidance)"
    assert reply["graph_dot"] is None and "text" in reply["result"]


def test_offline_uses_saved_answers(client, monkeypatch):
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    assert client.post("/api/ask", json={"question": SCAFFOLD}).json()["source"] == "saved"
    other = client.post("/api/ask", json={"question": "Something new entirely"}).json()
    assert other["result"]["error"] == service.OFFLINE_MESSAGE


def test_error_falls_back_to_saved_answer(client, monkeypatch):
    monkeypatch.setenv("MOCK_FAIL", "500:20")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    assert client.post("/api/ask", json={"question": SCAFFOLD}).json()["source"] == "saved"
    reply = client.post("/api/ask", json={"question": "compress something unsaved"}).json()
    assert reply["result"]["error"] and "Mock" not in reply["result"]["error"]


def test_session_limit(client, monkeypatch):
    monkeypatch.setenv("MAX_CALLS_PER_SESSION", "1")
    client.post("/api/ask", json={"question": "viscous one", "session_id": "x"})
    reply = client.post("/api/ask", json={"question": "viscous two", "session_id": "x"}).json()
    assert "limit" in reply["result"]["error"]


def test_stream_sends_stages_then_result(client):
    with client.stream("POST", "/api/ask/stream", json={"question": "viscous polymer"}) as response:
        text = "".join(response.iter_text())
    events = [block.split("\n") for block in text.strip().split("\n\n")]
    names = [lines[0].removeprefix("event: ") for lines in events]
    stages = [json.loads(lines[1].removeprefix("data: "))["stage"] for lines in events if lines[0] == "event: stage"]
    assert stages == ["reading", "matching", "checking", "done"]
    assert names[-1] == "result"


def test_stream_from_cache_skips_model_stages(client):
    body = {"question": "viscous polymer again"}
    client.post("/api/ask", json=body)
    with client.stream("POST", "/api/ask/stream", json=body) as response:
        text = "".join(response.iter_text())
    assert '"matching"' not in text and '"done"' in text


def test_feedback(client, saved):
    answer_id = client.post("/api/ask", json={"question": "compress scaffold"}).json()["answer_id"]
    ok = client.post("/api/feedback", json={"answer_id": answer_id, "overall": "good", "comment": "nice",
                                            "instrument_ratings": {"EQ15": "Good", "EQ99": "Wrong"}})
    assert ok.json() == {"ok": True}
    tab, row = saved[-1]
    assert tab == "feedback" and row["overall"] == "good" and row["instrument_ratings"] == "EQ15 Good"
    assert client.post("/api/feedback", json={"answer_id": "nope", "overall": "bad"}).status_code == 404


def test_rejects_empty_question(client):
    assert client.post("/api/ask", json={"question": "   "}).status_code == 422
