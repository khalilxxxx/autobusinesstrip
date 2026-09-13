import httpx
from fastapi.testclient import TestClient
import pytest

from mock_travel import gateway
from mock_travel.gateway import create_gateway


def test_gateway_requires_token_and_does_not_forward_credentials():
    calls = []

    def upstream(request):
        calls.append(request)
        assert "Authorization" not in request.headers
        assert request.headers["X-Demo-Source"] == "DIFY"
        return httpx.Response(200, json={"code": "SUCCESS", "data": []})

    with TestClient(create_gateway(token="gateway-test-secret", transport=httpx.MockTransport(upstream))) as client:
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            assert client.get("/mock/v1/transport-options", headers=headers).status_code == 401
        assert calls == []
        response = client.get("/mock/v1/transport-options", headers={"Authorization": "Bearer gateway-test-secret"})
        assert response.status_code == 200
        assert len(calls) == 1
        assert "gateway-test-secret" not in response.text


def test_gateway_never_exposes_management_or_chat_proxy():
    def upstream(request):
        raise AssertionError("不允许的路径不能访问本地服务")

    with TestClient(create_gateway(token="test-token", transport=httpx.MockTransport(upstream))) as client:
        for method, path in [("GET", "/docs"), ("GET", "/assistant/api/status"),
                             ("GET", "/mock/v1/scenario"), ("PUT", "/mock/v1/scenario"),
                             ("GET", "/.local/dify.json"), ("GET", "/mock/v1/travel/applications")]:
            assert client.request(method, path, headers={"Authorization": "Bearer test-token"}).status_code == 404


def test_gateway_preserves_city_form_and_creation_identifiers():
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={"code": "SUCCESS", "data": {}})

    with TestClient(create_gateway(token="test-token", transport=httpx.MockTransport(upstream))) as client:
        headers = {"Authorization": "Bearer test-token", "X-Client-Request-Id": "request-1",
                   "X-Draft-Id": "draft-1", "X-Draft-Version": "2", "X-Workflow-Run-Id": "run-1"}
        assert client.post("/mock/v1/cities/query", data={"filter": "深圳北站"}, headers=headers).status_code == 200
        assert client.post("/mock/v1/travel/applications", json={"dqydbg": None}, headers=headers).status_code == 200
        assert calls[0].headers["Content-Type"].startswith("application/x-www-form-urlencoded")
        assert b"filter=" in calls[0].content
        assert calls[1].headers["X-Draft-Version"] == "2"
        assert calls[1].headers["X-Workflow-Run-Id"] == "run-1"


def test_gateway_does_not_follow_redirects():
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://elsewhere.example"})

    with TestClient(create_gateway(token="test-token", transport=httpx.MockTransport(upstream))) as client:
        response = client.get("/mock/v1/employee-context", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 502
        assert len(calls) == 1


def test_gateway_missing_custom_config_error_does_not_point_to_old_bridge_path(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "BRIDGE_CONFIG", tmp_path / "lifecycle-bridge.json")

    with pytest.raises(RuntimeError, match="lifecycle-bridge.json") as error:
        gateway.create_gateway()

    assert ".local/bridge.json" not in str(error.value)
