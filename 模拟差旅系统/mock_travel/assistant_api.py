"""本机助手 API；浏览器只访问此服务，Dify 凭证不进入客户端。"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .assistant_store import AssistantStore
from .catalog import employee_context, query_cities, transport_options
from .draft_forms import FormSubmission, perform_submission, prepare_form, submission_result
from .dify_client import DifyError, DifyService
from .dify_probe import DEFAULT_CONFIG, ProbeError, load_config
from .store import ServiceError

logger = logging.getLogger(__name__)


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draftId: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1, strict=True)
    fingerprint: str = Field(min_length=1, max_length=128)


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    clientRequestId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    confirmation: Optional[Confirmation] = None


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def same_origin(request: Request):
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
            valid = (parsed.scheme == request.url.scheme and parsed.hostname == request.url.hostname
                     and parsed.port == request.url.port and not parsed.username and not parsed.password)
        except ValueError:
            valid = False
        if not valid:
            raise ServiceError("ORIGIN_NOT_ALLOWED", "请从本地助手页面操作。", 403)
    if request.method in {"POST", "PUT", "PATCH"} and request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise ServiceError("JSON_REQUIRED", "请以 JSON 格式提交请求。", 415)


class AssistantManager:
    def __init__(self, store, service=None):
        self.store, self.service = store, service
        self.tasks = set()

    def get_service(self):
        if self.service is not None:
            return self.service
        try:
            return DifyService(load_config(DEFAULT_CONFIG))
        except ProbeError:
            raise ServiceError("DIFY_NOT_CONFIGURED", "助手尚未完成连接配置，请检查本地服务配置。", 503) from None

    def launch(self, turn_id, cid, text):
        task = asyncio.create_task(self.execute(turn_id, cid, text))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def execute(self, turn_id, cid, text):
        answer = ""
        try:
            row = self.store.private_conversation(cid)

            async def progress(value, dify_id):
                nonlocal answer
                answer = value
                self.store.progress(turn_id, answer, dify_id)

            service = self.get_service()
            if row["push_pending"]:
                await service.set_variables(row["dify_conversation_id"], row["dify_user"], json.loads(row["state_json"]))
                self.store.mark_pushed(cid, row["generation"])
            reply = await service.chat(text, row["dify_conversation_id"], row["dify_user"], progress)
            answer = reply["answer"]
            try:
                state = await service.variables(reply["conversation_id"], row["dify_user"])
            except DifyError:
                raise DifyError("STATE_SYNC_FAILED", "回复已保存，但草稿状态暂未同步。请重新打开会话并核对模拟单据后继续。", True) from None
            self.store.finish(turn_id, answer, "succeeded", state=state)
        except asyncio.CancelledError:
            self.store.finish(turn_id, answer, "uncertain", error={"code": "SERVICE_STOPPED",
                "message": "本地服务停止，本轮结果尚未确认。请重新打开会话并核对模拟单据后继续。"})
            raise
        except DifyError as error:
            self.store.finish(turn_id, answer, "uncertain" if error.uncertain else "failed",
                              error={"code": error.code, "message": error.message})
        except ServiceError as error:
            self.store.finish(turn_id, answer, "failed", error={"code": error.code, "message": error.text})
        except Exception as error:
            logger.error("助手后台任务失败，异常类别：%s", type(error).__name__)
            self.store.finish(turn_id, answer, "uncertain", error={"code": "LOCAL_PROCESSING_ERROR",
                "message": "本轮处理未能完成，已有内容仍保留。请核对会话及模拟单据后再继续。"})

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def launch_form(self, app, turn_id, gate):
        task = asyncio.create_task(self.execute_form(app, turn_id, gate))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def execute_form(self, app, turn_id, gate):
        try:
            result = await perform_submission(app, gate)
        except asyncio.CancelledError:
            result = submission_result(gate)
            self.store.finish(turn_id, result["reply_text"], "uncertain", state=result["state"], push_pending=True)
            raise
        except Exception as error:
            logger.error("表单提交处理异常，类别：%s", type(error).__name__)
            result = submission_result(gate)
        uncertain = result["state"]["last_submission"]["status"] == "UNKNOWN"
        self.store.finish(turn_id, result["reply_text"], "uncertain" if uncertain else "succeeded",
                          state=result["state"], push_pending=True)


def register_assistant(app, db_path, *, dify_service=None):
    store = AssistantStore(db_path)
    manager = AssistantManager(store, dify_service)
    app.state.assistant_manager = manager
    app.add_event_handler("startup", store.interrupt_running)
    app.add_event_handler("shutdown", manager.close)
    router = APIRouter(prefix="/assistant/api", include_in_schema=False, dependencies=[Depends(same_origin)])

    @router.get("/status")
    def status():
        ready, name = False, "差旅申请助手"
        try:
            config = manager.get_service().config
            ready = bool(config.api_key)
            name = config.expected_app_name or name
        except ServiceError:
            pass
        bridge_path = Path(DEFAULT_CONFIG).parent / "bridge.json"
        bridge_ready = False
        if bridge_path.exists():
            try:
                bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
                bridge_ready = bool(bridge.get("public_url") and bridge.get("token"))
            except (OSError, ValueError):
                pass
        return {"ready": ready, "appName": name, "employeeName": employee_context()["employee"]["employeeName"],
                "bridgeConfigured": bridge_ready}

    @router.get("/conversations")
    def conversations():
        return store.conversations()

    @router.post("/conversations")
    def create_conversation(payload: EmptyRequest):
        return store.create_conversation()

    @router.delete("/conversations/{cid}")
    def delete_conversation(cid: str):
        return store.delete_conversation(cid)

    @router.get("/conversations/{cid}")
    async def conversation(cid: str):
        row = store.private_conversation(cid)
        detail = store.conversation(cid)
        if not row["synchronized"] and not row["push_pending"] and row["dify_conversation_id"] and not detail["activeTurnId"]:
            try:
                state = await manager.get_service().variables(row["dify_conversation_id"], row["dify_user"])
                store.synchronize(cid, state, expected_generation=row["generation"])
                detail = store.conversation(cid)
            except (DifyError, ServiceError):
                pass
        return detail

    @router.post("/conversations/{cid}/messages", status_code=202)
    async def send_message(cid: str, payload: MessageRequest):
        text = payload.text.strip()
        if not text:
            raise ServiceError("EMPTY_MESSAGE", "请先输入出差安排或要修改的内容。", 422)
        turn_id, created = store.start_turn(cid, text, payload.clientRequestId,
                                           payload.confirmation.model_dump() if payload.confirmation else None)
        if created:
            manager.launch(turn_id, cid, text)
        return {"turnId": turn_id, "status": store.turn(turn_id)["status"]}

    @router.get("/turns/{turn_id}")
    def turn(turn_id: str):
        return store.turn(turn_id)

    @router.get("/form-options")
    def form_options():
        return {"transports": transport_options()}

    @router.get("/cities")
    def cities(filter: str = Query("", max_length=100)):
        matches = query_cities(filter.strip()) if filter.strip() else []
        return {"items": [{"id": item["cityId"],
                           "name": "桐庐" if item["cityName"] == "桐庐县（桐庐基地除外）" else item["cityName"]}
                          for item in matches]}

    @router.post("/conversations/{cid}/submit", status_code=202)
    async def submit_form(cid: str, payload: FormSubmission):
        request = payload.model_dump()
        replay, state = store.form_request(cid, request)
        if replay:
            return {"turnId": replay, "status": store.turn(replay)["status"]}
        gate = await prepare_form(app, state, payload)
        pending_state = submission_result(gate)["state"]
        turn_id, created = store.start_form(cid, request, gate, pending_state, expected_state=state)
        if created:
            manager.launch_form(app, turn_id, gate)
        return {"turnId": turn_id, "status": store.turn(turn_id)["status"]}

    app.include_router(router)
