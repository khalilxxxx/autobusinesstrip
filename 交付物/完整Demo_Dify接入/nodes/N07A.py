import copy
import json
import re


def main(checked_json: str, response_text: str, context_json: str) -> dict:
    checked, ctx = json.loads(checked_json), json.loads(context_json)
    result = copy.deepcopy(checked)
    requests = {x["trip_id"]: x for x in result["transport_requests"]}
    allowed = {x["name"]: x for x in ctx["transports"]}
    diagnostics = {"applied": [], "ignored": [], "parse_error": ""}

    def output():
        return {"checked_json": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                "diagnostics_json": json.dumps(diagnostics, ensure_ascii=False, separators=(",", ":"))}

    if not requests:
        return output()
    try:
        text = str(response_text or "").strip()
        thinking = re.match(r"^<think>[\s\S]*?</think>\s*", text)
        if thinking:
            text = text[thinking.end():].strip()
        fenced = re.fullmatch(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text, flags=re.I)
        if fenced:
            text = fenced.group(1).strip()
        data = json.loads(text)
        if not isinstance(data, dict) or set(data) != {"recommendations"}:
            raise ValueError("EXPECTED_RECOMMENDATIONS_OBJECT")
        recommendations = data["recommendations"]
        if not isinstance(recommendations, list) or len(recommendations) > 20:
            raise ValueError("INVALID_RECOMMENDATION_LIST")
    except (TypeError, ValueError) as exc:
        diagnostics["parse_error"] = "INVALID_MODEL_JSON: " + str(exc)[:160]
        return output()

    counts = {}
    for item in recommendations:
        if isinstance(item, dict) and isinstance(item.get("trip_id"), str):
            counts[item["trip_id"]] = counts.get(item["trip_id"], 0) + 1
    by_id = {x["id"]: (i, x) for i, x in enumerate(result["draft"]["trips"], 1)}
    for item in recommendations:
        if (not isinstance(item, dict) or set(item) != {"trip_id", "transport", "reason"}
                or not all(isinstance(v, str) for v in item.values())):
            diagnostics["ignored"].append("INVALID_ITEM_SHAPE")
            continue
        target, mode, reason = item["trip_id"], item["transport"], item["reason"].strip()
        if target not in requests or target not in by_id or counts[target] != 1:
            diagnostics["ignored"].append(target + ":UNKNOWN_OR_DUPLICATE_TARGET")
            continue
        if mode not in allowed or not reason or len(reason) > 200:
            diagnostics["ignored"].append(target + ":INVALID_OPTION_OR_REASON")
            continue
        index, trip = by_id[target]
        request = requests[target]
        if (trip["transport"]["value"] or trip["transport"]["source"] == "USER_CLEAR"
                or trip["resolved_from"]["place"] != request["from_city"]
                or trip["resolved_to"]["place"] != request["to_city"]):
            diagnostics["ignored"].append(target + ":VALUE_OR_ROUTE_CHANGED")
            continue
        trip["transport"] = {"value": mode, "source": "MODEL_ROUTE", "evidence": ""}
        trip["transport_recommendation"] = {"from_city": request["from_city"], "to_city": request["to_city"], "reason": reason}
        trip["resolved_transport"] = {"name": mode, "code": allowed[mode]["code"]}
        result["issues"] = [x for x in result["issues"] if not (x["code"] == "TRANSPORT_INCOMPLETE" and x["target"] == target and x["field"] == "transport")]
        result["notes"].append("第" + str(index) + "段交通为系统建议：" + mode + "（" + reason + "）；可直接修改。")
        diagnostics["applied"].append(target)
    missing = set(requests) - set(diagnostics["applied"])
    diagnostics["unresolved"] = sorted(missing)
    return output()
