"""删除历史会话后的可见性、提交记录保留及处理状态保护。"""
from fastapi.testclient import TestClient

from mock_travel.app import create_app
from test_assistant import wait_turn
from test_draft_interaction import fixture_state, form_payload, seed


def test_deleted_conversation_stays_hidden_without_removing_application(tmp_path):
    database = tmp_path / "demo.db"
    store, cid = seed(database)
    other = store.create_conversation()["id"]
    with TestClient(create_app(database)) as client:
        form = form_payload()
        accepted = client.post(f"/assistant/api/conversations/{cid}/submit", json=form)
        tid = accepted.json()["turnId"]
        assert wait_turn(client, tid)["status"] == "succeeded"
        applications = client.get("/mock/v1/travel/applications").json()["data"]
        assert applications["total"] == 1
        request_id = client.get(f"/assistant/api/conversations/{cid}").json()["state"]["lastSubmission"]["requestId"]
        receipt = client.get(f"/mock/v1/submissions/{request_id}").json()["data"]

        removed = client.delete(f"/assistant/api/conversations/{cid}")
        assert removed.status_code == 200, removed.text
        assert removed.json() == {"id": cid, "deleted": True}
        assert [x["id"] for x in client.get("/assistant/api/conversations").json()["items"]] == [other]
        assert client.get(f"/assistant/api/conversations/{cid}").status_code == 404
        assert client.get(f"/assistant/api/turns/{tid}").status_code == 404
        assert client.post(f"/assistant/api/conversations/{cid}/submit", json=form).status_code == 404
        assert client.post(f"/assistant/api/conversations/{cid}/messages", json={
            "text": "安排出差", "clientRequestId": "seed-" + cid,
        }).status_code == 404
        assert client.delete(f"/assistant/api/conversations/{cid}").status_code == 200
        assert client.get("/mock/v1/travel/applications").json()["data"] == applications
        assert client.get(f"/mock/v1/submissions/{request_id}").json()["data"] == receipt

    with TestClient(create_app(database)) as client:
        assert [x["id"] for x in client.get("/assistant/api/conversations").json()["items"]] == [other]
        assert client.get(f"/assistant/api/conversations/{cid}").status_code == 404


def test_running_conversation_cannot_be_deleted(tmp_path):
    database = tmp_path / "demo.db"
    store, cid = seed(database)
    with TestClient(create_app(database)) as client:
        tid, _ = store.start_turn(cid, "补充事由", "running-before-delete")
        response = client.delete(f"/assistant/api/conversations/{cid}")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONVERSATION_BUSY"
        assert client.get(f"/assistant/api/conversations/{cid}").json()["activeTurnId"] == tid
        store.finish(tid, "已处理。", "succeeded", state=fixture_state())
        assert client.delete(f"/assistant/api/conversations/{cid}").status_code == 200


def test_unknown_submission_keeps_its_recovery_conversation(tmp_path):
    state = fixture_state()
    state["last_submission"] = {"draft_id": "D-form", "revision": 1, "status": "UNKNOWN", "request_id": "pending-submit"}
    _, cid = seed(tmp_path / "demo.db", state)
    with TestClient(create_app(tmp_path / "demo.db")) as client:
        response = client.delete(f"/assistant/api/conversations/{cid}")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SUBMISSION_UNCERTAIN"
        assert client.get(f"/assistant/api/conversations/{cid}").json()["state"]["lastSubmission"]["requestId"] == "pending-submit"


def test_deleted_draft_cannot_be_accepted_after_form_validation(tmp_path):
    from mock_travel.store import ServiceError
    import pytest

    store, cid = seed(tmp_path / "demo.db")
    payload = form_payload()
    _, before = store.form_request(cid, payload)
    with TestClient(create_app(tmp_path / "demo.db")) as client:
        assert client.delete(f"/assistant/api/conversations/{cid}").status_code == 200
    with pytest.raises(ServiceError) as error:
        store.start_form(cid, payload, {}, {}, expected_state=before)
    assert error.value.code == "CONVERSATION_NOT_FOUND"
