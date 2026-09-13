"""用外部 API 边界样本验证鉴权、会话延续及密钥处理，不调用线上模型。"""
import json

import httpx
import pytest

from mock_travel.dify_probe import DifyConfig, ProbeError, check_application, check_network


def config():
    return DifyConfig("https://api.dify.ai/v1", "app-test-secret", "差旅申请助手-MVP1.2-测试")


def test_network_probe_distinguishes_reachability_from_authentication():
    def server(request):
        assert request.url.path == "/v1/parameters"
        assert "Authorization" not in request.headers
        return httpx.Response(401, json={"code": "unauthorized", "message": "Bearer required"})

    result = check_network(config().base_url, transport=httpx.MockTransport(server))
    assert result == {"network": "reachable", "http_status": 401, "authentication": "not_tested"}


def test_auth_only_does_not_send_chat_messages():
    calls = []

    def server(request):
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer app-test-secret"
        if request.url.path == "/v1/info":
            return httpx.Response(200, json={"name": config().expected_app_name})
        return httpx.Response(200, json={"user_input_form": []})

    result = check_application(config(), transport=httpx.MockTransport(server))
    assert result["authentication"] == "passed"
    assert result["conversation"] == "not_tested"
    assert calls == [("GET", "/v1/info"), ("GET", "/v1/parameters")]


def test_wrong_application_stops_before_model_calls():
    calls = []

    def server(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"name": "其他应用"})

    with pytest.raises(ProbeError, match="应用名称不匹配"):
        check_application(config(), chat=True, transport=httpx.MockTransport(server))
    assert calls == ["/v1/info"]


def test_second_turn_reuses_first_conversation_and_test_user():
    messages = []

    def server(request):
        if request.url.path == "/v1/info":
            return httpx.Response(200, json={"name": config().expected_app_name})
        if request.url.path == "/v1/parameters":
            return httpx.Response(200, json={"user_input_form": []})
        assert request.url.path == "/v1/chat-messages"
        messages.append(json.loads(request.content))
        return httpx.Response(200, json={"conversation_id": "conv-123", "message_id": str(len(messages)),
                                         "answer": "测试草稿回复"})

    result = check_application(config(), chat=True, transport=httpx.MockTransport(server))
    assert messages[0]["conversation_id"] == ""
    assert messages[1]["conversation_id"] == "conv-123"
    assert messages[0]["user"] == messages[1]["user"]
    assert messages[0]["user"].startswith("connectivity-")
    assert all(item["response_mode"] == "blocking" for item in messages)
    assert result["conversation"] == "passed"
    assert result["conversation_id"] == "conv-123"
    assert len(result["turns"]) == 2


def test_changed_conversation_is_not_reported_as_continuation():
    count = 0

    def server(request):
        nonlocal count
        if request.url.path == "/v1/info":
            return httpx.Response(200, json={"name": config().expected_app_name})
        if request.url.path == "/v1/parameters":
            return httpx.Response(200, json={"user_input_form": []})
        count += 1
        return httpx.Response(200, json={"conversation_id": "conv-" + str(count), "answer": "有回复"})

    with pytest.raises(ProbeError, match="会话标识"):
        check_application(config(), chat=True, transport=httpx.MockTransport(server))


def test_error_message_cannot_echo_the_api_key():
    def server(request):
        return httpx.Response(401, json={"code": "unauthorized", "message": "Invalid app-test-secret"})

    with pytest.raises(ProbeError) as error:
        check_application(config(), transport=httpx.MockTransport(server))
    assert "app-test-secret" not in str(error.value)
    assert "401" in str(error.value)


def test_authenticated_redirect_is_not_followed():
    calls = []

    def server(request):
        calls.append(request.url.host)
        return httpx.Response(307, headers={"Location": "https://different.example/v1/info"})

    with pytest.raises(ProbeError, match="307"):
        check_application(config(), transport=httpx.MockTransport(server))
    assert calls == ["api.dify.ai"]


def test_control_characters_in_key_are_rejected_before_transport():
    def server(request):
        pytest.fail("无效密钥不应进入网络请求")

    invalid = DifyConfig(config().base_url, "app-placeholder\x00", config().expected_app_name)
    with pytest.raises(ProbeError, match="api_key 格式"):
        check_application(invalid, transport=httpx.MockTransport(server))


def test_successful_reply_redacts_key_before_json_escaping():
    special = DifyConfig(config().base_url, 'app-placeholder"\\suffix', config().expected_app_name)

    def server(request):
        if request.url.path == "/v1/info":
            return httpx.Response(200, json={"name": special.expected_app_name})
        if request.url.path == "/v1/parameters":
            return httpx.Response(200, json={"user_input_form": []})
        return httpx.Response(200, json={"conversation_id": "conv-123", "answer": special.api_key})

    result = check_application(special, chat=True, transport=httpx.MockTransport(server))
    assert "app-placeholder" not in json.dumps(result)


def test_transport_error_does_not_output_escaped_credentials():
    special = DifyConfig(config().base_url, 'app-placeholder"\\suffix', config().expected_app_name)

    def server(request):
        raise httpx.LocalProtocolError("header contains " + repr(special.api_key))

    with pytest.raises(ProbeError) as error:
        check_application(special, transport=httpx.MockTransport(server))
    assert "app-placeholder" not in str(error.value)
    assert "LocalProtocolError" in str(error.value)
