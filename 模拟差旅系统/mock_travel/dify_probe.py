"""本地调用 Dify Service API；仅 --chat 会发起两轮模拟草稿对话。"""
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / ".local" / "dify.json"
DEFAULT_BASE_URL = "https://api.dify.ai/v1"
QUERIES = (
    "帮我整理明天从杭州到上海、后天返程的出差申请草稿，事由是接口连通性测试。",
    "把这份草稿的事由改为接口连通性复测。",
)


class ProbeError(Exception):
    """适合显示给用户的脱敏诊断。"""


@dataclass
class DifyConfig:
    base_url: str
    api_key: str = field(repr=False)
    expected_app_name: str = ""
    inputs: dict = field(default_factory=dict)


def _base_url(value):
    if not isinstance(value, str):
        raise ProbeError("base_url 必须是 Dify Service API 地址。")
    value = value.strip().rstrip("/")
    try:
        parts = urlsplit(value)
        parts.port
    except ValueError:
        raise ProbeError("base_url 格式不正确。") from None
    if (parts.scheme not in {"https", "http"} or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment):
        raise ProbeError("base_url 需为 http(s) 地址，不能包含账号、查询参数或片段。")
    if parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ProbeError("远程 Dify API 请使用 HTTPS；HTTP 仅用于本机调试。")
    return value


def _redact(value, api_key=""):
    text = str(value)
    if api_key:
        variants = {api_key, json.dumps(api_key)[1:-1], repr(api_key)[1:-1]}
        for variant in sorted(variants, key=len, reverse=True):
            text = text.replace(variant, "[密钥已隐藏]")
    return text


def _redact_result(value, api_key):
    if isinstance(value, str):
        return _redact(value, api_key)
    if isinstance(value, list):
        return [_redact_result(item, api_key) for item in value]
    if isinstance(value, dict):
        return {_redact(key, api_key): _redact_result(item, api_key) for key, item in value.items()}
    return value


def _request_json(client, method, url, *, api_key="", allowed_status=(200,), **kwargs):
    try:
        response = client.request(method, url, **kwargs)
    except httpx.RequestError as error:
        # 原始异常可能包含请求头以及经过转义的凭证，只显示异常类别。
        raise ProbeError("Dify 请求未完成（{}），请检查 API 地址、网络或服务状态。".format(
            type(error).__name__)) from None
    if response.status_code not in allowed_status:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = "{} {}".format(body.get("code", ""), body.get("message", "")).strip()
        except ValueError:
            pass
        detail = _redact(detail, api_key)[:600]
        raise ProbeError("Dify 返回 HTTP {}{}".format(
            response.status_code, "：" + detail if detail else ""))
    try:
        body = response.json()
    except ValueError:
        raise ProbeError("Dify 返回 HTTP {}，响应不是 JSON。".format(response.status_code)) from None
    if not isinstance(body, dict):
        raise ProbeError("Dify 响应必须是 JSON 对象。")
    return body, response.status_code


def check_network(base_url, *, transport=None):
    base_url = _base_url(base_url)
    with httpx.Client(transport=transport, timeout=20, follow_redirects=False) as client:
        _, status = _request_json(client, "GET", base_url + "/parameters", allowed_status=(200, 401))
    return {"network": "reachable", "http_status": status, "authentication": "not_tested"}


def check_application(config, *, chat=False, transport=None):
    base_url = _base_url(config.base_url)
    if not isinstance(config.api_key, str) or not config.api_key.strip():
        raise ProbeError("尚未配置 api_key，请在本地 dify.json 中填入目标 Chatflow 的应用密钥。")
    api_key = config.api_key.strip()
    if not api_key.isascii() or not api_key.isprintable() or any(char.isspace() for char in api_key):
        raise ProbeError("api_key 格式不正确，请使用应用 API 密钥原文。")
    if not isinstance(config.inputs, dict) or not isinstance(config.expected_app_name, str):
        raise ProbeError("inputs 必须是 JSON 对象，expected_app_name 必须是字符串。")

    with httpx.Client(transport=transport, timeout=httpx.Timeout(120, connect=20),
                      follow_redirects=False, headers={"Authorization": "Bearer " + api_key}) as client:
        info, _ = _request_json(client, "GET", base_url + "/info", api_key=api_key)
        app_name = info.get("name")
        if not isinstance(app_name, str) or not app_name.strip():
            raise ProbeError("应用信息缺少有效 name，无法核对目标应用。")
        if config.expected_app_name and app_name != config.expected_app_name:
            raise ProbeError("应用名称不匹配：预期「{}」，实际「{}」。".format(
                _redact(config.expected_app_name, api_key), _redact(app_name, api_key)))
        parameters, _ = _request_json(client, "GET", base_url + "/parameters", api_key=api_key)
        form = parameters.get("user_input_form")
        if not isinstance(form, list):
            raise ProbeError("应用参数缺少 user_input_form 数组，请检查 API 地址与应用类型。")
        input_fields = []
        for item in form:
            if not isinstance(item, dict):
                raise ProbeError("应用 user_input_form 中存在无效字段。")
            for kind, definition in item.items():
                if not isinstance(definition, dict) or not isinstance(definition.get("variable"), str):
                    raise ProbeError("应用输入字段缺少有效 variable。")
                input_fields.append({"type": kind, "variable": definition["variable"],
                                     "required": bool(definition.get("required")),
                                     "has_default": definition.get("default") not in (None, "", [])})
        result = {"network": "reachable", "authentication": "passed", "app_name": app_name,
                  "input_fields": input_fields, "conversation": "not_tested"}
        if chat:
            missing = [item["variable"] for item in input_fields
                       if item["required"] and not item["has_default"]
                       and config.inputs.get(item["variable"]) in (None, "", [])]
            if missing:
                raise ProbeError("请先在 inputs 配置必填变量：" + _redact("、".join(missing), api_key))
            user = "connectivity-" + uuid4().hex
            conversation_id = ""
            turns = []
            for number, query in enumerate(QUERIES, 1):
                reply, status = _request_json(
                    client, "POST", base_url + "/chat-messages", api_key=api_key,
                    json={"inputs": config.inputs, "query": query, "response_mode": "blocking",
                          "conversation_id": conversation_id, "user": user})
                returned_id = reply.get("conversation_id")
                if not isinstance(returned_id, str) or not returned_id.strip():
                    raise ProbeError("第 {} 轮缺少有效会话标识 conversation_id。".format(number))
                if conversation_id and returned_id != conversation_id:
                    raise ProbeError("第二轮会话标识发生变化，无法确认会话延续。")
                answer = reply.get("answer")
                if not isinstance(answer, str) or not answer.strip():
                    raise ProbeError("第 {} 轮没有返回非空 answer，尚未通过对话验证。".format(number))
                conversation_id = returned_id
                turns.append({"turn": number, "http_status": status, "query": query,
                              "answer": answer, "message_id": reply.get("message_id")})
            result.update(conversation="passed", conversation_id=conversation_id, user=user, turns=turns,
                          business_validation="not_tested")
    # 即使上游意外回显密钥，返回值和后续报告也不含该密钥。
    return _redact_result(result, api_key)


def load_config(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ProbeError("无法读取本地配置，请检查文件存在且是有效 JSON：{}".format(path)) from None
    if not isinstance(data, dict):
        raise ProbeError("本地配置必须是 JSON 对象。")
    return DifyConfig(base_url=data.get("base_url", DEFAULT_BASE_URL), api_key=data.get("api_key", ""),
                      expected_app_name=data.get("expected_app_name", ""), inputs=data.get("inputs", {}))


def _save_report(path, report):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="本地配置文件路径")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--network-only", action="store_true", help="仅检查 API 网络可达性，不发送密钥")
    mode.add_argument("--chat", action="store_true", help="鉴权后发送两轮模拟草稿对话，会调用模型")
    args = parser.parse_args(argv)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "mode": "network" if args.network_only else "chat" if args.chat else "authentication"}
    try:
        config = load_config(args.config)
        result = check_network(config.base_url) if args.network_only else check_application(config, chat=args.chat)
        report.update(status="passed", result=result)
    except ProbeError as error:
        report.update(status="failed", error=str(error))
    output = args.config.parent / "dify-check-result.json"
    try:
        _save_report(output, report)
    except OSError:
        print("本地检查报告保存失败，请检查目录写入权限。")
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("报告已保存：{}".format(output))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
