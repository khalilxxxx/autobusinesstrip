# 自动生成：修改完整Demo_Dify接入/common 后运行 build_nodes.py。
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


"""共用解析契约；由 build_nodes.py 内联生成 Dify 独立节点。"""
import copy
import json
import re


def validate_event(parsed, query, state, context):
    normalizations = []
    source = "MODEL"

    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def diagnostics(code="", path=""):
        return {"error_code": code, "error_path": path,
                "diagnostics_json": encode({"source": source, "normalizations": normalizations,
                                            "error_code": code, "error_path": path})}

    def fail(message, code="CONTRACT_INVALID", path="$"):
        return {"status": "INVALID", "action": "ERROR", "plan_json": "{}",
                "message": "本轮内容未能可靠解析，已有草稿未改动。" + message,
                **diagnostics(code, path)}

    def clean(value):
        return re.sub(r"\s+", "", value)

    def exact_keys(value, keys):
        return isinstance(value, dict) and set(value) == set(keys)

    def evidence_ok(value):
        return isinstance(value, str) and bool(clean(value)) and clean(value) in clean(query)

    command = query.strip().rstrip("。.!！").strip()
    if command in {"确认提交", "取消整张申请", "清空当前草稿", "放弃这张申请"}:
        source = "EXACT_COMMAND"
        action = "SUBMIT" if command == "确认提交" else "CANCEL"
        data = {"intent": action, "submit_requested": "Y" if action == "SUBMIT" else "N",
                "basic_updates": [], "trip_operations": [], "clarification": "",
                "consultation": "", "clarification_resolutions": []}
        plan = {"action": action, "event": data, "query": query, "message": ""}
        return {"status": "OK", "action": action, "plan_json": encode(plan), "message": "", **diagnostics()}
    if isinstance(parsed, str):
        text = parsed.strip()
        thinking = re.match(r"^<think>[\s\S]*?</think>\s*", text)
        if thinking:
            text = text[thinking.end():].strip()
            normalizations.append("$:remove_closed_think_prefix")
        fenced = re.fullmatch(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text, flags=re.I)
        if fenced:
            text = fenced.group(1).strip()
            normalizations.append("$:remove_single_json_fence")
        try:
            data = json.loads(text)
        except ValueError:
            return fail("请检查模型输出是否为完整JSON对象。", "JSON_PARSE_ERROR")
    else:
        data = copy.deepcopy(parsed)
    if isinstance(data, dict):
        for key, default in (("submit_requested", "N"), ("clarification", ""),
                             ("consultation", ""), ("clarification_resolutions", [])):
            if key not in data or data[key] is None:
                data[key] = copy.deepcopy(default)
                normalizations.append(key + ":empty_default")
        for i, trip in enumerate(data.get("trip_operations", []) if isinstance(data.get("trip_operations"), list) else []):
            if not isinstance(trip, dict):
                continue
            if isinstance(trip.get("op"), str) and trip.get("op") in {"UPDATE", "DELETE"}:
                for key in ("after_id", "kind"):
                    if key not in trip or trip[key] is None:
                        trip[key] = ""
                        normalizations.append(f"trip_operations[{i}].{key}:empty_default")
            for j, change in enumerate(trip.get("updates", []) if isinstance(trip.get("updates"), list) else []):
                if isinstance(change, dict) and set(change) == {"field", "op", "value"}:
                    change["evidence"] = trip.get("evidence")
                    normalizations.append(f"trip_operations[{i}].updates[{j}].evidence:inherit_operation")
    keys = {"intent", "submit_requested", "basic_updates", "trip_operations", "clarification", "clarification_resolutions", "consultation"}
    if not exact_keys(data, keys):
        return fail("请检查结构化输出字段及 N04 的输入绑定。", "TOP_LEVEL_KEYS")
    if not isinstance(data["intent"], str) or data["intent"] not in {"START", "UPDATE", "NEW", "REVIEW", "SUBMIT", "CANCEL", "ASK", "UNKNOWN"}:
        return fail("操作类型不合法。")
    if not isinstance(data["submit_requested"], str) or data["submit_requested"] not in {"Y", "N"}:
        return fail("提交标记不合法。")
    if not all(isinstance(data[k], str) for k in ("clarification", "consultation")):
        return fail("澄清信息类型或长度不合法。")
    if any(len(data[k]) > 1000 for k in ("clarification", "consultation")):
        return fail("澄清内容超出范围。", "CONTENT_LIMIT", "clarification")
    basics, trips = data["basic_updates"], data["trip_operations"]
    if not isinstance(basics, list) or not isinstance(trips, list):
        return fail("本轮变化必须为列表。", "UPDATE_LIST_TYPE", "$")
    if len(basics) > 20 or len(trips) > 40:
        return fail("本轮修改数量超出演示范围。", "CONTENT_LIMIT", "$")
    allowed_basic = {"reason", "travel_type", "department", "payer_company", "all_transport", "companions", "activity", "excluded"}
    allowed_trip = {"from_city", "to_city", "depart_date", "arrive_date", "transport"}

    def update_error(item, fields, path, allow_append=False):
        if not exact_keys(item, {"field", "op", "value", "evidence"}):
            return ("字段变化结构不完整。", "UPDATE_KEYS", path)
        if not all(isinstance(v, str) for v in item.values()):
            return ("字段变化的值必须是字符串。", "UPDATE_VALUE_TYPE", path)
        if item["field"] not in fields or item["op"] not in {"SET", "CLEAR", "APPEND"}:
            return ("字段或操作不在允许范围中。", "UPDATE_ENUM", path)
        if item["op"] == "APPEND" and not (allow_append and item["field"] == "reason"):
            return ("APPEND仅允许追加事由。", "APPEND_NOT_ALLOWED", path + ".op")
        if not evidence_ok(item["evidence"]):
            return ("字段变化缺少本轮连续原话依据。", "EVIDENCE_NOT_IN_QUERY", path + ".evidence")
        if len(item["value"]) > 1000:
            return ("字段变化长度超出范围。", "VALUE_TOO_LONG", path + ".value")
        if not ((item["op"] == "CLEAR" and item["value"] == "") or (item["op"] != "CLEAR" and bool(item["value"].strip()))):
            return ("SET需要确定值，CLEAR需要空值。", "EMPTY_VALUE_CONTRACT", path + ".value")
        return None

    for i, item in enumerate(basics):
        error = update_error(item, allowed_basic, f"basic_updates[{i}]", True)
        if error:
            return fail(*error)
    for i, trip in enumerate(trips):
        path = f"trip_operations[{i}]"
        if not exact_keys(trip, {"op", "trip_id", "after_id", "kind", "evidence", "updates"}):
            return fail("行程操作结构不完整。")
        if not all(isinstance(trip[k], str) for k in ("op", "trip_id", "after_id", "kind", "evidence")):
            return fail("行程标识类型不正确。")
        if trip["op"] not in {"ADD", "UPDATE", "DELETE"}:
            return fail("行程操作不正确。", "TRIP_OPERATION_ENUM", path + ".op")
        if not evidence_ok(trip["evidence"]):
            return fail("行程操作缺少本轮连续原话依据。", "EVIDENCE_NOT_IN_QUERY", path + ".evidence")
        if not isinstance(trip["updates"], list) or len(trip["updates"]) > 5:
            return fail("每段字段变化应为最多五项的列表。")
        for j, item in enumerate(trip["updates"]):
            error = update_error(item, allowed_trip, path + f".updates[{j}]")
            if error:
                return fail(*error)
        fields = [item["field"] for item in trip["updates"]]
        if len(fields) != len(set(fields)):
            return fail("同一操作中不能重复修改同一个字段。")
        if trip["op"] == "ADD":
            if not re.fullmatch(r"NEW[1-9][0-9]*", trip["trip_id"]) or trip["kind"] not in {"MOVE", "RETURN"}:
                return fail("新增段须使用 NEW1 等临时标识及明确的段类型。", "ADD_ID_OR_KIND", path)
            if not trip["after_id"]:
                return fail("新增段需要指定插入位置。")
        elif trip["after_id"] or trip["kind"] not in {"", "MOVE", "RETURN"}:
            return fail("修改已有段的 after_id 应为空，kind 只能为空、MOVE 或 RETURN。")
        if trip["op"] == "DELETE" and trip["kind"]:
            return fail("删除已有段时 kind 应为空。")
        if trip["op"] == "DELETE" and trip["updates"]:
            return fail("删除操作不能同时设置字段。")
        if trip["op"] == "UPDATE" and not trip["updates"] and not trip["kind"]:
            return fail("修改操作没有字段变化。")

    # 没有节假日表/具体日期时拒绝模型猜测，但仍保留地点、事由等明确事实。
    date_or_route_update = any(t['op'] == 'ADD' or any(x['field'] in ('depart_date', 'arrive_date') for x in t['updates']) for t in trips)
    if holiday_needs_date(query) and data['intent'] in ('UPDATE', 'NEW', 'START') and date_or_route_update:
        for trip in trips:
            trip['updates'] = [x for x in trip['updates'] if x['field'] not in ('depart_date', 'arrive_date')]
        trips[:] = [t for t in trips if t['op'] != 'UPDATE' or t['updates'] or t['kind']]
        data['clarification'] = '请确认具体出发日期；确定后再按你说明的间隔安排返程。'
        normalizations.append('dates:await_explicit_holiday_date')
    has_changes = bool(basics or trips)
    start_action = None
    if data["intent"] == "START":
        if has_changes:
            data["intent"] = "UPDATE"
            normalizations.append("intent:START_to_UPDATE_with_facts")
        elif possible_fact_signal(query, context):
            return fail("本轮可能有日期、地点或交通信息尚未提取。", "POSSIBLE_FACT_OMISSION", "intent")
        else:
            action = {"IDLE": "UPDATE", "COLLECTING": "REVIEW", "READY_TO_CONFIRM": "REVIEW", "SUBMITTED": "GUIDE"}[state["flow_state"]]
            # 仍继续验证 resolutions，不允许启动意图绕过问题校验。
            data["intent"] = "REVIEW"
            start_action = action
    else:
        start_action = None
    resolutions = data["clarification_resolutions"]
    if not isinstance(resolutions, list) or len(resolutions) > 20:
        return fail("歧义解决记录格式不正确。")
    known_questions = {x["id"] for x in state["pending"] if x.get("code") == "CLARIFICATION"}
    rule_questions = {x["id"]: x for x in state["pending"] if x.get("code") != "CLARIFICATION"}
    semantic_resolutions = []
    for index, resolution in enumerate(resolutions):
        if not exact_keys(resolution, {"question_id", "evidence"}):
            return fail("歧义解决记录结构不正确。")
        path = f"clarification_resolutions[{index}]"
        if not evidence_ok(resolution["evidence"]):
            return fail("解决歧义缺少本轮原话依据。", "EVIDENCE_NOT_IN_QUERY", path + ".evidence")
        qid = resolution["question_id"]
        if not isinstance(qid, str) or qid not in known_questions | set(rule_questions):
            return fail("解决歧义必须指向已有问题。", "RESOLUTION_UNKNOWN_ID", path + ".question_id")
        if qid in rule_questions:
            normalizations.append(path + ":ignore_rule_resolution_recompute_by_code")
        else:
            semantic_resolutions.append(resolution)
    data["clarification_resolutions"] = semantic_resolutions
    if data["clarification"] and any(clean(data["clarification"]) == clean(x["question"]) for x in rule_questions.values()):
        data["clarification"] = ""
        normalizations.append("clarification:ignore_repeated_rule_question")
    if semantic_resolutions and (not has_changes or data["intent"] not in {"UPDATE", "NEW"}):
        return fail("只有明确回答并更新对应字段，才能解除已有歧义；查看或提交不能解除。")
    if data["intent"] in {"UPDATE", "NEW"} and not has_changes and not data["clarification"]:
        return fail("未提取到本轮变化；这不表示你没有提供信息。", "EMPTY_UPDATE", "$")
    command = query.strip().rstrip("。.!！").strip()
    action, message = data["intent"], ""
    if command in {"确认提交", "取消整张申请", "清空当前草稿", "放弃这张申请"}:
        if has_changes or data["clarification"]:
            return fail("纯操作指令被解析成了字段修改，请重试本轮。")
        action = "SUBMIT" if command == "确认提交" else "CANCEL"
    elif action == "NEW" and state["flow_state"] in {"COLLECTING", "READY_TO_CONFIRM"}:
        action = "GUIDE"
        message = "当前申请尚未完成，已保留原草稿。本演示同时只编辑一张申请；若要放弃当前草稿，请单独回复“取消整张申请”，然后描述新申请。"
    elif action == "CANCEL":
        action = "GUIDE"
        message = "已保留当前草稿。删除某段请说明具体行程；若要取消整张草稿，请单独回复“取消整张申请”。"
    elif action == "SUBMIT" and not has_changes:
        action = "GUIDE"
        message = "当前申请未提交。需要执行模拟提交时，请在核对最新确认单后，单独回复“确认提交”。"
    elif action in {"ASK", "UNKNOWN", "REVIEW"} and has_changes:
        return fail("操作类型与字段变化互相矛盾。")
    elif has_changes:
        action = "UPDATE"
    elif action in {"UPDATE", "NEW"}:
        if data["clarification"]:
            action = "UPDATE"
        else:
            return fail("未提取到本轮变化；这不表示你没有提供信息。", "EMPTY_UPDATE", "$")
    elif action == "ASK":
        action = "GUIDE"
        message = ("已保留当前草稿。你可以补充或修改出差日期、地点、事由和交通方式，核对后进行模拟提交。" if state.get('draft')
                   else "我可以帮你整理差旅申请，包括出差日期、地点、事由和交通方式，核对后进行模拟提交。请先告诉我你的出差安排。")
        message += "当前尚未配置住宿标准等政策问答。"
    elif action == "UNKNOWN":
        action = "GUIDE"
        message = data["clarification"] or "请描述差旅安排，或说明要修改哪项申请内容；已有草稿会保留。"
    if start_action is not None:
        action = start_action
        data["intent"] = "START"
        if state["flow_state"] == "SUBMITTED":
            message = "这张申请已模拟提交，已保留提交结果。若要填写另一张，请明确说“新申请”，并说明新的出差安排。"
    plan = {"action": action, "event": data, "query": query, "message": message}
    return {"status": "OK", "action": action, "plan_json": encode(plan), "message": "", **diagnostics()}


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def clean(value):
    return re.sub(r'\s+', '', value)


def evidence_ok(value, query):
    return isinstance(value, str) and bool(clean(value)) and clean(value) in clean(query)


def command_text(query):
    return query.strip().rstrip('。.!！').strip()


def empty_event(intent='UNKNOWN'):
    return dict(intent=intent, submit_requested='N', basic_updates=[], trip_operations=[],
                clarification='', consultation='', clarification_resolutions=[])


def load_inputs(state_json, context_json):
    """系统状态先独立读取；任何异常都不能降级为模型修复。"""
    state = json.loads(state_json)
    required = {'schema_version', 'flow_state', 'draft', 'pending', 'last_question', 'confirmation', 'last_submission', 'history'}
    if not isinstance(state, dict) or not required <= set(state):
        raise ValueError('会话结构损坏。')
    if state['schema_version'] not in ('mvp1.0', 'mvp1.2') or state['flow_state'] not in ('IDLE', 'COLLECTING', 'READY_TO_CONFIRM', 'SUBMITTED'):
        raise ValueError('会话版本或状态损坏。')
    for key in ('draft', 'confirmation', 'last_submission'):
        if not isinstance(state[key], dict):
            raise ValueError('会话对象损坏：' + key)
    if not isinstance(state['last_question'], str) or not isinstance(state['history'], list):
        raise ValueError('会话历史损坏。')
    if not isinstance(state['pending'], list) or any(not isinstance(q, dict) or not isinstance(q.get('id'), str) or not isinstance(q.get('question'), str) or not isinstance(q.get('code'), str) for q in state['pending']):
        raise ValueError('会话问题列表损坏。')
    draft = state['draft']
    if draft and (not isinstance(draft.get('trips'), list) or not isinstance(draft.get('revision'), int) or isinstance(draft.get('revision'), bool) or draft['revision'] < 0):
        raise ValueError('草稿结构损坏。')
    if draft and any(not isinstance(t, dict) or not isinstance(t.get('id'), str) for t in draft['trips']):
        raise ValueError('草稿行程结构损坏。')
    dialogue = state.get('dialogue', {})
    if not isinstance(dialogue, dict) or not isinstance(dialogue.get('recovery', {}), dict) or not isinstance(dialogue.get('focus', {}), dict):
        raise ValueError('对话状态损坏。')
    recovery = dialogue.get('recovery', {})
    if recovery and (not isinstance(recovery.get('id'), str) or recovery.get('scope') not in ('TURN','TARGET') or not isinstance(recovery.get('targets'), list) or any(not isinstance(t, dict) or not isinstance(t.get('trip_id'), str) or not isinstance(t.get('field'), str) for t in recovery['targets'])):
        raise ValueError('恢复状态损坏。')
    context = json.loads(context_json) if context_json else {}
    if not isinstance(context, dict):
        raise ValueError('业务上下文损坏。')
    if context_json and (not isinstance(context.get('reference_date'), str) or not isinstance(context.get('timezone'), str)):
        raise ValueError('业务日期上下文损坏。')
    return state, context


def possible_fact_signal(query, context):
    if re.search(r'今天|明天|后天|昨天|[上下本这]周|星期[一二三四五六日天]|周[一二三四五六日天]|\d{1,4}[年/月日号-]|[一二三四五六七八九十]+[月日号]|高铁|火车|飞机|动车|经济舱|二等座', query):
        return True
    names = list(context.get('city_names', []))
    for transport in context.get('transports', []):
        names.extend(transport.get('aliases', []))
    for city in context.get('cities', []):
        if isinstance(city, dict):
            names.extend([city.get('place', ''), city.get('name', '')])
            names.extend(city.get('aliases', []) if isinstance(city.get('aliases', []), list) else [])
    return any(isinstance(name, str) and name and name in query for name in names)


def compact_draft(value):
    if isinstance(value, list):
        return [compact_draft(x) for x in value]
    if isinstance(value, dict):
        return {k: compact_draft(v) for k, v in value.items() if k != 'evidence' and not k.startswith('resolved') and 'recommend' not in k}
    return value


def make_repair_input(parsed, query, state, context, code='', path=''):
    model_context = {k: context[k] for k in ('reference_date', 'timezone', 'weekday', 'clock_source', 'employee', 'activity_mode', 'departments', 'payer_companies') if k in context}
    model_context['city_names'] = context.get('city_names', [])
    model_context['transport_options'] = [t.get('name', '') for t in context.get('transports', []) if isinstance(t, dict)]
    dialogue = state.get('dialogue', {})
    rec = dialogue.get('recovery', {})
    focus = dialogue.get('focus', {})
    safe_focus = {k: copy.deepcopy(focus[k]) for k in ('draft_id', 'revision') if k in focus}
    safe_focus['questions'] = [{k: q.get(k, '') for k in ('id','target','field','question')} for q in focus.get('questions', [])]
    return dict(dialogue_focus=safe_focus, recovery_context=recovery_fact_context(rec, query, state['draft']), user_message=query, context=model_context, flow_state=state['flow_state'], current_draft=compact_draft(state['draft']),
                pending_questions=[{k: q.get(k, '') for k in ('id', 'code', 'target', 'field', 'question')} for q in state['pending'] if q['code'] == 'CLARIFICATION'],
                form_issues=[{k: q.get(k, '') for k in ('code', 'target', 'field', 'question')} for q in state['pending'] if q['code'] != 'CLARIFICATION'],
                original_output=parsed, error_code=code, error_path=path,
                constraints=['只能引用本轮连续原话作为 evidence。', '未知字段保持未知，不补默认业务事实。', '仅重新理解一次，不把历史失败消息作为授权或字段证据。', '确认提交和整单取消只能由独立当前原话触发。'])


def has_reanswer_clause(query):
    # 整段引用、条件和否定不构成独立授权；保守拒绝无法证明的变体。
    if any(mark in query for mark in ('“', '”', '「', '」', '『', '』', '"', "'", '`')):
        return False
    if re.search(r'如果|假如|假设|要是|是否|请问|能否|可以吗|[？?]', query):
        return False
    for clause in re.split(r'[，,；;。！!\n]', query):
        if clause.strip() == '上次未记录的内容以这次为准':
            return True
    return False


def recovery_answers(plan, state):
    recovery = state.get('dialogue', {}).get('recovery', {})
    resolutions = plan['event']['clarification_resolutions']
    current = [r for r in resolutions if recovery and r['question_id'] == recovery['id']]
    has_changes = bool(plan['event']['basic_updates'] or plan['event']['trip_operations'])
    route_restatement = (bool(recovery_fact_context(recovery, plan['query'], state['draft']).get('failed_query'))
                         and complete_route_updates(plan['event']))
    reanswer = has_changes and plan['action'] == 'UPDATE' and (has_reanswer_clause(plan['query']) or route_restatement)
    if current:
        if recovery['scope'] == 'TURN':
            valid = reanswer
        else:
            stable_ids = {t['id'] for t in state['draft'].get('trips', [])}
            changes = {('BASIC', x['field']): x for x in plan['event']['basic_updates']}
            for trip in plan['event']['trip_operations']:
                if trip['op'] == 'UPDATE' and trip['trip_id'] in stable_ids:
                    for x in trip['updates']:
                        changes[(trip['trip_id'], x['field'])] = x
            deleted_ids = {t['trip_id'] for t in plan['event']['trip_operations'] if t['op'] == 'DELETE'}
            valid = bool(recovery['targets']) and not any(t['trip_id'] in deleted_ids for t in recovery['targets']) and all((t['trip_id'], t['field']) in changes and evidence_ok(changes[(t['trip_id'], t['field'])]['evidence'], plan['query']) for t in recovery['targets'])
        if not valid:
            return ('RECOVERY_RESOLUTION_MISMATCH', 'clarification_resolutions')
    if recovery and reanswer:
        plan['recovery_resolution'] = 'REANSWER'
    return None


def primary(parsed, query, state_json, context_json='', origin='PRIMARY'):
    state, context = load_inputs(state_json, context_json)
    if not isinstance(query, str) or not query.strip():
        raise ValueError('本轮原话缺失。')
    if command_text(query) == '忽略上次未记录内容':
        event = empty_event('REVIEW' if state['draft'] else 'UNKNOWN')
        plan = dict(action='REVIEW' if state['draft'] else 'GUIDE', event=event, query=query, message='', origin=origin,
                    recovery_request={}, diagnostics=dict(source='EXACT_COMMAND', normalizations=[], error_code='', error_path=''), recovery_resolution='DISCARD')
        return dict(status='OK', action=plan['action'], plan_json=encode(plan), message='', error_code='', error_path='', diagnostics_json=encode(plan['diagnostics']), repair_input_json=encode(make_repair_input(parsed, query, state, context)))
    result = validate_event(parsed, query, state, context)
    diag = json.loads(result['diagnostics_json'])
    if result['status'] == 'OK':
        plan = json.loads(result['plan_json'])
        plan.update(origin=origin, recovery_request={}, diagnostics=diag, recovery_resolution='')
        error = recovery_answers(plan, state)
        if error:
            result.update(status='INVALID', action='ERROR', plan_json='{}', error_code=error[0], error_path=error[1], message='本轮回答尚未可靠覆盖上次未记录的内容。')
            diag.update(error_code=error[0], error_path=error[1])
        else:
            result['plan_json'] = encode(plan)
    if result['status'] != 'OK':
        result['status'] = 'CLARIFY' if result['error_code'] in ('VALUE_TOO_LONG', 'CONTENT_LIMIT') else 'REPAIR'
    result['diagnostics_json'] = encode(diag)
    result['repair_input_json'] = encode(make_repair_input(parsed, query, state, context, result['error_code'], result['error_path']))
    return result


def decoded_output(raw):
    if not isinstance(raw, str):
        return copy.deepcopy(raw)
    text = re.sub(r'^<think>[\s\S]*?</think>\s*', '', raw.strip())
    fence = re.fullmatch(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', text, flags=re.I)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        return None


def proven_failure_targets(repair, state, query, context):
    if repair['error_code'] not in ('UPDATE_VALUE_TYPE', 'EMPTY_VALUE_CONTRACT'):
        return []
    data = decoded_output(repair.get('original_output'))
    if not isinstance(data, dict) or data.get('intent') != 'UPDATE' or data.get('clarification') or data.get('consultation') or data.get('clarification_resolutions') or data.get('submit_requested', 'N') != 'N':
        return []
    basics, trips = data.get('basic_updates'), data.get('trip_operations')
    if not isinstance(basics, list) or not isinstance(trips, list):
        return []
    target = None
    if len(basics) == 1 and not trips:
        item = basics[0]
        target = {'trip_id': 'BASIC', 'field': item.get('field')} if isinstance(item, dict) else None
    elif not basics and len(trips) == 1:
        t = trips[0]
        if not isinstance(t, dict) or t.get('op') != 'UPDATE' or t.get('kind') or t.get('after_id') or t.get('trip_id') not in {x['id'] for x in state['draft'].get('trips', [])} or not re.fullmatch(r'T[1-9][0-9]*', t.get('trip_id','')):
            return []
        if not isinstance(t.get('updates'), list) or len(t['updates']) != 1 or not evidence_ok(t.get('evidence'), query):
            return []
        item = t['updates'][0]
        target = {'trip_id': t['trip_id'], 'field': item.get('field')} if isinstance(item, dict) else None
        if isinstance(item, dict) and set(item) == {'field', 'op', 'value'}:
            item['evidence'] = t['evidence']
    else:
        return []
    if not target or set(item) != {'field','op','value','evidence'} or item.get('op') not in ('SET','APPEND') or not evidence_ok(item.get('evidence'), query):
        return []
    if not (not isinstance(item['value'], str) or not item['value'].strip()):
        return []
    # 仅替换错误值做契约证明；占位符绝不进入计划或持久状态。
    item['value'] = '仅校验占位'
    result = validate_event(data, query, state, context)
    return [target] if result['status'] == 'OK' else []


def load_repair_input(repair_input_json, query):
    repair = json.loads(repair_input_json)
    if not isinstance(repair, dict) or not all(isinstance(repair.get(k), str) for k in ('user_message','error_code','error_path')) or repair['user_message'] != query:
        raise ValueError('修复共同上游输入损坏或不属于本轮。')
    return repair


def recover(query, state_json, context_json, repair_input_json, error=None):
    import hashlib
    state, context = load_inputs(state_json, context_json)
    repair = load_repair_input(repair_input_json, query)
    code, path = (error['error_code'], error['error_path']) if error else (repair['error_code'], repair['error_path'])
    targets = proven_failure_targets(repair, state, query, context)
    question = '这轮内容还没有记录，请重新说明要补充或修改的内容，并另加一句“上次未记录的内容以这次为准”；如果不再需要这轮内容，请单独回复“忽略上次未记录内容”。'
    if targets:
        labels = dict(reason='出差事由', travel_type='差旅类型', department='部门', payer_company='费用公司', all_transport='全程交通', companions='同行人', activity='活动', excluded='特殊要求', from_city='出发地', to_city='目的地', depart_date='出发日期', arrive_date='到达日期', transport='交通方式')
        t = targets[0]
        prefix = '' if t['trip_id'] == 'BASIC' else '行程' + t['trip_id'] + '的'
        question = '这轮内容还没有记录，请重新说明' + prefix + labels.get(t['field'], '该字段') + '。'
    reference_date = context.get('reference_date', state.get('demo_anchor_date',''))
    seed = encode([query, reference_date, state['draft'].get('draft_id', ''), state['draft'].get('revision', 0), code, path])
    request = dict(id='Q-RECOVERY-' + hashlib.sha256(seed.encode()).hexdigest()[:16], failed_query=query, reference_date=reference_date,
                   error_code=code, error_path=path, base_draft_id=state['draft'].get('draft_id', ''), base_revision=state['draft'].get('revision', 0),
                   question=question, targets=targets, scope='TARGET' if targets else 'TURN', failure_count=1, recent_errors=[dict(error_code=code,error_path=path)])
    # R03 同时承接跳过修复和 R01 调用失败，仅凭共同上游不能区分。
    diag = dict(source='MODEL', normalizations=[], error_code=code, error_path=path, repair_attempted=True if error else None)
    if error:
        diag['initial_error_code'] = repair['error_code']
        diag['initial_error_path'] = repair['error_path']
    plan = dict(action='CLARIFY', event=empty_event(), query=query, message=question, origin='RECOVERY', recovery_request=request, diagnostics=diag, recovery_resolution='')
    return dict(plan_json=encode(plan), diagnostics_json=encode(diag))


def revalidate(parsed, query, state_json, context_json, repair_input_json):
    load_repair_input(repair_input_json, query)
    result = primary(parsed, query, state_json, context_json, origin='REPAIRED')
    if result['status'] == 'OK':
        return dict(plan_json=result['plan_json'], diagnostics_json=result['diagnostics_json'])
    return recover(query, state_json, context_json, repair_input_json, json.loads(result['diagnostics_json']))


def check_final(plan_json, primary_only=False):
    plan = json.loads(plan_json)
    keys = {'action','event','query','message','origin','recovery_request','diagnostics','recovery_resolution'}
    if not isinstance(plan, dict) or set(plan) != keys:
        raise ValueError('统一操作计划封装不完整。')
    if plan['action'] not in ('UPDATE','REVIEW','SUBMIT','CANCEL','GUIDE','CLARIFY') or plan['origin'] not in ('PRIMARY','REPAIRED','RECOVERY'):
        raise ValueError('统一计划动作或来源不合法。')
    if primary_only and plan['origin'] != 'PRIMARY':
        raise ValueError('首次通过分支只能传递 PRIMARY 计划。')
    if not all(isinstance(plan[k], str) for k in ('action','query','message','origin','recovery_resolution')) or not isinstance(plan['diagnostics'], dict) or not isinstance(plan['recovery_request'], dict):
        raise ValueError('统一计划字段类型不正确。')
    ev = plan['event']
    if not isinstance(ev, dict) or set(ev) != set(empty_event()) or not isinstance(ev['basic_updates'], list) or not isinstance(ev['trip_operations'], list) or not isinstance(ev['clarification_resolutions'], list) or ev['submit_requested'] not in ('Y','N'):
        raise ValueError('统一计划事件结构不合法。')
    if not isinstance(ev['intent'], str) or ev['intent'] not in ('START','UPDATE','NEW','REVIEW','SUBMIT','CANCEL','ASK','UNKNOWN') or not all(isinstance(ev[k], str) for k in ('clarification','consultation')):
        raise ValueError('统一计划事件类型不正确。')
    if any(not isinstance(r, dict) or set(r) != {'question_id','evidence'} or not isinstance(r['question_id'], str) or not evidence_ok(r['evidence'], plan['query']) for r in ev['clarification_resolutions']):
        raise ValueError('统一计划问题解除结构不正确。')
    command = command_text(plan['query'])
    if command in ('确认提交', '取消整张申请', '清空当前草稿', '放弃这张申请'):
        expected_action = 'SUBMIT' if command == '确认提交' else 'CANCEL'
        expected_event = empty_event(expected_action)
        expected_event['submit_requested'] = 'Y' if expected_action == 'SUBMIT' else 'N'
        if plan['action'] != expected_action or ev != expected_event or plan['recovery_resolution']:
            raise ValueError('独立操作指令的动作及事件必须与代码生成结果一致。')
    check_state = {'flow_state': 'IDLE', 'pending': [{'id': r['question_id'], 'code': 'CLARIFICATION', 'question': ''} for r in ev['clarification_resolutions']]}
    if validate_event(ev, plan['query'], check_state, {})['status'] != 'OK':
        raise ValueError('统一计划事件未通过字段或证据校验。')
    if plan['action'] == 'SUBMIT' and (ev['intent'] != 'SUBMIT' or ev['submit_requested'] != 'Y'):
        raise ValueError('提交计划缺少一致的提交事件标记。')
    if plan['action'] == 'CANCEL' and (ev['intent'] != 'CANCEL' or ev['submit_requested'] != 'N'):
        raise ValueError('取消计划缺少一致的取消事件标记。')
    if plan['recovery_resolution'] not in ('','DISCARD','REANSWER'):
        raise ValueError('恢复解除标记不合法。')
    if plan['action'] == 'CLARIFY':
        if plan['origin'] != 'RECOVERY' or ev != empty_event() or not plan['recovery_request'] or plan['recovery_resolution']:
            raise ValueError('恢复提问必须是无业务增量的 RECOVERY 计划。')
    elif plan['origin'] == 'RECOVERY' or plan['recovery_request']:
        raise ValueError('恢复计划不能携带可执行动作。')
    if plan['action'] in ('SUBMIT','CANCEL'):
        allowed = ('确认提交',) if plan['action'] == 'SUBMIT' else ('取消整张申请','清空当前草稿','放弃这张申请')
        if command_text(plan['query']) not in allowed or ev['basic_updates'] or ev['trip_operations'] or ev['clarification_resolutions'] or ev['clarification']:
            raise ValueError('提交或取消只能由当前独立原话授权，且不能同时修改字段。')
    if plan['recovery_resolution'] == 'DISCARD' and (command_text(plan['query']) != '忽略上次未记录内容' or plan['action'] not in ('REVIEW','GUIDE') or ev['basic_updates'] or ev['trip_operations'] or ev['clarification_resolutions']):
        raise ValueError('忽略恢复事项必须是独立原话和空增量。')
    if plan['recovery_resolution'] == 'REANSWER' and (not (has_reanswer_clause(plan['query']) or explicit_route_restatement(plan['query']) and complete_route_updates(ev)) or plan['action'] != 'UPDATE' or not (ev['basic_updates'] or ev['trip_operations'])):
        raise ValueError('重述解除缺少独立声明或有效增量。')
    return plan


def complete_route_updates(event):
    # 当前话术明确重述至少去回两段，不能凭一个无关字段解除整轮恢复。
    trips = [t for t in event['trip_operations'] if t['op'] != 'DELETE']
    return len(trips) >= 2 and all({'to_city', 'depart_date'} <= {x['field'] for x in t['updates'] if x['op'] == 'SET'} for t in trips)


def main(plan_json: str) -> dict:
    check_final(plan_json, primary_only=True)
    return {"plan_json": plan_json}
