"""验证本地助手在 Dify HTTP 边界上的会话、请求回放与确认行为。"""
import json
import time
import asyncio

import pytest

import httpx
from fastapi.testclient import TestClient

from mock_travel.app import create_app
from mock_travel.dify_client import DifyService
from mock_travel.dify_probe import DifyConfig
from mock_travel.assistant_store import AssistantStore
from mock_travel.store import ServiceError


def upstream_fixture(*, variables_status=200):
    messages = []
    session = {"flow_state": "READY_TO_CONFIRM", "draft": {"draft_id": "draft-1", "revision": 2},
               "confirmation": {"draft_id": "draft-1", "revision": 2, "fingerprint": "hash-2"},
               "pending": [], "last_submission": {}}

    def server(request):
        assert request.headers["Authorization"] == "Bearer app-test-secret"
        if request.url.path.endswith("/chat-messages"):
            payload = json.loads(request.content)
            messages.append(payload)
            cid = payload["conversation_id"] or "dify-" + payload["user"]
            events = [{"event": "message", "conversation_id": cid, "answer": "草稿已整理"},
                      {"event": "message_end", "conversation_id": cid, "message_id": "message-1"}]
            return httpx.Response(200, text="".join("data: " + json.dumps(event) + "\n\n" for event in events),
                                  headers={"Content-Type": "text/event-stream"})
        if request.url.path.endswith("/variables"):
            if variables_status != 200:
                return httpx.Response(variables_status, json={"code": "unavailable"})
            return httpx.Response(200, json={"data": [{"name": "cv_session", "value": json.dumps(session)}]})
        return httpx.Response(404, json={"code": "not_found"})

    service = DifyService(DifyConfig("https://api.dify.ai/v1", "app-test-secret", "测试应用"),
                          transport=httpx.MockTransport(server))
    return service, messages


def wait_turn(client, turn_id):
    for _ in range(100):
        result = client.get("/assistant/api/turns/" + turn_id).json()
        if result["status"] != "running":
            return result
        time.sleep(0.01)
    raise AssertionError("模拟上游任务未结束")


def test_real_dify_boundary_preserves_conversation_and_hides_key(tmp_path):
    service, calls = upstream_fixture()
    with TestClient(create_app(tmp_path / "demo.sqlite3", dify_service=service)) as client:
        conversation = client.post("/assistant/api/conversations", json={}).json()
        cid = conversation["id"]
        for number, query in enumerate(["明天去上海参加会议，后天回杭州", "把事由改为拜访客户"]):
            response = client.post(f"/assistant/api/conversations/{cid}/messages",
                                   json={"text": query, "clientRequestId": f"request-{number}"})
            assert response.status_code == 202
            assert wait_turn(client, response.json()["turnId"])["status"] == "succeeded"
        detail = client.get("/assistant/api/conversations/" + cid)
        assert len(detail.json()["messages"]) == 4
        assert detail.json()["state"]["canSubmit"] is True
        assert detail.json()["state"]["revision"] == 2
        assert "app-test-secret" not in detail.text
        assert calls[0]["conversation_id"] == ""
        assert calls[1]["conversation_id"] == "dify-" + calls[0]["user"]
        assert calls[0]["user"] == calls[1]["user"]


def test_repeated_client_request_does_not_repeat_dify_call(tmp_path):
    service, calls = upstream_fixture()
    with TestClient(create_app(tmp_path / "demo.sqlite3", dify_service=service)) as client:
        cid = client.post("/assistant/api/conversations", json={}).json()["id"]
        path = f"/assistant/api/conversations/{cid}/messages"
        payload = {"text": "明天去上海", "clientRequestId": "repeat-1"}
        first = client.post(path, json=payload).json()
        wait_turn(client, first["turnId"])
        replay = client.post(path, json=payload)
        assert replay.json()["turnId"] == first["turnId"]
        assert len(calls) == 1
        conflict = client.post(path, json={**payload, "text": "改去北京"})
        assert conflict.status_code == 409


def test_stale_confirmation_is_rejected_before_dify(tmp_path):
    service, calls = upstream_fixture()
    with TestClient(create_app(tmp_path / "demo.sqlite3", dify_service=service)) as client:
        cid = client.post("/assistant/api/conversations", json={}).json()["id"]
        path = f"/assistant/api/conversations/{cid}/messages"
        first = client.post(path, json={"text": "明天去上海", "clientRequestId": "draft-turn"})
        wait_turn(client, first.json()["turnId"])
        stale = client.post(path, json={"text": "确认提交", "clientRequestId": "stale-confirmation",
                             "confirmation": {"draftId": "draft-1", "revision": 1, "fingerprint": "hash-1"}})
        assert stale.status_code == 409
        assert len(calls) == 1
        assert stale.json()["error"]["code"] == "CONFIRMATION_STALE"


def test_conversations_persist_and_use_separate_dify_users(tmp_path):
    service, calls = upstream_fixture()
    database = tmp_path / "demo.sqlite3"
    with TestClient(create_app(database, dify_service=service)) as client:
        for number in range(2):
            cid = client.post("/assistant/api/conversations", json={}).json()["id"]
            response = client.post(f"/assistant/api/conversations/{cid}/messages",
                                   json={"text": "明天去上海", "clientRequestId": f"turn-{number}"})
            wait_turn(client, response.json()["turnId"])
        assert calls[0]["user"] != calls[1]["user"]
    with TestClient(create_app(database, dify_service=service)) as client:
        assert len(client.get("/assistant/api/conversations").json()["items"]) == 2
        assert len(client.get("/assistant/api/conversations/" + cid).json()["messages"]) == 2


def test_foreign_web_page_cannot_invoke_local_chat(tmp_path):
    service, calls = upstream_fixture()
    with TestClient(create_app(tmp_path / "demo.sqlite3", dify_service=service)) as client:
        response = client.post("/assistant/api/conversations", json={}, headers={"Origin": "https://unrelated.example"})
        assert response.status_code == 403
        assert calls == []


def test_older_refresh_cannot_overwrite_new_turn_confirmation(tmp_path):
    store = AssistantStore(tmp_path / "demo.sqlite3")
    cid = store.create_conversation()["id"]
    first, _ = store.start_turn(cid, "旧草稿", "first")
    old = {"flow_state": "READY_TO_CONFIRM", "draft": {"draft_id": "draft-1", "revision": 2},
           "confirmation": {"draft_id": "draft-1", "revision": 2, "fingerprint": "hash-2"}}
    store.finish(first, "已显示旧草稿", "succeeded", state=old)
    observed_generation = store.private_conversation(cid)["generation"]
    second, _ = store.start_turn(cid, "修改事由", "second")
    new = {"flow_state": "READY_TO_CONFIRM", "draft": {"draft_id": "draft-1", "revision": 3},
           "confirmation": {"draft_id": "draft-1", "revision": 3, "fingerprint": "hash-3"}}
    store.finish(second, "已显示新草稿", "succeeded", state=new)
    store.synchronize(cid, old, expected_generation=observed_generation)
    assert store.conversation(cid)["state"]["revision"] == 3
    with pytest.raises(ServiceError, match="草稿已经变化"):
        store.start_turn(cid, "确认提交", "old-confirm", {"draftId": "draft-1", "revision": 2, "fingerprint": "hash-2"})


def test_completed_reply_with_state_sync_error_is_uncertain(tmp_path):
    service, _ = upstream_fixture(variables_status=503)
    with TestClient(create_app(tmp_path / "demo.sqlite3", dify_service=service)) as client:
        cid = client.post("/assistant/api/conversations", json={}).json()["id"]
        turn = client.post(f"/assistant/api/conversations/{cid}/messages",
                           json={"text": "确认提交", "clientRequestId": "confirm-unknown"}).json()
        result = wait_turn(client, turn["turnId"])
        assert result["status"] == "uncertain"
        assert result["answer"] == "草稿已整理"


def test_stream_does_not_publish_a_partial_key():
    secret = "app-test-secret"

    def server(request):
        events = [{"event": "message", "conversation_id": "conv-safe", "answer": secret[:-1]},
                  {"event": "message", "conversation_id": "conv-safe", "answer": secret[-1:]},
                  {"event": "message_end", "conversation_id": "conv-safe"}]
        return httpx.Response(200, text="".join("data: " + json.dumps(event) + "\n\n" for event in events))

    async def check():
        chunks = []

        async def progress(answer, conversation_id):
            chunks.append(answer)

        service = DifyService(DifyConfig("https://api.dify.ai/v1", secret), transport=httpx.MockTransport(server))
        result = await service.chat("测试", "", "safe-user", progress)
        assert result["answer"] == "[密钥已隐藏]"
        assert all("app-test" not in answer for answer in chunks)

    asyncio.run(check())
