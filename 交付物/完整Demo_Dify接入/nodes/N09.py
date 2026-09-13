import copy
import hashlib
import json


def main(state_json: str, plan_json: str, checked_json: str, context_json: str) -> dict:
    state, plan, checked, ctx = (json.loads(x) for x in (state_json, plan_json, checked_json, context_json))
    next_state = copy.deepcopy(state)

    def output(reply):
        return {"result_json": json.dumps({"state": next_state, "reply_text": reply}, ensure_ascii=False, separators=(",", ":"))}

    def esc(value):
        return str(value or "待补充").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "／").replace("\n", " ").replace("\r", " ")

    def snapshot(draft):
        return {k: v for k, v in draft.items() if k != "revision"}

    action = plan["action"]
    if action == "CANCEL":
        next_state.update({"flow_state": "IDLE", "draft": {}, "pending": [], "last_question": "", "confirmation": {},
                           "dialogue": {"focus": {"draft_id": "", "revision": 0, "questions": []}, "recovery": {}}})
        return output("已清空当前草稿。已经产生的模拟单据记录仍保留；你可以描述下一张差旅申请。")
    if checked["merge_error"]:
        return output(checked["merge_error"])
    next_state["dialogue"] = copy.deepcopy(checked["dialogue"])
    if not next_state["dialogue"]["recovery"]:
        next_state["pending"] = [x for x in next_state["pending"] if not x["id"].startswith("Q-RECOVERY-")]
    if action == "CLARIFY":
        rec = next_state["dialogue"]["recovery"]
        issue = {"id": rec["id"], "code": "CLARIFICATION", "target": "", "field": "interpretation",
                 "question": rec["question"], "priority": 0}
        next_state["pending"] = [issue] + [x for x in state["pending"] if not x["id"].startswith("Q-RECOVERY-")]
        if state["flow_state"] != "SUBMITTED":
            next_state["confirmation"] = {}
            next_state["flow_state"] = "COLLECTING" if state["draft"] else "IDLE"
        next_state["last_question"] = issue["question"]
        next_state["dialogue"]["focus"] = {"draft_id": state["draft"].get("draft_id", ""),
                                           "revision": state["draft"].get("revision", 0),
                                           "questions": [{k: issue[k] for k in ("id", "target", "field", "question")}]}
        return output("这轮内容尚未记录，原草稿已保留。\n\n" + esc(rec["question"]))
    if action == "GUIDE":
        if plan.get("recovery_resolution") == "DISCARD":
            next_state["last_question"] = ""
            next_state["dialogue"]["focus"] = {"draft_id": "", "revision": 0, "questions": []}
        questions = next_state["dialogue"]["focus"]["questions"]
        next_state["last_question"] = "\n".join(x["question"] for x in questions)
        reply = plan["message"] or "已保留当前草稿，请继续说明差旅安排。"
        if questions:
            reply += "\n\n请继续补充：\n" + "\n".join(str(i) + ". " + esc(x["question"]) for i, x in enumerate(questions, 1))
        return output(reply)
    if action == "REVIEW" and state["flow_state"] == "SUBMITTED":
        return output("这张申请已模拟提交。\n\n" + state["last_submission"].get("reply_text", "请查看最近的模拟提交结果。"))
    draft = checked["draft"]
    if not draft:
        return output("当前还没有差旅草稿，请先描述出差日期、地点和业务目的。")
    if action not in {"UPDATE", "REVIEW"}:
        raise ValueError("非提交处理节点收到不支持的操作。")
    old = state["draft"]
    changed = not old or snapshot(draft) != snapshot(old)
    if not old or draft["draft_id"] != old.get("draft_id"):
        draft["revision"] = 1
    else:
        draft["revision"] = old["revision"] + (1 if changed else 0)
    ready = not checked["issues"] and not next_state["dialogue"]["recovery"]
    next_state.update({"draft": draft, "pending": checked["issues"],
                       "flow_state": "READY_TO_CONFIRM" if ready else "COLLECTING"})
    if ready:
        fingerprint = hashlib.sha256(json.dumps(draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        next_state["confirmation"] = {"draft_id": draft["draft_id"], "revision": draft["revision"], "fingerprint": fingerprint}
        next_state["last_question"] = ""
    else:
        next_state["confirmation"] = {}
    ranks = {"CLARIFICATION": 0, "MISSING_TRIPS": 6, "DATE_MISSING": 7, "CITY_UNKNOWN": 8,
             "MISSING_REASON": 9, "MISSING_RETURN": 10, "TRANSPORT_INCOMPLETE": 30}
    missing_city_targets = {x["target"] for x in checked["issues"] if x["code"] == "CITY_UNKNOWN"}
    choices = [x for x in checked["issues"] if not (x["code"] == "TRANSPORT_INCOMPLETE" and x["target"] in missing_city_targets)]
    choices.sort(key=lambda x: ranks.get(x["code"], x["priority"]))
    questions = choices[:2]
    next_state["last_question"] = "\n".join(x["question"] for x in questions)
    next_state["dialogue"]["focus"] = {"draft_id": draft["draft_id"], "revision": draft["revision"],
                                       "questions": [{k: x[k] for k in ("id", "target", "field", "question")} for x in questions]}
    if not ready and action != "REVIEW":
        lines = ["### 已记录差旅草稿（Demo）", ""]
        if not draft["trips"] and not draft["reason"] and not old:
            lines.append("已开始填写差旅申请。")
        else:
            changes = []
            labels = {"reason": "事由", "department": "部门", "payer_company": "付款公司", "travel_type": "差旅类型"}
            for key, label in labels.items():
                if draft.get(key) != old.get(key) and key == "reason" or old and draft.get(key) != old.get(key) and key != "reason":
                    changes.append(label + "：" + esc(draft.get(key)))
            old_trips = {x["id"]: x for x in old.get("trips", [])}
            for index, trip in enumerate(draft["trips"], 1):
                if old_trips.get(trip["id"]) != trip:
                    changes.append("第" + str(index) + "段：" + esc(trip["resolved_from"]["name"]) + " → " + esc(trip["resolved_to"]["name"])
                                   + "；出发日期：" + esc(trip["depart_date"]["value"]) + "；交通：" + esc(trip["resolved_transport"]["name"]))
            removed = set(old_trips) - {x["id"] for x in draft["trips"]}
            if removed:
                changes.append("已删除行程：" + "、".join(sorted(removed)))
            lines += changes[:4] or ["已保留当前草稿。"]
            if len(changes) > 4:
                lines.append("还有其他已记录变化，可回复“查看确认单”查看完整草稿。")
        if questions:
            lines += ["", "请继续补充："] + [str(i) + ". " + esc(x["question"]) for i, x in enumerate(questions, 1)]
        lines += ["", "可以直接回答，也可以一次补充多项；回复“查看确认单”可查看完整草稿。"]
        if plan["event"]["consultation"]:
            lines += ["", "同时提出的咨询已识别；当前 Demo 尚未配置政策问答，未把咨询写成申请事实。"]
        if ctx["clock_source"] == "TEST_OVERRIDE":
            lines += ["", "演示日期基准：" + ctx["reference_date"] + "（测试时间）。"]
        return output("\n".join(lines))
    title = "请核对差旅申请（Demo）" if ready else "已记录差旅草稿（Demo）"
    lines = ["### " + title, "", "申请人：" + esc(draft["applicant_name"]),
             "部门：" + esc(draft["department"]), "付款公司：" + esc(draft["payer_company"]),
             "差旅类型：" + {"NORMAL": "普通差旅", "SHORT_TERM": "短期异地办公"}.get(draft["travel_type"], "待修正"),
             "事由：" + esc(draft["reason"]), "",
             "| 段 | 出发城市 | 到达城市 | 出发日期 | 到达日期 | 交通工具 |",
             "|---|---|---|---|---|---|"]
    for index, trip in enumerate(draft["trips"], 1):
        values = [index, trip["resolved_from"]["name"], trip["resolved_to"]["name"],
                  trip["depart_date"]["value"], trip["arrive_date"]["value"], trip["resolved_transport"]["name"]]
        lines.append("| " + " | ".join(esc(x) for x in values) + " |")
    if ready:
        if plan["event"]["submit_requested"] == "Y" or plan["event"]["intent"] == "SUBMIT":
            lines += ["", "已先应用本轮修改，请核对这份新版内容。"]
        lines += ["", "确认无误后，请单独回复 **确认提交**。需要修改时直接说明具体内容。",
                  "当前已完成草稿检查，确认后将调用本地模拟系统创建申请并返回实际模拟回执。"]
    else:
        lines += ["", "请先补充或处理："] + [str(i) + ". " + esc(x["question"]) for i, x in enumerate(questions, 1)]
        if len(checked["issues"]) > 2:
            shown = {x["id"] for x in questions}
            lines += ["", "其余待处理项：" + "；".join(esc(x["question"]) for x in checked["issues"] if x["id"] not in shown)]
        lines += ["", "可以直接回答当前问题，也可以一次补充多项；已记录的信息会保留。"]
    if plan["event"]["consultation"]:
        lines += ["", "关于同时提出的咨询：当前 MVP 尚未配置政策问答，未将咨询内容写入申请事实。"]
    if ctx["clock_source"] == "TEST_OVERRIDE":
        lines += ["", "演示日期基准：" + ctx["reference_date"] + "（测试时间）。"]
    return output("\n".join(lines))
