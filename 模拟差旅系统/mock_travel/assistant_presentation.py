"""将工作流状态投影为卡片数据；业务状态与原始字段不在展示层修改。"""
import re


def draft_view(draft):
    if not draft or not isinstance(draft.get("trips"), list):
        return None

    def value(trip, field, resolved=None):
        return str((trip.get(resolved) or {}).get("name") or (trip.get(field) or {}).get("value") or "")

    result = {"draftId": draft.get("draft_id", ""), "revision": draft.get("revision", 0),
            "applicantName": draft.get("applicant_name", ""), "department": draft.get("department", ""),
            "payerCompany": draft.get("payer_company", ""), "travelType": draft.get("travel_type", "NORMAL"),
            "reason": draft.get("reason", ""), "trips": [
                {"id": t["id"], "fromCity": value(t, "from_city", "resolved_from"),
                 "toCity": value(t, "to_city", "resolved_to"), "departDate": value(t, "depart_date"),
                 "arriveDate": value(t, "arrive_date"), "transport": value(t, "transport", "resolved_transport")}
                for t in draft["trips"]]}
    result["editTrips"] = [{**view, "fromCity": value(trip, "from_city") or view["fromCity"],
                           "toCity": value(trip, "to_city") or view["toCity"]}
                          for trip, view in zip(draft["trips"], result["trips"])]
    return result


def clean_answer(answer):
    """兼容已发布工作流与历史消息，只移除约定的说明块及旧提交指引。"""
    lines, skipping = [], False
    for line in str(answer or "").splitlines():
        plain = re.sub(r"^[#\s>*]+", "", line).strip().strip("*")
        if re.match(r"^默认与(?:映射说明|建议)[：:]?$", plain):
            skipping = True
            continue
        if skipping:
            if not line.strip() or re.match(r"^\s*[-*]\s", line):
                continue
            skipping = False
        if "其余默认与建议可在完整确认单中查看" in line:
            continue
        line = line.replace("确认无误后，请单独回复 **确认提交**。需要修改时直接说明具体内容。",
                            "请核对下方草稿，可编辑明细、继续对话或提交单据。")
        line = line.replace("草稿与当前确认版本已保留；修复失败原因后可再次单独回复“确认提交”。",
                            "当前填写信息已保存为草稿，可前往差旅系统继续编辑并提交。")
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def present_answer(answer, old, state):
    answer = clean_answer(answer)
    if not state:
        return answer
    last = state.get("last_submission") or {}
    draft = state.get("draft") or {}
    previous = (old or {}).get("draft") or {}
    if (last.get("status") == "FAILED" and last != (old or {}).get("last_submission")
            and last.get("draft_id") == draft.get("draft_id") and last.get("revision") == draft.get("revision")):
        return "提交失败：" + str(last.get("message") or "系统暂时无法创建单据。") + "\n\n当前填写信息已保存为草稿，可前往差旅系统继续编辑并提交。"
    if not draft_view(draft) or draft == previous or state.get("flow_state") == "SUBMITTED":
        return answer
    # 只有确定生成/更新了草稿才用卡片替代重复的文字整单；澄清、咨询与异常回复保留。
    if not any(marker in answer for marker in ("已记录差旅草稿", "请核对差旅申请")):
        return answer
    changed = []
    if draft.get("draft_id") == previous.get("draft_id"):
        for key, label in (("reason", "事由"), ("travel_type", "差旅类型"), ("trips", "行程")):
            if draft.get(key) != previous.get(key):
                changed.append(label)
    reply = "已更新" + "、".join(changed) + "，请核对下方草稿。" if changed else "已整理差旅申请，请核对下方草稿。"
    questions = [x.get("question", "") for x in state.get("pending", []) if x.get("question")][:2]
    if questions:
        reply += "\n\n" + "\n".join(questions)
    for paragraph in answer.split("\n\n"):
        if "咨询" in paragraph or "演示日期基准" in paragraph:
            reply += "\n\n" + paragraph
    return reply
