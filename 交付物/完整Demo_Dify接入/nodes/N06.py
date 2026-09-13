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
import copy
import hashlib
import json


def main(state_json: str, plan_json: str, context_json: str) -> dict:
    state, plan, ctx = (json.loads(x) for x in (state_json, plan_json, context_json))
    action = plan["action"]
    old = state["draft"]
    draft = copy.deepcopy(old)
    error = ""
    dialogue = copy.deepcopy(state["dialogue"])

    def empty_field():
        return {"value": "", "source": "", "evidence": ""}

    def field_value(value, source, evidence):
        return {"value": value, "source": source, "evidence": evidence}

    def route_identity(value, target_id):
        route = []
        for trip in value.get("trips", []):
            route.append((trip["id"], trip["kind"], trip["from_city"]["value"], trip["to_city"]["value"]))
            if trip["id"] == target_id:
                return route
        return None

    if action == "CLARIFY":
        request = copy.deepcopy(plan["recovery_request"])
        if not request:
            raise ValueError("恢复提问计划缺少恢复事项。")
        if dialogue["recovery"]:
            previous = dialogue["recovery"]
            previous["failure_count"] += 1
            previous["recent_errors"] = (previous["recent_errors"] + request["recent_errors"])[-3:]
            previous["scope"], previous["targets"] = "TURN", []
            previous["question"] = "仍有尚未记录的内容。请重新说明，并加上“上次未记录的内容以这次为准”；也可单独回复“忽略上次未记录内容”。"
        else:
            dialogue["recovery"] = request

    if action == "UPDATE":
        if state["flow_state"] in {"IDLE", "SUBMITTED"}:
            emp = ctx["employee"]
            draft = {"draft_id": ctx["draft_seed"], "revision": 0, "next_trip_id": 1,
                     "applicant_id": emp["id"], "applicant_name": emp["name"],
                     "department": emp["department"], "payer_company": emp["payer_company"],
                     "travel_type": "NORMAL", "reason": "", "all_transport": empty_field(),
                     "scope_requests": {"companions": "", "activity": "", "excluded": ""},
                     "basic_sources": {"department": "DEFAULT", "payer_company": "DEFAULT", "travel_type": "DEFAULT"},
                     "open_clarifications": [], "trips": []}
        try:
            event = plan["event"]
            for item in event["basic_updates"]:
                field, op, value = item["field"], item["op"], item["value"].strip()
                if field in {"companions", "activity", "excluded"}:
                    draft["scope_requests"][field] = "" if op == "CLEAR" else value
                elif field == "all_transport":
                    draft[field] = field_value("", "USER_CLEAR", item["evidence"]) if op == "CLEAR" else field_value(value, "USER_ALL", item["evidence"])
                    for trip in draft["trips"]:
                        trip["transport"] = copy.deepcopy(draft[field])
                elif field == "reason" and op == "APPEND":
                    pieces = [p for p in draft["reason"].split("；") if p]
                    if value not in pieces:
                        pieces.append(value)
                    draft["reason"] = "；".join(pieces)
                    draft["basic_sources"][field] = "USER"
                else:
                    draft[field] = "" if op == "CLEAR" else value
                    draft["basic_sources"][field] = "USER_CLEAR" if op == "CLEAR" else "USER"
            aliases = {}
            for operation in event["trip_operations"]:
                op, target = operation["op"], operation["trip_id"]
                if op == "ADD":
                    if target in aliases:
                        raise ValueError("新增行程的临时标识重复。")
                    actual = "T" + str(draft["next_trip_id"])
                    draft["next_trip_id"] += 1
                    trip = {"id": actual, "kind": operation["kind"]}
                    for key in ("from_city", "to_city", "depart_date", "arrive_date", "transport"):
                        trip[key] = empty_field()
                    after = aliases.get(operation["after_id"], operation["after_id"])
                    if after == "END":
                        position = len(draft["trips"])
                    elif after == "START":
                        position = 0
                    else:
                        positions = [i for i, t in enumerate(draft["trips"]) if t["id"] == after]
                        if len(positions) != 1:
                            raise ValueError("无法确定新增段应插在哪段之后。")
                        position = positions[0] + 1
                    draft["trips"].insert(position, trip)
                    aliases[target] = actual
                else:
                    actual = aliases.get(target, target)
                    matches = [t for t in draft["trips"] if t["id"] == actual]
                    if len(matches) != 1:
                        raise ValueError("没有找到要修改或删除的行程段，请明确具体行程。")
                    trip = matches[0]
                    if op == "DELETE":
                        draft["trips"].remove(trip)
                        continue
                    if operation["kind"]:
                        trip["kind"] = operation["kind"]
                for change in operation["updates"]:
                    key = change["field"]
                    if key == 'depart_date':
                        trip.pop('date_relation', None)
                    if change["op"] == "CLEAR":
                        trip[key] = field_value("", "USER_CLEAR", change["evidence"])
                    else:
                        trip[key] = field_value(change["value"].strip(), "USER", change["evidence"])
            if len(draft["trips"]) > 20 or len(draft["reason"]) > 1200:
                raise ValueError("本 MVP 最多支持 20 段行程和 1200 字事由，请缩小本次申请内容。")
            # 多趟仍然是已明确事实，交 N07 的 EARLY_RETURN 等业务校验阻止；不能整轮丢失。
            days = return_day_offset(plan['query'])
            if holiday_needs_date(plan['query']) and days and len(draft['trips']) == 2:
                first, last = draft['trips']
                if not first['depart_date']['value'] and not last['depart_date']['value']:
                    last['date_relation'] = {'anchor_trip_id': first['id'], 'days': days, 'evidence': plan['query']}
            resolved_ids = {x["question_id"] for x in event["clarification_resolutions"]}
            draft["open_clarifications"] = [x for x in draft["open_clarifications"] if x["id"] not in resolved_ids]
            if event["clarification"]:
                text = event["clarification"]
                question_id = "Q-" + hashlib.sha256((draft["draft_id"] + text).encode()).hexdigest()[:12]
                if not any(x["id"] == question_id for x in draft["open_clarifications"]):
                    draft["open_clarifications"].append({"id": question_id, "question": text})
            if plan.get("recovery_resolution") == "REANSWER":
                dialogue["recovery"] = {}
            elif dialogue["recovery"] and dialogue["recovery"]["id"] in resolved_ids:
                dialogue["recovery"] = {}
            rec = dialogue["recovery"]
            if rec and rec["scope"] == "TARGET":
                changed_target = old.get("draft_id") != draft.get("draft_id")
                for target in rec["targets"]:
                    if target["trip_id"] != "BASIC":
                        before_route = route_identity(old, target["trip_id"])
                        after_route = route_identity(draft, target["trip_id"])
                        changed_target = changed_target or before_route is None or after_route is None or before_route != after_route
                if changed_target:
                    rec["scope"], rec["targets"] = "TURN", []
                    rec["question"] = "原恢复目标或相关路线已变化，仍有尚未记录的内容。请重新说明，并加上“上次未记录的内容以这次为准”；也可单独回复“忽略上次未记录内容”。"
        except (KeyError, TypeError, ValueError) as exc:
            draft = copy.deepcopy(old)
            dialogue = copy.deepcopy(state["dialogue"])
            error = "本轮修改尚未应用，原草稿已保留。" + str(exc)
    if not error and plan.get("recovery_resolution") == "DISCARD":
        dialogue["recovery"] = {}
    result = {"action": action, "draft": draft, "merge_error": error,
              "clarification": plan["event"]["clarification"], "dialogue": dialogue}
    return {"candidate_json": json.dumps(result, ensure_ascii=False, separators=(",", ":"))}
