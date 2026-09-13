"""仅在服务端使用的 Dify 聊天客户端。"""
import json

import httpx

from .dify_probe import DifyConfig, ProbeError, _base_url, _redact, _redact_result


class DifyError(Exception):
    def __init__(self, code, message, uncertain=False):
        super().__init__(message)
        self.code, self.message, self.uncertain = code, message, uncertain


class DifyService:
    def __init__(self, config: DifyConfig, *, transport=None):
        self.config, self.transport = config, transport

    def _client(self):
        key = self.config.api_key.strip() if isinstance(self.config.api_key, str) else ""
        if not key or not key.isascii() or not key.isprintable() or any(c.isspace() for c in key):
            raise DifyError("DIFY_NOT_CONFIGURED", "助手尚未完成连接配置，请检查本地服务配置。")
        try:
            base_url = _base_url(self.config.base_url)
        except ProbeError as error:
            raise DifyError("DIFY_CONFIG_ERROR", str(error)) from None
        return httpx.AsyncClient(base_url=base_url + "/", headers={"Authorization": "Bearer " + key},
                                 timeout=httpx.Timeout(180, connect=20), transport=self.transport,
                                 follow_redirects=False)

    def _safe(self, value):
        return _redact_result(value, self.config.api_key.strip())

    def _safe_progress(self, value, finished=False):
        result = self._safe(value)
        if not finished:
            key = self.config.api_key.strip()
            variants = {key, json.dumps(key)[1:-1], repr(key)[1:-1]}
            hold = max((size for variant in variants for size in range(1, len(variant))
                        if result.endswith(variant[:size])), default=0)
            if hold:
                result = result[:-hold]
        return result

    async def _check_status(self, response):
        if response.status_code == 200:
            return
        await response.aread()
        message = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                message = _redact(body.get("message", ""), self.config.api_key.strip())[:500]
        except ValueError:
            pass
        if response.status_code in {401, 403}:
            message = "助手连接认证失败，请检查应用密钥和服务状态。"
        elif response.status_code == 429:
            message = "助手请求较多或额度不足，请稍后再试。"
        elif 300 <= response.status_code < 400:
            message = "服务地址发生跳转，请检查本地配置中的 API 地址。"
        raise DifyError("DIFY_HTTP_" + str(response.status_code), message or "助手服务暂时不可用，请稍后再试。")

    async def chat(self, text, conversation_id, user, on_progress):
        answer, current_id, message_id = "", conversation_id, ""
        ended = False
        try:
            async with self._client() as client:
                async with client.stream("POST", "chat-messages", json={
                    "query": text, "inputs": self.config.inputs, "user": user,
                    "conversation_id": conversation_id, "response_mode": "streaming",
                }) as response:
                    await self._check_status(response)
                    data_lines = []

                    async def consume(lines):
                        nonlocal answer, current_id, message_id, ended
                        if not lines:
                            return
                        try:
                            event = json.loads("\n".join(lines))
                        except ValueError:
                            raise DifyError("DIFY_INVALID_STREAM", "回复数据格式异常，已保留本地消息，请核对会话状态。", True) from None
                        if not isinstance(event, dict):
                            raise DifyError("DIFY_INVALID_STREAM", "回复数据格式异常，请稍后查看会话。", True)
                        if event.get("conversation_id"):
                            if current_id and current_id != event["conversation_id"]:
                                raise DifyError("DIFY_CONVERSATION_CHANGED", "助手会话标识发生变化，已停止本轮处理。", True)
                            current_id = event["conversation_id"]
                        kind = event.get("event")
                        if kind == "error":
                            message = self._safe(str(event.get("message") or "助手处理失败，请稍后再试。"))
                            raise DifyError("DIFY_WORKFLOW_ERROR", message[:500], True)
                        if kind in {"message", "agent_message", "message_replace"}:
                            part = event.get("answer", "")
                            if not isinstance(part, str):
                                raise DifyError("DIFY_INVALID_STREAM", "助手回复格式异常，请核对会话。", True)
                            answer = part if kind == "message_replace" else answer + part
                            if len(answer) > 100000:
                                raise DifyError("DIFY_REPLY_TOO_LARGE", "本轮回复过长，已停止接收并保留会话。", True)
                        if kind == "message_end":
                            ended = True
                            message_id = event.get("message_id", "")
                        await on_progress(self._safe_progress(answer, ended), current_id)

                    async for line in response.aiter_lines():
                        if not line:
                            await consume(data_lines)
                            data_lines = []
                        elif line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                    await consume(data_lines)
        except httpx.RequestError as error:
            raise DifyError("DIFY_NETWORK_ERROR", "助手连接中断（{}）。请先查看已保存内容，确认结果后再继续。".format(
                type(error).__name__), True) from None
        if not ended or not answer.strip() or not current_id:
            raise DifyError("DIFY_INCOMPLETE_REPLY", "尚未收到完整回复，请先核对会话和提交记录。", True)
        return self._safe({"answer": answer, "conversation_id": current_id, "message_id": message_id})

    async def variables(self, conversation_id, user):
        try:
            async with self._client() as client:
                response = await client.get("conversations/" + conversation_id + "/variables", params={"user": user})
                await self._check_status(response)
                data = response.json()
        except httpx.RequestError:
            raise DifyError("STATE_SYNC_FAILED", "草稿状态暂未同步，请稍后重新打开会话核对。", True) from None
        except ValueError:
            raise DifyError("STATE_SYNC_FAILED", "草稿状态格式异常，已保留回复，请稍后核对。", True) from None
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise DifyError("STATE_SYNC_FAILED", "未取得有效草稿状态，暂不能确认提交。", True)
        for item in data["data"]:
            if isinstance(item, dict) and item.get("name") == "cv_session":
                try:
                    state = json.loads(item["value"]) if isinstance(item.get("value"), str) else item.get("value")
                except ValueError:
                    raise DifyError("STATE_SYNC_FAILED", "草稿状态无法读取，暂不能确认提交。", True) from None
                if isinstance(state, dict):
                    return self._safe(state)
        raise DifyError("STATE_SYNC_FAILED", "尚未找到差旅草稿状态，暂不能确认提交。", True)

    async def set_variables(self, conversation_id, user, state):
        """在后续对话前写回表单的最终状态；失败时保留本地权威副本。"""
        if not conversation_id:
            raise DifyError("STATE_PUSH_FAILED", "原会话暂时无法同步，当前填写信息仍保留。", True)
        try:
            async with self._client() as client:
                path = "conversations/" + conversation_id + "/variables"
                response = await client.get(path, params={"user": user})
                await self._check_status(response)
                items = response.json().get("data", [])
                variable = next((item for item in items if item.get("name") == "cv_session" and item.get("id")), None)
                if not variable:
                    raise ValueError("missing session variable")
                response = await client.put(path + "/" + variable["id"], json={
                    "user": user, "value": json.dumps(state, ensure_ascii=False, separators=(",", ":"))})
                await self._check_status(response)
                value = response.json().get("value")
                actual = json.loads(value) if isinstance(value, str) else value
                if actual != state:
                    raise ValueError("session write not confirmed")
        except (httpx.RequestError, ValueError, KeyError, TypeError, AttributeError):
            raise DifyError("STATE_PUSH_FAILED", "最新填写信息已在本地保留，但会话同步暂未完成，请稍后重试。", True) from None
