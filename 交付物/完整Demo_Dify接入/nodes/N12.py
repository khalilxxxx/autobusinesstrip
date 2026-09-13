import json
import hashlib


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


def main(result_json: str) -> dict:
    result = json.loads(result_json)
    if not isinstance(result, dict) or set(result) != {"state", "reply_text"}:
        raise ValueError("分支返回结构错误。")
    state, reply = result["state"], result["reply_text"]
    keys = {"schema_version", "demo_case", "demo_anchor_date", "flow_state", "draft", "pending", "last_question", "confirmation", "last_submission", "history", "dialogue"}
    if not isinstance(state, dict) or set(state) != keys or state["schema_version"] != "mvp1.2":
        raise ValueError("待保存会话结构错误。")
    if state["flow_state"] not in {"IDLE", "COLLECTING", "READY_TO_CONFIRM", "SUBMITTED"}:
        raise ValueError("待保存状态不合法。")
    if not isinstance(reply, str) or not reply.strip():
        raise ValueError("回复内容为空，不保存新状态。")
    for key in ("draft", "confirmation", "last_submission"):
        if not isinstance(state[key], dict):
            raise ValueError("会话对象类型错误：" + key)
    if not isinstance(state["pending"], list) or not isinstance(state["history"], list) or not isinstance(state["last_question"], str):
        raise ValueError("会话列表或追问类型错误。")
    draft = state["draft"]
    validate_dialogue(state["dialogue"])
    recovery = state["dialogue"]["recovery"]
    if recovery and not any(x.get("id") == recovery["id"] for x in state["pending"]):
        raise ValueError("恢复事项与待处理问题不一致。")
    if recovery and (state["flow_state"] == "READY_TO_CONFIRM" or state["confirmation"] and state["flow_state"] != "SUBMITTED"):
        raise ValueError("恢复事项未解决，不能保留可提交确认状态。")
    if state["flow_state"] in {"READY_TO_CONFIRM", "SUBMITTED"}:
        if not draft or not draft.get("trips") or not draft.get("reason"):
            raise ValueError("完整申请状态缺少草稿内容。")
    if state["flow_state"] == "READY_TO_CONFIRM":
        if state["pending"] or state["confirmation"].get("draft_id") != draft["draft_id"]:
            raise ValueError("待确认状态与待处理项或确认标识不一致。")
        if state["confirmation"].get("revision") != draft["revision"]:
            raise ValueError("待确认版本不一致。")
    if state["flow_state"] == "SUBMITTED":
        if state["last_submission"].get("demo_only") != "Y" or state["last_submission"].get("draft_id") != draft["draft_id"]:
            raise ValueError("模拟提交状态缺少一致的提交结果。")
    if state["flow_state"] in {"READY_TO_CONFIRM", "SUBMITTED"}:
        fingerprint = hashlib.sha256(json.dumps(draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if state["confirmation"].get("fingerprint") != fingerprint:
            raise ValueError("待保存确认指纹与草稿不一致。")
    last = state["last_submission"]
    if last.get("status"):
        if last["status"] not in {"SUCCEEDED", "FAILED", "UNKNOWN"} or not last.get("request_id"):
            raise ValueError("提交回执状态或请求号不合法。")
        if state["flow_state"] == "SUBMITTED" and (last["status"] != "SUCCEEDED" or not last.get("application_id") or not last.get("application_no") or last.get("revision") != draft["revision"] or last.get("fingerprint") != fingerprint):
            raise ValueError("成功状态与真实模拟回执不一致。")
    encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > 150000 or len(reply) > 50000:
        raise ValueError("演示状态或回复过大；已停止写回以保留原状态。")
    return {"session_json": encoded, "reply_text": reply}
