import pytest
from fastapi.testclient import TestClient


def test_health_reports_demo_mode(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["demo_mode"] is True
    assert body["model"] == "demo-agent"
    assert body["web_search"] is False


def test_index_page_is_served(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Nebula Knowledge" in response.text


def test_chat_runs_calculator_tool_and_remembers_session(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "帮我算一下 (12 + 8) * 3", "session_id": "test-session"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "test-session"
    assert body["team_id"] == "default"
    assert body["demo_mode"] is True
    assert body["answer"] == "计算结果是 **60**。"
    assert body["tool_calls"] == [
        {
            "id": body["tool_calls"][0]["id"],
            "name": "calculator",
            "args": {"expression": "(12 + 8) * 3"},
            "result": "60",
        }
    ]

    history = client.get("/api/sessions/test-session/history").json()
    assert [item["role"] for item in history["messages"]] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert history["messages"][0]["content"] == "帮我算一下 (12 + 8) * 3"


def test_chat_uses_previous_turn_context(client: TestClient) -> None:
    first = client.post(
        "/api/chat",
        json={"message": "现在几点了？", "session_id": "memory-session"},
    )
    assert first.status_code == 200
    assert first.json()["tool_calls"][0]["name"] == "current_time"

    history = client.get("/api/sessions/memory-session/history").json()
    assert len(history["messages"]) == 4
    assert history["messages"][1]["tool_calls"][0]["name"] == "current_time"
    assert "UTC+08:00" in history["messages"][2]["content"]


def test_sessions_are_isolated(client: TestClient) -> None:
    client.post(
        "/api/chat",
        json={"message": "1 + 1", "session_id": "session-a"},
    )

    history_b = client.get("/api/sessions/session-b/history").json()
    assert history_b["messages"] == []


def test_delete_session_clears_history(client: TestClient) -> None:
    client.post(
        "/api/chat",
        json={"message": "1 + 1", "session_id": "to-delete"},
    )
    assert client.delete("/api/sessions/to-delete").status_code == 204

    history = client.get("/api/sessions/to-delete/history").json()
    assert history["messages"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"message": ""},
        {"message": "   "},
        {"message": "hello", "session_id": "../etc/passwd"},
    ],
)
def test_invalid_requests_are_rejected(client: TestClient, payload: dict) -> None:
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 422


def test_unknown_session_returns_empty_history(client: TestClient) -> None:
    response = client.get("/api/sessions/never-seen/history")

    assert response.status_code == 200
    assert response.json()["messages"] == []
