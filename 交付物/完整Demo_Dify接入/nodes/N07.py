import copy
import json
from datetime import datetime, timedelta


def validate(candidate_json: str, context_json: str) -> dict:
    candidate, ctx = json.loads(candidate_json), json.loads(context_json)
    draft = copy.deepcopy(candidate["draft"])
    issues, notes = [], []
    requests = []

    def output(result):
        recovery = candidate["dialogue"]["recovery"]
        if recovery and not any(x["id"] == recovery["id"] for x in result["issues"]):
            result["issues"].append({"id": recovery["id"], "code": "CLARIFICATION", "target": "",
                                    "field": "interpretation", "question": recovery["question"], "priority": 0})
            result["issues"].sort(key=lambda x: x["priority"])
        result["transport_requests"] = requests
        model_input = {"trips": requests, "allowed_transports": [x["name"] for x in ctx["transports"]]}
        return {"checked_json": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                "needs_transport": "Y" if requests else "N",
                "transport_input_json": json.dumps(model_input, ensure_ascii=False, separators=(",", ":"))}

    def issue(code, question, target="", field="", priority=20):
        key = code + ":" + target + ":" + field
        if not any(x["id"] == key for x in issues):
            issues.append({"id": key, "code": code, "target": target, "field": field,
                           "question": question, "priority": priority})

    def note(text):
        if text not in notes:
            notes.append(text)

    def set_default(trip, field, value, source, explanation):
        current = trip[field]
        if not current["value"] and current["source"] != "USER_CLEAR" and value:
            trip[field] = {"value": value, "source": source, "evidence": ""}
            note(explanation)

    def city(value):
        query = "".join(value.split())
        for item in ctx["cities"]:
            if query in item["aliases"] and query not in ctx.get("city_errors", {}):
                return {key: item[key] for key in ("place", "name", "code", "mapped")}
        return {"place": value, "name": value, "code": "", "mapped": False}

    def date_value(value):
        if not value:
            return None
        try:
            result = datetime.strptime(value, "%Y-%m-%d").date()
            return result if result.isoformat() == value else None
        except ValueError:
            return None

    action = candidate["action"]
    if candidate["merge_error"] or action not in {"UPDATE", "REVIEW", "SUBMIT"} or not draft:
        result = {**candidate, "draft": draft, "issues": [], "notes": [], "date_start": "", "date_end": ""}
        return output(result)
    if draft["applicant_id"] != ctx["employee"]["id"]:
        raise ValueError("草稿申请人与当前业务身份不一致。")
    if not draft["reason"].strip():
        issue("MISSING_REASON", "请补充这次出差的具体业务目的，例如拜访客户或参加展会。", field="reason", priority=25)
    if draft["travel_type"] not in {"NORMAL", "SHORT_TERM"}:
        issue("TYPE_INVALID", "请选择普通差旅或短期异地办公。", field="travel_type", priority=10)
    for field, allowed, label in [("department", ctx["departments"], "部门"), ("payer_company", ctx["payer_companies"], "付款公司")]:
        if draft[field] not in allowed:
            issue("ORG_UNAVAILABLE", label + "不在本演示用户的授权选项中，请选择：" + "、".join(allowed) + "。", field=field, priority=5)
    if ctx["activity_mode"] == "REQUIRED":
        issue("MVP_SCOPE", "当前模拟用户必填活动，MVP 1 尚未实现活动选择，不能完成这张申请。请使用其他演示场景的新会话测试单人主线。", field="activity_mode", priority=1)
    for field, label in [("companions", "同行人"), ("activity", "活动关联"), ("excluded", "本期未支持的模块")]:
        if draft["scope_requests"][field]:
            issue("MVP_SCOPE", "已保留" + label + "要求：" + draft["scope_requests"][field] + "。MVP 1 尚不支持完成该要求；只有明确不再需要此项后，才可继续模拟提交。", field=field, priority=1)
    trips = draft["trips"]
    if not trips:
        issue("MISSING_TRIPS", "请描述至少一段出行的日期和目的地。", field="trips", priority=10)
    dates = []
    for index, trip in enumerate(trips):
        prefix = "第" + str(index + 1) + "段"
        for field in ("from_city", "to_city", "depart_date", "arrive_date", "transport"):
            if trip[field]["source"].startswith("DEFAULT_") or trip[field]["source"] == "USER_ALL":
                trip[field] = {"value": "", "source": "", "evidence": ""}
        default_from = ctx["employee"]["base_city"] if index == 0 else trips[index - 1]["to_city"]["value"]
        set_default(trip, "from_city", default_from,
                    "DEFAULT_BASE" if index == 0 else "DEFAULT_CHAIN",
                    prefix + "出发地按" + ("员工 Base" if index == 0 else "上一段目的地") + "补全为" + default_from + "。")
        if trip["kind"] == "RETURN":
            start_city = trips[0]["from_city"]["value"]
            set_default(trip, "to_city", start_city, "DEFAULT_RETURN", prefix + "返程终点按本申请实际起点补全为" + start_city + "。")
        for field, result_field, label in [("from_city", "resolved_from", "出发城市"), ("to_city", "resolved_to", "到达城市")]:
            value = trip[field]["value"]
            resolved = city(value)
            trip[result_field] = resolved
            if not resolved["code"]:
                issue("CITY_UNKNOWN", prefix + label + (ctx.get("city_errors", {}).get("".join(value.split()), "“" + value + "”没有唯一城市匹配，请明确城市名称。") if value else "尚未填写，请补充。"), trip["id"], field, 12)
            elif resolved["mapped"]:
                note(prefix + label + "原始地点为" + value + "，按业务规则使用" + resolved["name"] + "作为提单城市。")
        relation = trip.get('date_relation', {})
        if relation and trip['depart_date']['source'] not in ('USER', 'USER_CLEAR'):
            anchors = [t for t in trips[:index] if t['id'] == relation.get('anchor_trip_id')]
            anchor = date_value(anchors[0]['depart_date']['value']) if len(anchors) == 1 else None
            days = relation.get('days')
            value = (anchor + timedelta(days=days)).isoformat() if anchor and type(days) is int and 1 <= days <= 30 else ''
            trip['depart_date'] = {'value': value, 'source': 'DATE_RELATION', 'evidence': relation.get('evidence', '')}
        depart = date_value(trip["depart_date"]["value"])
        if depart:
            set_default(trip, "arrive_date", depart.isoformat(), "DEFAULT_SAME_DAY", prefix + "未指定跨日到达，按国内演示默认同日到达；请核对。")
        arrive = date_value(trip["arrive_date"]["value"])
        for field, date, label in [("depart_date", depart, "出发日期"), ("arrive_date", arrive, "到达日期")]:
            value = trip[field]["value"]
            if not date:
                # 未填出发日期时，默认的同日到达会随之补齐，不重复追问两个日期。
                if field == "arrive_date" and not value and not depart and trip[field]["source"] != "USER_CLEAR":
                    continue
                issue("DATE_INVALID" if value else "DATE_MISSING", prefix + label + ("“" + value + "”不是有效的 YYYY-MM-DD 日期，请修正。" if value else "尚未确定，请补充。"), trip["id"], field, 10)
        if depart and arrive and arrive < depart:
            issue("DATE_ORDER", prefix + "到达日期早于出发日期，请修正。", trip["id"], "arrive_date", 3)
        if index and depart and dates[index - 1][1] and depart < dates[index - 1][1]:
            issue("DATE_ORDER", prefix + "出发日期早于上一段到达日期，请修正。", trip["id"], "depart_date", 3)
        dates.append((depart, arrive))
        if not trip["transport"]["value"] and trip["transport"]["source"] != "USER_CLEAR" and draft["all_transport"]["value"]:
            trip["transport"] = copy.deepcopy(draft["all_transport"])
        if not trip["transport"]["value"] and draft["all_transport"]["source"] == "USER_CLEAR":
            trip["transport"] = copy.deepcopy(draft["all_transport"])
        origin, destination = trip["resolved_from"], trip["resolved_to"]
        if trip["transport"]["source"] == "MODEL_ROUTE":
            recommendation = trip.get("transport_recommendation", {})
            if (not origin["code"] or not destination["code"]
                    or recommendation.get("from_city") != origin["place"]
                    or recommendation.get("to_city") != destination["place"]):
                trip["transport"] = {"value": "", "source": "", "evidence": ""}
            else:
                note(prefix + "交通为系统建议：" + trip["transport"]["value"] + "（" + recommendation.get("reason", "按起止地判断") + "）；可直接修改。")
        if trip["transport"]["source"] != "MODEL_ROUTE":
            trip.pop("transport_recommendation", None)
        if (not trip["transport"]["value"] and trip["transport"]["source"] != "USER_CLEAR"
                and origin["code"] and destination["code"] and origin["code"] != destination["code"]):
            requests.append({"trip_id": trip["id"], "from_city": origin["place"], "to_city": destination["place"]})
        raw_tool = trip["transport"]["value"]
        matches = [t for t in ctx["transports"] if "".join(raw_tool.split()) in t["aliases"]]
        trip["resolved_transport"] = {"name": matches[0]["name"], "code": matches[0]["code"]} if matches else {"name": raw_tool, "code": ""}
        if not matches:
            incomplete = raw_tool in {"", "火车", "高铁", "动车", "飞机", "航班", "机票"}
            code = "TRANSPORT_INCOMPLETE" if incomplete else "TRANSPORT_UNAVAILABLE"
            question = prefix + ("交通方式或席别尚未确定。" if incomplete else "交通选择“" + raw_tool + "”不在模拟授权范围中。")
            question += "请选择：" + "、".join(t["name"] for t in ctx["transports"]) + "。"
            issue(code, question, trip["id"], "transport", 30)
        if trip["resolved_from"]["code"] and trip["resolved_to"]["code"]:
            if trip["resolved_from"]["code"] == trip["resolved_to"]["code"]:
                mapped = trip["resolved_from"]["mapped"] or trip["resolved_to"]["mapped"]
                issue("MAPPING_CONFLICT" if mapped else "SAME_CITY",
                      prefix + ("城市映射后形成同城段，需要明确业务处理口径，不能自动删段或放行。" if mapped else "出发和到达是同一业务城市，请修改行程。"), trip["id"], "cities", 2)
        if index and trips[index - 1]["resolved_to"]["code"] and trip["resolved_from"]["code"]:
            if trips[index - 1]["resolved_to"]["code"] != trip["resolved_from"]["code"]:
                issue("DISCONNECTED", prefix + "出发城市与上一段到达城市不衔接，请明确实际路线。", trip["id"], "from_city", 3)
    if trips:
        first, last = trips[0]["resolved_from"], trips[-1]["resolved_to"]
        if first["code"] and last["code"]:
            if first["code"] != last["code"]:
                issue("MISSING_RETURN", "请补充从" + last["place"] + "返回本申请起点" + first["place"] + "的日期和安排；整张申请必须闭环。", "RETURN", "depart_date", 8)
            elif first["place"] != last["place"] and (first["mapped"] or last["mapped"]):
                issue("MAPPING_CONFLICT", "起终点原始地点不同，但映射成了同一提单城市；闭环口径需要明确后才能提交。", field="closure", priority=2)
        if first["code"] and any(t["resolved_to"]["code"] == first["code"] for t in trips[:-1]):
            issue("EARLY_RETURN", "路线中途返回了最初出发城市后再次出发，不能作为一张申请。请修改本张路线；本 MVP 不自动拆单。", field="route", priority=2)
    for question in draft["open_clarifications"]:
        issues.append({"id": question["id"], "code": "CLARIFICATION", "target": "", "field": "interpretation", "question": question["question"], "priority": 0})
    issues.sort(key=lambda x: x["priority"])
    start = dates[0][0].isoformat() if dates and dates[0][0] else ""
    end = dates[-1][1].isoformat() if dates and dates[-1][1] else ""
    result = {**candidate, "draft": draft, "issues": issues, "notes": notes,
              "date_start": start, "date_end": end}
    return output(result)


def main(candidate_json: str, context_json: str, api_body: str) -> dict:
    ctx = json.loads(context_json)
    response = json.loads(api_body)
    if response.get("code") != "SUCCESS":
        raise ValueError("城市接口调用失败；不能将旧映射视为本轮校验通过。")
    ctx["cities"], ctx["city_errors"] = [], {}
    for item in response["data"]["items"]:
        original = item["query"]
        query = "".join(original.split())
        matches = item["matches"]
        if len(matches) != 1:
            ctx["city_errors"][query] = ("“" + original + "”匹配到多个城市，请明确具体城市：" + "、".join(m["cityName"] for m in matches) + "。") if matches else "“" + original + "”没有匹配到城市，请明确城市名称。"
            continue
        match = matches[0]
        name = "桐庐" if match["cityName"] == "桐庐县（桐庐基地除外）" else match["cityName"]
        mapped = match.get("mockMetadata", {}).get("matchType") == "BUSINESS_MAPPING"
        # 原始查询为唯一别名，避免其他查询的多匹配被规范名称别名旁路。
        place = ("昆山" if original in ("昆山", "昆山市", "昆山南", "昆山南站") else original) if mapped else name
        ctx["cities"].append({"place": place, "name": name, "code": match["cityId"], "mapped": mapped, "aliases": [query]})
    encoded = json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))
    result = validate(candidate_json, encoded)
    result["context_json"] = encoded
    return result
