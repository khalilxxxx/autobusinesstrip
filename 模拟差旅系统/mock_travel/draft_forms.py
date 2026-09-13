"""抽屉的确定性提交流程，复用同一套工作流校验和模拟 HTTP 接口。"""
import copy
import json
import re
from functools import lru_cache
from pathlib import Path
import runpy
from typing import List, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .store import ServiceError, encode
from .catalog import employee_context

NODES = Path(__file__).resolve().parents[2] / "交付物/完整Demo_Dify接入/nodes"


@lru_cache(maxsize=8)
def node(name):
    return runpy.run_path(str(NODES / (name + ".py")))["main"]


class FormTrip(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=128)
    fromCity: str = Field(max_length=100)
    toCity: str = Field(max_length=100)
    departDate: str = Field(max_length=20)
    arriveDate: str = Field(max_length=20)
    transport: str = Field(max_length=100)


class FormEdits(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    travelType: Literal["NORMAL", "SHORT_TERM"]
    reason: str = Field(max_length=1200)
    trips: List[FormTrip] = Field(max_length=20)


class FormSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clientRequestId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    draftId: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1, strict=True)
    edits: FormEdits


class FormError(ServiceError):
    def __init__(self, issues):
        super().__init__("DRAFT_INVALID", "请修正以下信息后提交。", 422)
        self.issues = issues


def internal_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8766",
                             trust_env=False, headers={"X-Demo-Source": "ASSISTANT_FORM"})


def successful_body(response):
    if response.status_code != 200 or response.json().get("code") != "SUCCESS":
        raise ServiceError("FORM_OPTIONS_UNAVAILABLE", "基础数据暂时无法获取，填写内容仍保留，请稍后重试。", 503)
    return response.text


def form_answers_transport_scope(question, trips):
    """完整表单逐段明确交通时，解除旧的交通归属问题；其他语义/恢复事项仍需回答。"""
    text = question.get('question', '')
    if question.get('id', '').startswith('Q-RECOVERY-'):
        return False
    if re.search(r'政策|标准|报销|费用|同行|活动|日期|事由|权限|未记录|删除|取消|去掉|保留|新增|增加|插入|路线|城市|目的地|起点|终点|车站|哪天', text):
        return False
    transport = re.search(r'交通|席别|高铁|火车|飞机|动车|舱|等座', text)
    # 仅明确的作用范围问句（兼容旧的“请问高铁二等座是用于”截断问题）。
    # 出现交通词的目的地、删段等问题不能靠完整交通字段解除。
    scope = re.search(r'用于|适用于|用在|用到|(?:交通|席别|舱位).*(?:范围|归属|适用)', text)
    return bool(transport and scope and trips and all(t['transport']['value'] for t in trips))


async def prepare_form(app, state, payload):
    draft = copy.deepcopy(state["draft"])
    context = employee_context()
    # 名称调整后，旧草稿在本次编辑校验中采用同一组织的新名称；后续仍生成新确认版本。
    if draft.get('department') == '演示业务部': draft['department'] = context['defaultDepartment']['name']
    if draft.get('payer_company') == '演示科技公司': draft['payer_company'] = context['defaultPayerCompany']['name']
    old = {t["id"]: t for t in draft.get("trips", [])}
    edits = payload.edits
    if len({t.id for t in edits.trips}) != len(edits.trips):
        raise FormError([{"target": "", "field": "trips", "question": "行程标识重复，请重新打开草稿。"}])
    draft.update(reason=edits.reason, travel_type=edits.travelType, trips=[])
    draft.setdefault("basic_sources", {}).update(reason="USER", travel_type="USER")
    aliases = {}
    for index, item in enumerate(edits.trips):
        trip_id = item.id
        if trip_id not in old:
            trip_id = "T" + str(draft["next_trip_id"])
            draft["next_trip_id"] += 1
            while trip_id in old or trip_id in aliases:
                trip_id = "T" + str(draft["next_trip_id"])
                draft["next_trip_id"] += 1
        aliases[trip_id] = item.id
        trip = {"id": trip_id, "kind": "OUTBOUND" if index == 0 else "RETURN" if index == len(edits.trips) - 1 else "MOVE"}
        for frontend, backend in (("fromCity", "from_city"), ("toCity", "to_city"),
                                  ("departDate", "depart_date"), ("arriveDate", "arrive_date"), ("transport", "transport")):
            value = getattr(item, frontend)
            trip[backend] = {"value": value, "source": "USER" if value else "USER_CLEAR", "evidence": value}
        draft["trips"].append(trip)
    draft['open_clarifications'] = [q for q in draft.get('open_clarifications', [])
                                    if not form_answers_transport_scope(q, draft['trips'])]
    candidate = {"draft": draft, "action": "UPDATE", "merge_error": "", "clarification": "",
                 "dialogue": copy.deepcopy(state["dialogue"])}
    async with internal_client(app) as client:
        context = node("N02")(query="编辑并提交单据", cv_session=encode(state), demo_reference_date="",
                              run_id=payload.clientRequestId, api_body=successful_body(await client.get("/workflow/v1/context")))
        queries = [json.loads(context["context_json"])["employee"]["base_city"]]
        queries += [trip[key]["value"] for trip in draft["trips"] for key in ("from_city", "to_city") if trip[key]["value"]]
        cities = await client.post("/workflow/v1/cities/resolve", json={"queries": list(dict.fromkeys(queries))})
    checked = node("N07")(candidate_json=encode(candidate), context_json=context["context_json"], api_body=successful_body(cities))
    content = json.loads(checked["checked_json"])
    if content["issues"]:
        raise FormError([{**issue, "target": aliases.get(issue.get("target"), issue.get("target", ""))} for issue in content["issues"]])
    plan = {"action": "UPDATE", "event": {"consultation": "", "submit_requested": "N", "intent": "UPDATE"}}
    prepared = json.loads(node("N09")(state_json=encode(state), plan_json=encode(plan), checked_json=checked["checked_json"],
                                      context_json=checked["context_json"])["result_json"])["state"]
    content["draft"] = prepared["draft"]
    plan = {"query": "确认提交", "action": "SUBMIT", "event": {"basic_updates": [], "trip_operations": []}}
    result = node("N10")(state_json=encode(prepared), plan_json=encode(plan), checked_json=encode(content), context_json=checked["context_json"])
    if result["route"] != "HTTP":
        raise ServiceError("FORM_NOT_READY", "草稿状态发生变化，请重新核对后提交。", 409)
    return json.loads(result["gate_json"])


def submission_result(gate, body="", status_code=0):
    return json.loads(node("S01")(gate_json=encode(gate), api_body=body, status_code=status_code)["result_json"])


async def perform_submission(app, gate):
    try:
        async with internal_client(app) as client:
            response = await client.get("/mock/v1/submissions/" + gate["request_id"])
            if response.status_code == 200:
                envelope = response.json()
                if envelope.get("code") != "SUCCESS" or envelope.get("data", {}).get("clientRequestId") != gate["request_id"]:
                    return submission_result(gate)
                return submission_result(gate, encode(envelope["data"]["result"]), 200)
            if response.status_code != 404 or response.json().get("code") != "SUBMISSION_NOT_FOUND":
                return submission_result(gate)
            response = await client.post("/mock/v1/travel/applications", json=gate["payload"], headers={
                "X-Client-Request-Id": gate["request_id"], "X-Draft-Id": gate["identity"]["draft_id"],
                "X-Draft-Version": str(gate["identity"]["revision"])})
            return submission_result(gate, response.text, response.status_code)
    except (httpx.RequestError, ValueError, KeyError):
        return submission_result(gate)
