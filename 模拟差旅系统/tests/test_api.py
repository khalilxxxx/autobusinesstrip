"""通过真实 HTTP 路由和临时 SQLite 验证契约及持久化行为。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from mock_travel.app import create_app


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.sqlite3"


@pytest.fixture
def client(db_path):
    with TestClient(create_app(db_path)) as c:
        yield c


@pytest.fixture
def payload():
    return {
        "applicantId": "DEMO_EMP_001",
        "departmentId": "DEMO_DEPT_001",
        "payerCompanyId": "DEMO_COMPANY_001",
        "remark": "赴桐庐拜访客户",
        "dqydbg": None,
        "trips": [
            {"dateFrom": "2026-09-12", "dateTo": "2026-09-12",
             "cityFrom": "330100", "cityTo": "330122", "tool": "火车-二等座"},
            {"dateFrom": "2026-09-13", "dateTo": "2026-09-13",
             "cityFrom": "330122", "cityTo": "330100", "tool": "火车-二等座"},
        ],
    }


def submit(client, payload, request_id="test-request-001", **extra_headers):
    return client.post("/mock/v1/travel/applications", json=payload,
                       headers={"X-Client-Request-Id": request_id, **extra_headers})


def test_employee_context_has_one_default_identity_and_business_clock(client):
    response = client.get("/mock/v1/employee-context")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["employee"]["employeeId"] == "DEMO_EMP_001"
    assert data["defaultDepartment"]["id"] == "DEMO_DEPT_001"
    assert data["defaultPayerCompany"]["id"] == "DEMO_COMPANY_001"
    assert data["businessTime"]["timezone"] == "Asia/Shanghai"
    assert data["canSubmit"] is True
    assert "role" not in data["employee"]


def test_unknown_employee_is_not_silently_substituted(client):
    response = client.get("/mock/v1/employee-context?employeeId=missing")
    assert response.status_code == 404
    assert response.json()["code"] == "EMPLOYEE_NOT_FOUND"


def test_transport_is_ordinary_catalog_even_with_an_ignored_role_parameter(client):
    response = client.get("/mock/v1/transport-options?role=M5")
    assert response.status_code == 200
    values = {x["value"] for x in response.json()["data"]}
    assert len(values) == 21
    assert {"飞机-经济舱", "飞机-自订机票", "火车-一等座", "火车-特等座",
            "轮船-一等舱", "火车-无座", "其他-客户代订"} <= values
    assert not {"飞机-商务舱", "飞机-头等舱"} & values


def test_city_mapping_keeps_tonglu_and_maps_kunshan_with_explicit_reason(client):
    response = client.post("/mock/v1/cities/query", files={"filter": (None, "桐庐")})
    assert response.status_code == 200
    tonglu = response.json()["data"][0]
    assert tonglu["cityId"] == "330122"
    assert tonglu["upCityId"] == "330100"
    assert tonglu["cityName"] == "桐庐县（桐庐基地除外）"
    kunshan = client.post("/mock/v1/cities/query", data={"filter": "昆山"}).json()["data"][0]
    assert kunshan["cityId"] == "DEMO_SUZHOU"
    assert kunshan["cityName"] == "苏州"
    assert kunshan["mockMetadata"]["matchType"] == "BUSINESS_MAPPING"
    assert "昆山" in kunshan["mockMetadata"]["explanation"]


def test_city_station_alias_returns_city_and_not_a_fabricated_station_code(client):
    response = client.post("/mock/v1/cities/query", data={"filter": "上海虹桥站"})
    assert response.status_code == 200
    assert response.json()["data"][0]["cityId"] == "DEMO_SHANGHAI"


def test_unknown_city_is_empty_success_but_wrong_request_is_an_error(client):
    empty = client.post("/mock/v1/cities/query", data={"filter": "不存在的城市"})
    assert empty.status_code == 200
    assert empty.json()["code"] == "SUCCESS"
    assert empty.json()["data"] == []
    invalid = client.post("/mock/v1/cities/query", json={"filter": "杭州"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "INVALID_REQUEST"
    assert isinstance(invalid.json()["message"], dict)


def test_city_query_contract_only_requires_filter(client):
    spec = client.get("/openapi.json").json()
    content = spec["paths"]["/mock/v1/cities/query"]["post"]["requestBody"]["content"]
    reference = content["application/x-www-form-urlencoded"]["schema"]["$ref"]
    body_schema = spec["components"]["schemas"][reference.rsplit("/", 1)[1]]
    assert set(body_schema["properties"]) == {"filter"}
    assert body_schema["required"] == ["filter"]
    response = client.post("/mock/v1/cities/query", files={"filter": (None, "杭州")})
    assert response.status_code == 200
    assert set(response.json()) == {"uuid", "code", "message", "data"}
    assert response.json()["data"][0]["cityId"] == "330100"


def test_create_success_can_be_read_as_exact_persisted_request(client, payload):
    response = submit(client, payload)
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "SUCCESS"
    assert isinstance(body["uuid"], dict) and isinstance(body["message"], dict)
    assert body["data"]["action"] == "AI_CREATE"
    assert body["data"]["demoOnly"] is True
    application_id = body["data"]["applicationId"]
    detail = client.get("/mock/v1/travel/applications/" + application_id)
    assert detail.status_code == 200
    assert detail.json()["data"]["request"] == payload
    assert detail.json()["data"]["applicationNo"] == body["data"]["applicationNo"]


def test_original_screenshot_body_can_use_default_employee_and_organization(client, payload):
    bare = {k: payload[k] for k in ("remark", "dqydbg", "trips")}
    response = submit(client, bare)
    assert response.status_code == 200
    detail = client.get("/mock/v1/travel/applications/" + response.json()["data"]["applicationId"])
    assert detail.json()["data"]["request"]["applicantId"] == "DEMO_EMP_001"


def test_failure_is_preset_does_not_create_application_and_can_be_queried(client, payload):
    setting = client.put("/mock/v1/scenario", json={"submissionResult": "FAILURE", "failureMessage": "演示失败"})
    assert setting.status_code == 200
    response = submit(client, payload)
    assert response.json()["code"] == "MOCK_SUBMIT_FAILED"
    assert response.json()["message"]["text"] == "演示失败"
    assert "applicationNo" not in response.json()["data"]
    assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 0
    receipt = client.get("/mock/v1/submissions/test-request-001")
    assert receipt.status_code == 200
    assert receipt.json()["data"]["result"] == response.json()


def test_repeated_request_replays_response_even_after_scenario_change(client, payload):
    first = submit(client, payload)
    assert first.status_code == 200
    client.put("/mock/v1/scenario", json={"submissionResult": "FAILURE"})
    again = submit(client, payload)
    assert again.json() == first.json()
    assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 1


def test_same_request_id_with_changed_content_is_rejected(client, payload):
    assert submit(client, payload).status_code == 200
    changed = deepcopy(payload)
    changed["remark"] = "更改事由"
    response = submit(client, changed)
    assert response.status_code == 409
    assert response.json()["code"] == "REQUEST_CONFLICT"
    assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 1


def test_failed_request_replay_stays_failed_but_new_attempt_can_succeed(client, payload):
    assert client.put("/mock/v1/scenario", json={"submissionResult": "FAILURE"}).status_code == 200
    first = submit(client, payload)
    client.put("/mock/v1/scenario", json={"submissionResult": "SUCCESS"})
    assert submit(client, payload).json() == first.json()
    assert submit(client, payload, "test-request-002").json()["code"] == "SUCCESS"
    assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 1


def test_overlapping_distinct_applications_succeed_without_business_checks(client, payload):
    first = submit(client, payload, "overlap-1")
    assert first.status_code == 200
    second = submit(client, payload, "overlap-2")
    assert second.json()["code"] == "SUCCESS"
    assert first.json()["data"]["applicationId"] != second.json()["data"]["applicationId"]
    assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 2


def test_confirmed_draft_version_does_not_duplicate_with_a_new_request_id(client, payload):
    headers = {"X-Draft-Id": "draft-1", "X-Draft-Version": "1"}
    first = submit(client, payload, "draft-attempt-1", **headers)
    assert first.status_code == 200
    second = submit(client, payload, "draft-attempt-2", **headers)
    assert second.json()["data"]["applicationId"] == first.json()["data"]["applicationId"]
    changed = deepcopy(payload)
    changed["remark"] = "不一致的新内容"
    conflict = submit(client, changed, "draft-attempt-3", **headers)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "DRAFT_CONFLICT"


def test_draft_headers_are_paired(client, payload):
    response = submit(client, payload, **{"X-Draft-Id": "draft-only"})
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


def test_concurrent_same_request_creates_only_one_record(client, payload):
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: submit(client, payload, "parallel-request"), range(4)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["data"]["applicationId"] for r in responses}) == 1
    assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 1


def test_restart_preserves_records_receipts_and_scenario(db_path, payload):
    with TestClient(create_app(db_path)) as first:
        response = submit(first, payload)
        assert response.status_code == 200
        first.put("/mock/v1/scenario", json={"submissionResult": "FAILURE", "failureMessage": "下次失败"})
    with TestClient(create_app(db_path)) as second:
        assert second.get("/mock/v1/travel/applications").json()["data"]["total"] == 1
        assert second.get("/mock/v1/submissions/test-request-001").json()["data"]["result"] == response.json()
        assert second.get("/mock/v1/scenario").json()["data"]["submissionResult"] == "FAILURE"


def test_missing_receipt_is_not_reported_as_a_failed_submission(client):
    response = client.get("/mock/v1/submissions/not-a-request")
    assert response.status_code == 404
    assert response.json()["code"] == "SUBMISSION_NOT_FOUND"


def test_list_pagination_and_filter_do_not_change_total(client, payload):
    assert submit(client, payload, "list-1").status_code == 200
    submit(client, payload, "list-2")
    response = client.get("/mock/v1/travel/applications?limit=1&offset=1&applicantId=DEMO_EMP_001")
    assert response.json()["data"]["total"] == 2
    assert len(response.json()["data"]["items"]) == 1
    assert client.get("/mock/v1/travel/applications?applicantId=other").json()["data"]["total"] == 0


def test_invalid_body_returns_structured_error_without_creating(client):
    response = client.post("/mock/v1/travel/applications", json={"root": {}})
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"
    assert isinstance(response.json()["uuid"], dict)
    assert client.get("/mock/v1/travel/applications").json()["data"]["total"] == 0


def test_debug_page_uses_local_assets_and_exposes_current_contract(client):
    page = client.get("/docs")
    assert page.status_code == 200
    assert 'src="/assets/swagger/swagger-ui-bundle.js"' in page.text
    assert client.get("/assets/swagger/swagger-ui-bundle.js").status_code == 200
    assert client.get("/assets/swagger/swagger-ui.css").status_code == 200
    spec = client.get("/openapi.json").json()
    assert "/mock/v1/scenario" in spec["paths"]
    transport = spec["paths"]["/mock/v1/transport-options"]["get"]
    assert "parameters" not in transport


def test_openapi_default_create_example_is_ready_to_submit(client):
    spec = client.get("/openapi.json").json()
    example = spec["paths"]["/mock/v1/travel/applications"]["post"]["requestBody"]["content"]["application/json"]["examples"]["ordinary"]["value"]
    assert "dqydbg" in example and example["dqydbg"] is None
    response = client.post("/mock/v1/travel/applications", json=example)
    assert response.status_code == 200
    assert response.json()["code"] == "SUCCESS"
