from fastapi.testclient import TestClient

HANDBOOK = """# 报销制度

员工报销需要在费用发生后 30 天内提交发票。

# 年假制度

入职满一年的员工每年有 10 天带薪年假。
"""


def upload(
    client: TestClient,
    team_id: str,
    filename: str = "员工手册.md",
    content: str = HANDBOOK,
):
    return client.post(
        f"/api/teams/{team_id}/documents",
        files={"file": (filename, content.encode("utf-8"), "text/markdown")},
    )


def test_default_team_is_created(client: TestClient) -> None:
    teams = client.get("/api/teams")

    assert teams.status_code == 200
    body = teams.json()
    assert body[0]["id"] == "default"
    assert body[0]["name"] == "默认团队"


def test_upload_search_and_citations(client: TestClient) -> None:
    created = client.post("/api/teams", json={"name": "研发团队"})
    assert created.status_code == 201
    team_id = created.json()["id"]

    uploaded = upload(client, team_id)
    assert uploaded.status_code == 201
    document = uploaded.json()
    assert document["filename"] == "员工手册.md"
    assert document["chunk_count"] == 2

    chat = client.post(
        "/api/chat",
        json={
            "message": "报销需要在多少天内提交发票？",
            "team_id": team_id,
            "session_id": "kb-session",
        },
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["tool_calls"][0]["name"] == "search_knowledge"
    assert "30 天" in body["answer"]
    assert len(body["citations"]) == 1
    citation = body["citations"][0]
    assert citation["document"] == "员工手册.md"
    assert citation["document_id"] == document["id"]

    history = client.get(
        "/api/sessions/kb-session/history", params={"team_id": team_id}
    ).json()
    assistant = [item for item in history["messages"] if item["role"] == "assistant"][-1]
    assert assistant["citations"][0]["chunk_id"] == citation["chunk_id"]


def test_team_documents_are_isolated(client: TestClient) -> None:
    team_id = client.post("/api/teams", json={"name": "销售团队"}).json()["id"]
    assert upload(client, team_id).status_code == 201

    default_chat = client.post(
        "/api/chat",
        json={"message": "报销需要在多少天内提交发票？", "team_id": "default"},
    )
    assert default_chat.status_code == 200
    assert default_chat.json()["citations"] == []
    assert "没有找到" in default_chat.json()["answer"]

    default_docs = client.get("/api/teams/default/documents").json()
    assert default_docs["documents"] == []


def test_duplicate_upload_is_rejected(client: TestClient) -> None:
    assert upload(client, "default").status_code == 201
    duplicate = upload(client, "default", filename="copy.md")

    assert duplicate.status_code == 409
    assert "已经上传过" in duplicate.json()["detail"]


def test_delete_document_removes_it_from_search(client: TestClient) -> None:
    document = upload(client, "default").json()
    stats_before = client.get("/api/teams/default/stats").json()
    assert stats_before["documents"] == 1
    assert stats_before["chunks"] == 2

    deleted = client.delete(f"/api/teams/default/documents/{document['id']}")
    assert deleted.status_code == 204

    assert client.get("/api/teams/default/documents").json()["documents"] == []
    chat = client.post(
        "/api/chat",
        json={"message": "报销需要在多少天内提交发票？", "team_id": "default"},
    )
    assert chat.json()["citations"] == []
    assert "没有找到" in chat.json()["answer"]


def test_invalid_upload_type_and_unknown_team(client: TestClient) -> None:
    bad_type = client.post(
        "/api/teams/default/documents",
        files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
    )
    assert bad_type.status_code == 415

    missing_team = upload(client, "does-not-exist")
    assert missing_team.status_code == 404


def test_team_stats_and_document_download(client: TestClient) -> None:
    document = upload(client, "default").json()
    download = client.get(document["download_url"])

    assert download.status_code == 200
    assert "报销制度" in download.text
