# BEGIN CURRENT BATCH INPUT RULES
"""确定性的恢复范围和未确认节假日规则，内联到 Dify 节点。"""
import re


def explicit_route_restatement(query):
    if any(mark in query for mark in ('“', '”', '「', '」', '『', '』', '"', "'", '`')):
        return False
    if re.search(r'如果|假如|假设|要是|是否|请问|能否|可以吗|[？?]', query):
        return False
    scope = re.search(r'(?:这张|这次|本张|本次|当前|这份).{0,8}只(?:保留|从|去)', query)
    dates = re.findall(r'\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}[日号]', query)
    return bool(scope and len(dates) >= 2 and re.search(r'去|到', query) and re.search(r'回|返', query))


def recovery_fact_context(recovery, query, draft):
    if not recovery:
        return {}
    view = {k: recovery.get(k, '') for k in ('id', 'targets', 'scope', 'question')}
    if (explicit_route_restatement(query) and recovery.get('failure_count') == 1
            and recovery.get('base_draft_id') == draft.get('draft_id', '')
            and recovery.get('base_revision') == draft.get('revision', 0)):
        view.update(failed_query=recovery['failed_query'], reference_date=recovery['reference_date'])
    return view


def holiday_needs_date(query):
    holiday = re.search(r'(?:国庆|春节|中秋|端午|劳动节|五一|清明|元旦)(?:假期|节)?(?:结束|过)?后|节后', query)
    explicit = re.search(r'\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}[日号]|\d{1,2}/\d{1,2}', query)
    return bool(holiday and not explicit)


def return_day_offset(query):
    # 捕获完整数字，避免“十二”或“102”从尾部匹配成“二”或“02”。
    match = re.search(r'([零〇一二两三四五六七八九十百千万\d]+)天后(?:再)?(?:回|返)', query)
    if not match:
        return None
    word = match[1]
    digits = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    if word.isdigit():
        days = int(word)
    elif word in digits:
        days = digits[word]
    elif re.fullmatch(r'[一二三四五六七八九]?十[一二三四五六七八九]?', word):
        tens, units = word.split('十')
        days = digits.get(tens, 1) * 10 + digits.get(units, 0)
    else:
        return None
    return days if 1 <= days <= 30 else None
# END CURRENT BATCH INPUT RULES
import json
import hashlib
from datetime import datetime, timedelta, timezone


# BEGIN GENERATED STATE CONTRACT
def empty_dialogue():
    return {"focus": {"draft_id": "", "revision": 0, "questions": []}, "recovery": {}}


def validate_dialogue(dialogue):
    if not isinstance(dialogue, dict) or set(dialogue) != {"focus", "recovery"}:
        raise ValueError("对话状态结构错误，不能自动清空。")
    focus, recovery = dialogue["focus"], dialogue["recovery"]
    if not isinstance(focus, dict) or set(focus) != {"draft_id", "revision", "questions"}:
        raise ValueError("当前追问目标结构错误。")
    if not isinstance(focus["draft_id"], str) or type(focus["revision"]) is not int or focus["revision"] < 0:
        raise ValueError("追问关联的草稿版本错误。")
    if not isinstance(focus["questions"], list) or len(focus["questions"]) > 2:
        raise ValueError("当前问题应为最多两项的列表。")
    for question in focus["questions"]:
        if not isinstance(question, dict) or set(question) != {"id", "target", "field", "question"} or not all(isinstance(v, str) for v in question.values()):
            raise ValueError("当前问题的目标字段错误。")
    if not isinstance(recovery, dict):
        raise ValueError("恢复事项结构错误。")
    if not recovery:
        return
    text_keys = ("id", "failed_query", "reference_date", "error_code", "error_path", "base_draft_id", "question", "scope")
    if not all(isinstance(recovery.get(k), str) for k in text_keys):
        raise ValueError("恢复事项文本字段错误。")
    if not recovery["id"].startswith("Q-RECOVERY-") or recovery["scope"] not in {"TURN", "TARGET"}:
        raise ValueError("恢复事项标识错误。")
    if not recovery["question"].strip() or len(recovery["failed_query"]) > 4000:
        raise ValueError("恢复事项内容为空或过长。")
    if type(recovery.get("base_revision")) is not int or recovery["base_revision"] < 0:
        raise ValueError("恢复事项草稿版本错误。")
    if type(recovery.get("failure_count")) is not int or recovery["failure_count"] < 1:
        raise ValueError("恢复次数错误。")
    if not isinstance(recovery.get("targets"), list) or len(recovery["targets"]) > 20:
        raise ValueError("恢复目标列表错误。")
    for target in recovery["targets"]:
        if not isinstance(target, dict) or set(target) != {"trip_id", "field"} or not all(isinstance(v, str) and v for v in target.values()):
            raise ValueError("恢复目标结构错误。")
    if recovery["scope"] == "TARGET" and not recovery["targets"]:
        raise ValueError("按目标恢复缺少目标。")
    if not isinstance(recovery.get("recent_errors"), list) or not 1 <= len(recovery["recent_errors"]) <= 3:
        raise ValueError("恢复诊断数量错误。")
    for error in recovery["recent_errors"]:
        if not isinstance(error, dict) or not all(isinstance(error.get(k), str) for k in ("error_code", "error_path")):
            raise ValueError("恢复诊断结构错误。")
# END GENERATED STATE CONTRACT


def main(query: str, cv_session: str, api_body: str,
         demo_reference_date: str, run_id: str) -> dict:
    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    case = "NORMAL"
    payload = json.loads(api_body)
    if payload.get("code") != "SUCCESS" or not isinstance(payload.get("data"), dict):
        raise ValueError("员工与交通接口调用失败；已有会话未改变。")
    api = payload["data"]
    employee_api = api["employeeContext"]
    emp = employee_api["employee"]
    department = employee_api["defaultDepartment"]
    company = employee_api["defaultPayerCompany"]
    query = str(query or "").strip()
    if not query or len(query) > 4000:
        raise ValueError("输入须为 1～4000 个字符。")
    now = datetime.now(timezone(timedelta(hours=8)))
    ref = str(demo_reference_date or "").strip()
    if ref:
        reference = datetime.strptime(ref, "%Y-%m-%d").date()
        if reference.isoformat() != ref:
            raise ValueError("测试日期必须严格使用 YYYY-MM-DD。")
        clock_source = "TEST_OVERRIDE"
    else:
        reference = datetime.strptime(employee_api["businessTime"]["date"], "%Y-%m-%d").date()
        clock_source = "SYSTEM_CLOCK"

    raw = json.loads(cv_session or "{}")
    if not isinstance(raw, dict):
        raise ValueError("会话状态应为 JSON 对象。")
    if not raw:
        state = {"schema_version": "mvp1.2", "demo_case": case, "demo_anchor_date": reference.isoformat(),
                 "flow_state": "IDLE", "draft": {}, "pending": [],
                 "last_question": "", "confirmation": {},
                 "last_submission": {}, "history": [], "dialogue": empty_dialogue()}
    else:
        expected = {"schema_version", "demo_case", "demo_anchor_date", "flow_state", "draft", "pending",
                    "last_question", "confirmation", "last_submission", "history"}
        legacy = raw.get("schema_version") == "mvp1.0"
        if (legacy and set(raw) != expected) or (not legacy and (set(raw) != expected | {"dialogue"} or raw.get("schema_version") != "mvp1.2")):
            raise ValueError("会话状态结构或版本不一致；不能自动清空。")
        if raw["demo_case"] != case:
            raise ValueError("同一会话不能切换演示身份；请新建会话选择场景。")
        if raw["flow_state"] not in {"IDLE", "COLLECTING", "READY_TO_CONFIRM", "SUBMITTED"}:
            raise ValueError("会话状态非法。")
        for key in ("draft", "confirmation", "last_submission"):
            if not isinstance(raw[key], dict):
                raise ValueError("会话对象损坏：" + key)
        for key in ("pending", "history"):
            if not isinstance(raw[key], list):
                raise ValueError("会话列表损坏：" + key)
        if not isinstance(raw["last_question"], str):
            raise ValueError("上一轮问题类型不正确。")
        state = raw
        if legacy:
            state["schema_version"] = "mvp1.2"
            state["dialogue"] = empty_dialogue()
            if state["flow_state"] in {"COLLECTING", "READY_TO_CONFIRM"}:
                state["flow_state"] = "COLLECTING"
                state["confirmation"] = {}
                state["last_question"] = "已升级会话，请查看并核对当前确认单后继续。"

    validate_dialogue(state["dialogue"])
    if state["dialogue"]["recovery"] and state["flow_state"] == "READY_TO_CONFIRM":
        raise ValueError("恢复事项尚未处理，不能处于待确认状态。")

    cities = []  # 名称范围不是校验结果，城市须经后续HTTP逐条查询。
    transports = []
    for option in api["transportOptions"]:
        category, seat, value = option["category"], option["option"], option["value"]
        aliases = [value, category + seat, seat]
        if category == "火车":
            aliases += [prefix + sep + seat for prefix in ("火车票", "高铁", "动车") for sep in ("", "-")]
        if category == "飞机":
            aliases += ["机票-" + seat, "机票" + seat]
            if seat == "经济舱": aliases += ["飞机经济仓"]
        transports.append({"name": value, "code": value, "aliases": list(dict.fromkeys(aliases))})
    if not transports or len({x["code"] for x in transports}) != len(transports):
        raise ValueError("交通接口没有返回有效的唯一选项。")
    employee = {"id": emp["employeeId"], "name": emp["employeeName"], "role": "DEMO_ORDINARY",
                "base_city": emp["baseCity"]["cityName"], "department": department["name"], "payer_company": company["name"],
                "department_id": department["id"], "payer_company_id": company["id"]}
    seed = str(run_id or "").strip()
    if not seed:
        seed = now.isoformat() + query
    context = {"demo_case": case, "reference_date": reference.isoformat(),
               "weekday": "星期" + "一二三四五六日"[reference.weekday()],
               "timezone": "Asia/Shanghai", "clock_source": clock_source,
               "draft_seed": "DEMO-DRAFT-" + hashlib.sha256(seed.encode()).hexdigest()[:16],
               "employee": employee, "can_submit": True,
               "activity_mode": "NONE",
               "check_available": True, "cities": cities, "city_names": api["cityNames"],
               "transports": transports, "departments": [employee["department"]],
               "payer_companies": [employee["payer_company"]], "external_history": []}
    model_context = {key: context[key] for key in (
        "reference_date", "weekday", "timezone", "clock_source", "employee", "activity_mode")}
    model_context.update({"city_names": api["cityNames"],
                          "transport_options": [t["name"] for t in transports],
                          "departments": context["departments"], "payer_companies": context["payer_companies"]})
    semantic_questions = [{key: x.get(key, "") for key in ("id", "code", "target", "field", "question")}
                          for x in state["pending"] if x.get("code") == "CLARIFICATION"]
    form_issues = [{key: x.get(key, "") for key in ("code", "target", "field", "question")}
                   for x in state["pending"] if x.get("code") != "CLARIFICATION"]
    draft_view = {}
    if state["draft"]:
        draft_view = {k: state["draft"].get(k) for k in ("draft_id", "revision", "reason", "travel_type", "department", "payer_company", "scope_requests")}
        draft_view["all_transport"] = {k: state["draft"].get("all_transport", {}).get(k, "") for k in ("value", "source")}
        draft_view["trips"] = [{"id": t["id"], "kind": t["kind"], "date_relation": t.get("date_relation", {}), **{
            f: {k: t[f].get(k, "") for k in ("value", "source")}
            for f in ("from_city", "to_city", "depart_date", "arrive_date", "transport")}} for t in state["draft"]["trips"]]
    rec = state["dialogue"]["recovery"]
    focus = state["dialogue"]["focus"]
    focus_view = {"draft_id": focus["draft_id"], "revision": focus["revision"],
                  "questions": [{k: x[k] for k in ("id", "target", "field", "question")} for x in focus["questions"]]}
    llm_input = {"context": model_context, "flow_state": state["flow_state"],
                 "current_draft": draft_view, "pending_questions": semantic_questions,
                 "form_issues": form_issues,
                 "last_question": state["last_question"], "user_message": query,
                 "dialogue_focus": focus_view,
                 "recovery_context": recovery_fact_context(rec, query, state["draft"])}
    return {"context_json": encode(context), "state_json": encode(state), "query": query,
            "model_context_json": encode(model_context), "draft_json": encode(state["draft"]),
            "pending_json": encode(state["pending"]), "last_question": state["last_question"],
            "llm_input_json": encode(llm_input)}
