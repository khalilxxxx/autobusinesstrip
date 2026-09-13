"""卡片快照、抽屉提交和失败保留的真实本地 API 回归。"""
import copy
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from mock_travel.app import create_app
from mock_travel.assistant_store import AssistantStore
from mock_travel.dify_client import DifyService
from mock_travel.dify_probe import DifyConfig
from test_assistant import wait_turn


def field(value):
    return {"value": value, "source": "USER", "evidence": value}


def fixture_state():
    draft = {"draft_id": "D-form", "revision": 1, "next_trip_id": 3,
             "applicant_id": "DEMO_EMP_001", "applicant_name": "演示员工", "department": "演示业务部",
             "payer_company": "演示科技公司", "travel_type": "NORMAL", "reason": "拜访客户",
             "all_transport": field(""), "scope_requests": {"companions": "", "activity": "", "excluded": ""},
             "basic_sources": {}, "open_clarifications": [], "trips": []}
    for i, (origin, destination, a, b, day) in enumerate([
        ("杭州", "上海", "330100", "DEMO_SHANGHAI", "2026-10-18"),
        ("上海", "杭州", "DEMO_SHANGHAI", "330100", "2026-10-20"),
    ], 1):
        draft["trips"].append({"id": "T" + str(i), "kind": "OUTBOUND" if i == 1 else "RETURN",
            "from_city": field(origin), "to_city": field(destination), "depart_date": field(day),
            "arrive_date": field(day), "transport": field("火车-二等座"),
            "resolved_from": {"place": origin, "name": origin, "code": a, "mapped": False},
            "resolved_to": {"place": destination, "name": destination, "code": b, "mapped": False},
            "resolved_transport": {"name": "火车-二等座", "code": "火车-二等座"}})
    fingerprint = hashlib.sha256(json.dumps(draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": "mvp1.2", "demo_case": "NORMAL", "demo_anchor_date": "2026-09-12",
            "flow_state": "READY_TO_CONFIRM", "draft": draft, "pending": [], "last_question": "",
            "confirmation": {"draft_id": "D-form", "revision": 1, "fingerprint": fingerprint},
            "last_submission": {}, "history": [],
            "dialogue": {"focus": {"draft_id": "", "revision": 0, "questions": []}, "recovery": {}}}


def seed(database, state=None):
    store = AssistantStore(database)
    cid = store.create_conversation()["id"]
    turn, _ = store.start_turn(cid, "安排出差", "seed-" + cid)
    store.progress(turn, "已整理", "dify-" + cid)
    store.finish(turn, "草稿已整理。\n\n默认与映射说明：\n- 默认杭州出发。\n\n请核对草稿。",
                 "succeeded", state=state or fixture_state())
    return store, cid


def form_payload():
    return {"clientRequestId": "form-submit-1", "draftId": "D-form", "revision": 1,
            "edits": {"travelType": "SHORT_TERM", "reason": "抽屉填写的项目验收", "trips": [
                {"id": "T1", "fromCity": "杭州", "toCity": "上海", "departDate": "2026-10-18",
                 "arriveDate": "2026-10-18", "transport": "火车-一等座"},
                {"id": "T2", "fromCity": "上海", "toCity": "杭州", "departDate": "2026-10-21",
                 "arriveDate": "2026-10-21", "transport": "飞机-经济舱"}]}}


def test_partial_draft_is_exposed_and_message_snapshot_is_immutable(tmp_path):
    state = fixture_state()
    state.update(flow_state="COLLECTING", confirmation={}, pending=[{"field": "reason", "question": "请填写事由"}])
    state["draft"]["reason"] = ""
    store, cid = seed(tmp_path / "demo.db", state)
    original = store.conversation(cid)
    assert original["state"]["draft"]["reason"] == ""
    assert original["state"]["draft"]["trips"][0]["toCity"] == "上海"
    assert original["state"]["canSubmit"] is False
    second, _ = store.start_turn(cid, "项目验收", "second")
    state["draft"].update(reason="项目验收", revision=2)
    store.finish(second, "已更新事由", "succeeded", state=state)
    messages = store.conversation(cid)["messages"]
    assert messages[1]["draftState"]["draft"]["reason"] == ""
    assert messages[3]["draftState"]["draft"]["reason"] == "项目验收"
    assert "默认与映射说明" not in messages[1]["content"]
    assert "默认杭州出发" not in messages[1]["content"]


def test_form_submits_latest_fields_and_replays_same_request(tmp_path):
    database = tmp_path / "demo.db"
    _, cid = seed(database)
    with TestClient(create_app(database)) as client:
        path = f"/assistant/api/conversations/{cid}/submit"
        response = client.post(path, json=form_payload())
        assert response.status_code == 202, response.text
        result = wait_turn(client, response.json()["turnId"])
        assert result["status"] == "succeeded", result
        items = client.get("/mock/v1/travel/applications").json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["request"]["remark"] == "抽屉填写的项目验收"
        assert items[0]["request"]["dqydbg"] == "Y"
        assert items[0]["request"]["trips"][1]["dateFrom"] == "2026-10-21"
        assert items[0]["request"]["trips"][1]["tool"] == "飞机-经济舱"
        detail = client.get(f"/assistant/api/conversations/{cid}").json()
        assert detail["state"]["phase"] == "SUBMITTED"
        assert detail["state"]["draft"]["reason"] == "抽屉填写的项目验收"
        replay = client.post(path, json=form_payload())
        assert replay.json()["turnId"] == response.json()["turnId"]
        assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 1
        altered = form_payload()
        altered["edits"]["reason"] = "其他事由"
        assert client.post(path, json=altered).status_code == 409


def test_failed_form_keeps_edited_draft_after_restart(tmp_path):
    database = tmp_path / "demo.db"
    _, cid = seed(database)
    with TestClient(create_app(database)) as client:
        client.put("/mock/v1/scenario", json={"submissionResult": "FAILURE", "failureMessage": "付款公司暂不可用"})
        response = client.post(f"/assistant/api/conversations/{cid}/submit", json=form_payload())
        assert response.status_code == 202, response.text
        result = wait_turn(client, response.json()["turnId"])
        assert "付款公司暂不可用" in result["answer"]
        assert "差旅系统" in result["answer"] and "草稿" in result["answer"]
        assert "单独回复" not in result["answer"]
        assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 0
    with TestClient(create_app(database)) as client:
        state = client.get(f"/assistant/api/conversations/{cid}").json()["state"]
        assert state["lastSubmission"]["status"] == "FAILED"
        assert state["draft"]["reason"] == "抽屉填写的项目验收"
        assert state["draft"]["trips"][1]["departDate"] == "2026-10-21"
        assert not state["canSubmit"]


@pytest.mark.parametrize("field_name,value,error_field", [
    ("arriveDate", "2026-10-17", "arrive_date"),
    ("departDate", "", "depart_date"),
    ("transport", "飞机-头等舱", "transport"),
    ("toCity", "不存在的城市", "to_city"),
])
def test_invalid_form_stays_unsubmitted_with_field_errors(tmp_path, field_name, value, error_field):
    database = tmp_path / "demo.db"
    _, cid = seed(database)
    with TestClient(create_app(database)) as client:
        payload = form_payload()
        payload["edits"]["trips"][0][field_name] = value
        response = client.post(f"/assistant/api/conversations/{cid}/submit", json=payload)
        assert response.status_code == 422, response.text
        assert any(x["field"] == error_field for x in response.json()["error"]["issues"])
        assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 0
        assert client.get(f"/assistant/api/conversations/{cid}").json()["state"]["revision"] == 1


def test_stale_form_and_busy_conversation_are_rejected(tmp_path):
    database = tmp_path / "demo.db"
    store, cid = seed(database)
    with TestClient(create_app(database)) as client:
        payload = form_payload()
        payload["revision"] = 9
        assert client.post(f"/assistant/api/conversations/{cid}/submit", json=payload).status_code == 409
        store.start_turn(cid, "修改行程", "running")
        assert client.post(f"/assistant/api/conversations/{cid}/submit", json=form_payload()).status_code == 409


def test_new_chat_syncs_latest_form_state_before_using_dify(tmp_path):
    database = tmp_path / "demo.db"
    _, cid = seed(database)
    remote = fixture_state()
    calls = []

    def upstream(request):
        nonlocal remote
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "session-var", "name": "cv_session", "value": json.dumps(remote)}]})
        if request.method == "PUT":
            body = json.loads(request.content)
            remote = json.loads(body["value"])
            assert remote["draft"]["reason"] == "抽屉填写的项目验收"
            return httpx.Response(200, json={"id": "session-var", "name": "cv_session", "value": body["value"]})
        assert remote["flow_state"] == "SUBMITTED"
        events = [{"event": "message", "conversation_id": "dify-" + cid, "answer": "这张申请已经提交。"},
                  {"event": "message_end", "conversation_id": "dify-" + cid, "message_id": "reply"}]
        return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events))

    service = DifyService(DifyConfig("https://api.dify.ai/v1", "app-test", "测试"), transport=httpx.MockTransport(upstream))
    with TestClient(create_app(database, dify_service=service)) as client:
        response = client.post(f"/assistant/api/conversations/{cid}/submit", json=form_payload())
        assert response.status_code == 202, response.text
        wait_turn(client, response.json()["turnId"])
        turn = client.post(f"/assistant/api/conversations/{cid}/messages", json={"text": "查看确认单", "clientRequestId": "after-form"})
        assert wait_turn(client, turn.json()["turnId"])["status"] == "succeeded"
        methods = [x[0] for x in calls]
        assert methods.index("PUT") < methods.index("POST")
        assert client.get(f"/assistant/api/conversations/{cid}").json()["state"]["draft"]["reason"] == "抽屉填写的项目验收"


def test_same_revision_new_clarification_cannot_be_overwritten_by_form(tmp_path):
    database = tmp_path / "demo.db"
    store, cid = seed(database)
    before = fixture_state()
    turn, _ = store.start_turn(cid, "还有一个不确定事项", "clarify")
    newer = copy.deepcopy(before)
    newer["pending"] = [{"field": "interpretation", "question": "请确认会议日期"}]
    store.finish(turn, "请确认会议日期", "succeeded", state=newer)
    from mock_travel.store import ServiceError
    with pytest.raises(ServiceError, match="草稿"):
        store.start_form(cid, form_payload(), {}, before, expected_state=before)
    assert store.conversation(cid)["state"]["pending"][0]["question"] == "请确认会议日期"


def test_failed_state_push_never_pulls_old_draft_over_saved_form(tmp_path):
    database = tmp_path / "demo.db"
    _, cid = seed(database)
    def unavailable(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "var", "name": "cv_session", "value": json.dumps(fixture_state())}]})
        return httpx.Response(503, json={"message": "暂不可用"})
    service = DifyService(DifyConfig("https://api.dify.ai/v1", "app-test", "测试"), transport=httpx.MockTransport(unavailable))
    with TestClient(create_app(database, dify_service=service)) as client:
        response = client.post(f"/assistant/api/conversations/{cid}/submit", json=form_payload())
        wait_turn(client, response.json()["turnId"])
        response = client.post(f"/assistant/api/conversations/{cid}/messages", json={"text": "查看申请", "clientRequestId": "push-failed"})
        assert wait_turn(client, response.json()["turnId"])["status"] != "succeeded"
        for _ in range(2):
            detail = client.get(f"/assistant/api/conversations/{cid}").json()
            assert detail["state"]["draft"]["reason"] == "抽屉填写的项目验收"
            assert detail["state"]["phase"] == "SUBMITTED"


def test_interrupted_form_retains_same_request_for_receipt_recovery(tmp_path):
    import asyncio
    from mock_travel.draft_forms import FormSubmission, prepare_form, submission_result
    database = tmp_path / "demo.db"
    store, cid = seed(database)
    app = create_app(database)
    gate = asyncio.run(prepare_form(app, fixture_state(), FormSubmission(**form_payload())))
    pending = submission_result(gate)["state"]
    store.start_form(cid, form_payload(), gate, pending, expected_state=fixture_state())
    # 模拟创建已成功，但进程未能写回助手状态。
    app.state.store.create(gate["payload"], gate["request_id"], gate["identity"]["draft_id"], gate["identity"]["revision"])
    with TestClient(create_app(database)) as client:
        state = client.get(f"/assistant/api/conversations/{cid}").json()["state"]
        assert state["lastSubmission"]["status"] == "UNKNOWN"
        assert state["lastSubmission"]["requestId"] == gate["request_id"]
        assert state["draft"]["reason"] == "抽屉填写的项目验收"
        assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 1


def test_form_can_explicitly_correct_a_mapped_city(tmp_path):
    state = fixture_state()
    state.update(flow_state="COLLECTING", confirmation={})
    for t, a, b, ac, bc in [
        (state["draft"]["trips"][0], "昆山", "杭州", "DEMO_SUZHOU", "330100"),
        (state["draft"]["trips"][1], "杭州", "苏州", "330100", "DEMO_SUZHOU")]:
        t.update(from_city=field(a), to_city=field(b),
                 resolved_from={"place": a, "name": "苏州" if a == "昆山" else a, "code": ac, "mapped": a == "昆山"},
                 resolved_to={"place": b, "name": b, "code": bc, "mapped": False})
    database = tmp_path / "demo.db"
    store, cid = seed(database, state)
    view = store.conversation(cid)["state"]["draft"]
    assert view["trips"][0]["fromCity"] == "苏州"
    assert view["editTrips"][0]["fromCity"] == "昆山"
    with TestClient(create_app(database)) as client:
        payload = form_payload()
        payload["edits"]["trips"] = view["editTrips"]
        before = client.post(f"/assistant/api/conversations/{cid}/submit", json=payload)
        assert before.status_code == 422
        assert any(x["code"] == "MAPPING_CONFLICT" for x in before.json()["error"]["issues"])
        payload["edits"]["trips"][0]["fromCity"] = "苏州"
        after = client.post(f"/assistant/api/conversations/{cid}/submit", json=payload)
        assert after.status_code == 202, after.text
        wait_turn(client, after.json()["turnId"])
        raw = json.loads(store.private_conversation(cid)["state_json"])
        assert raw["draft"]["trips"][0]["from_city"]["value"] == "苏州"
        assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 1


def test_old_failure_does_not_replace_new_clarification():
    from mock_travel.assistant_presentation import present_answer
    state = fixture_state()
    state["last_submission"] = {"draft_id": "D-form", "revision": 1, "status": "FAILED", "message": "付款公司不可用"}
    updated = copy.deepcopy(state)
    updated["pending"] = [{"question": "你想修改去程还是返程？"}]
    assert present_answer("你想修改去程还是返程？", state, updated) == "你想修改去程还是返程？"


def test_form_answers_old_transport_scope_question_after_date_correction(tmp_path):
    state = fixture_state()
    state.update(flow_state="COLLECTING", confirmation={})
    state["draft"]["open_clarifications"] = [{"id": "Q-old-transport", "question": "请问高铁二等座是用于"}]
    database = tmp_path / "demo.db"
    _, cid = seed(database, state)
    with TestClient(create_app(database)) as client:
        path = f"/assistant/api/conversations/{cid}/submit"
        payload = form_payload()
        payload["edits"]["trips"][1].update(departDate="2026-10-17", arriveDate="2026-10-17")
        failed = client.post(path, json=payload)
        assert failed.status_code == 422
        assert any(x["code"] == "DATE_ORDER" for x in failed.json()["error"]["issues"])
        assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 0
        corrected = client.post(path, json=form_payload())
        assert corrected.status_code == 202, corrected.text
        wait_turn(client, corrected.json()["turnId"])
        assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 1


@pytest.mark.parametrize("question", ["同行人张三还是李四？", "请确认会议日期与住宿政策的关系", "未能理解这次修改的目标",
                                      "请明确高铁行程要删除哪一段？", "请确认要取消去程还是返程高铁行程？",
                                      "请确认去程高铁到上海还是苏州？"])
def test_form_does_not_erase_unanswered_semantics(tmp_path, question):
    state = fixture_state()
    state.update(flow_state="COLLECTING", confirmation={})
    state["draft"]["open_clarifications"] = [{"id": "Q-unresolved", "question": question}]
    database = tmp_path / "demo.db"
    _, cid = seed(database, state)
    with TestClient(create_app(database)) as client:
        result = client.post(f"/assistant/api/conversations/{cid}/submit", json=form_payload())
        assert result.status_code == 422
        assert any(x["code"] == "CLARIFICATION" for x in result.json()["error"]["issues"])
        assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 0


def test_form_cannot_erase_an_unrecorded_turn(tmp_path):
    state = fixture_state()
    state.update(flow_state="COLLECTING", confirmation={})
    rec = {"id": "Q-RECOVERY-kept", "failed_query": "还有一段高铁行程", "reference_date": "2026-09-13",
           "error_code": "TOP_LEVEL_KEYS", "error_path": "$", "base_draft_id": "D-form", "base_revision": 1,
           "question": "这轮内容尚未记录，请重新说明。", "targets": [], "scope": "TURN", "failure_count": 1,
           "recent_errors": [{"error_code": "TOP_LEVEL_KEYS", "error_path": "$"}]}
    state["dialogue"]["recovery"] = rec
    state["pending"] = [{"id": rec["id"], "code": "CLARIFICATION", "field": "interpretation", "target": "", "question": rec["question"]}]
    database = tmp_path / "demo.db"
    store, cid = seed(database, state)
    with TestClient(create_app(database)) as client:
        result = client.post(f"/assistant/api/conversations/{cid}/submit", json=form_payload())
        assert result.status_code == 422
        assert any(x["id"] == rec["id"] for x in result.json()["error"]["issues"])
        assert json.loads(store.private_conversation(cid)["state_json"])["dialogue"]["recovery"] == rec
        assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 0


@pytest.mark.parametrize("draft_id,revision", [("D-next", 1), ("D-form", 2)])
def test_previous_submission_does_not_lock_a_new_draft(tmp_path, draft_id, revision):
    state = fixture_state()
    state["last_submission"] = {"draft_id": "D-form", "revision": 1, "status": "FAILED", "message": "付款公司不可用"}
    store, cid = seed(tmp_path / "demo.db", state)
    turn, _ = store.start_turn(cid, "重新整理申请", "new-draft")
    state["draft"].update(draft_id=draft_id, revision=revision)
    state["confirmation"].update(draft_id=draft_id, revision=revision)
    store.finish(turn, "已重新整理申请。", "succeeded", state=state)
    conversation = store.conversation(cid)
    assert conversation["state"]["lastSubmission"] is None
    assert conversation["state"]["canSubmit"] is True
    assert conversation["messages"][1]["draftState"]["lastSubmission"]["status"] == "FAILED"
    assert conversation["messages"][3]["draftState"]["lastSubmission"] is None
