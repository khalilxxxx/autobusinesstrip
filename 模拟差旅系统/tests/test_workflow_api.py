from fastapi.testclient import TestClient

from mock_travel.app import create_app


def test_workflow_context_uses_mock_employee_and_twenty_one_transports(tmp_path):
    with TestClient(create_app(tmp_path / "demo.sqlite3")) as client:
        response = client.get("/workflow/v1/context", headers={"X-Demo-Source": "DIFY", "X-Workflow-Run-Id": "run-context"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["employeeContext"]["employee"]["employeeId"] == "DEMO_EMP_001"
        assert len(data["transportOptions"]) == 21
        assert "深圳" in data["cityNames"]
        records = client.get("/mock/v1/integration/events").json()["data"]["items"]
        paths = {item["path"] for item in records}
        assert "/mock/v1/employee-context" in paths
        assert "/mock/v1/transport-options" in paths


def test_batch_city_resolution_preserves_form_contract_and_mapping(tmp_path):
    with TestClient(create_app(tmp_path / "demo.sqlite3")) as client:
        response = client.post("/workflow/v1/cities/resolve", json={"queries": ["深圳北站", "昆山", "不存在城市", "深圳北站"]},
                               headers={"X-Demo-Source": "DIFY", "X-Workflow-Run-Id": "run-city"})
        assert response.status_code == 200
        items = {item["query"]: item["matches"] for item in response.json()["data"]["items"]}
        assert items["深圳北站"][0]["cityName"] == "深圳"
        assert items["昆山"][0]["cityName"] == "苏州"
        assert items["不存在城市"] == []
        assert len(items) == 3
        events = client.get("/mock/v1/integration/events").json()["data"]["items"]
        calls = [item for item in events if item["path"] == "/mock/v1/cities/query"]
        assert len(calls) == 3
        assert all(item["requestId"] == "run-city" for item in calls)


def test_receipt_adapter_keeps_missing_distinct_from_explicit_failure(tmp_path):
    with TestClient(create_app(tmp_path / "demo.sqlite3")) as client:
        missing = client.get("/workflow/v1/submissions/missing-1")
        assert missing.status_code == 200
        assert missing.json()["data"]["httpStatus"] == 404
        assert missing.json()["data"]["result"]["code"] == "SUBMISSION_NOT_FOUND"
        assert client.get("/mock/v1/submissions/missing-1").status_code == 404
        client.put("/mock/v1/scenario", json={"submissionResult": "FAILURE", "failureMessage": "测试预设失败"})
        request = {"remark": "测试", "dqydbg": None, "trips": [
            {"dateFrom": "2026-10-18", "dateTo": "2026-10-18", "cityFrom": "330100", "cityTo": "330122", "tool": "火车_高铁二等座"}]}
        original = client.post("/mock/v1/travel/applications", json=request,
                               headers={"X-Client-Request-Id": "failure-1"}).json()
        receipt = client.get("/workflow/v1/submissions/failure-1").json()["data"]
        assert receipt["httpStatus"] == 200
        assert receipt["result"]["data"]["status"] == "FAILED"
        assert receipt["result"]["data"]["result"] == original
