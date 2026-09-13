"""本地助手会话、消息与请求回放。与模拟单据共用 SQLite，表名独立。"""
import hashlib
import json
from uuid import uuid4

from .catalog import business_time
from .store import Store, ServiceError, encode
from .assistant_presentation import clean_answer, draft_view, present_answer


def public_state(raw, synchronized=True):
    draft = raw.get("draft") or {}
    confirmation = raw.get("confirmation") or {}
    last = raw.get("last_submission") or {}
    if (not draft or last.get("draft_id") != draft.get("draft_id")
            or last.get("revision") != draft.get("revision")):
        last = {}
    phase = raw.get("flow_state", "IDLE")
    can_submit = (synchronized and phase == "READY_TO_CONFIRM" and bool(draft)
                  and confirmation.get("draft_id") == draft.get("draft_id")
                  and confirmation.get("revision") == draft.get("revision")
                  and bool(confirmation.get("fingerprint")) and not raw.get("pending"))
    if last.get("status") == "FAILED":
        can_submit = False
    submission = None
    if last:
        submission = {"status": last.get("status", "SUCCEEDED" if phase == "SUBMITTED" else "UNKNOWN"),
                      "applicationId": last.get("application_id", ""),
                      "applicationNo": last.get("application_no", ""),
                      "requestId": last.get("request_id", ""),
                      "message": last.get("message", "")}
    return {"phase": phase, "canSubmit": bool(can_submit), "draftId": draft.get("draft_id", ""),
            "revision": draft.get("revision", 0), "fingerprint": confirmation.get("fingerprint", ""),
            "lastSubmission": submission, "pending": raw.get("pending", []),
            "draft": draft_view(draft), "synchronized": bool(synchronized)}


class AssistantStore(Store):
    def __init__(self, db_path):
        super().__init__(db_path)
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS assistant_conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, dify_user TEXT NOT NULL,
                    dify_conversation_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, state_json TEXT NOT NULL DEFAULT '{}',
                    synchronized INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS assistant_turns (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, client_request_id TEXT NOT NULL UNIQUE,
                    request_hash TEXT NOT NULL, status TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '',
                    error_json TEXT NOT NULL DEFAULT 'null', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS assistant_turn_conversation ON assistant_turns(conversation_id,created_at);
                CREATE TABLE IF NOT EXISTS assistant_messages (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS assistant_message_conversation ON assistant_messages(conversation_id,sequence);
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(assistant_conversations)")}
            if "generation" not in columns:
                conn.execute("ALTER TABLE assistant_conversations ADD COLUMN generation INTEGER NOT NULL DEFAULT 0")
            if "push_pending" not in columns:
                conn.execute("ALTER TABLE assistant_conversations ADD COLUMN push_pending INTEGER NOT NULL DEFAULT 0")
            if "deleted_at" not in columns:
                conn.execute("ALTER TABLE assistant_conversations ADD COLUMN deleted_at TEXT")
            message_columns = {row["name"] for row in conn.execute("PRAGMA table_info(assistant_messages)")}
            if "draft_state_json" not in message_columns:
                conn.execute("ALTER TABLE assistant_messages ADD COLUMN draft_state_json TEXT")
            turn_columns = {row["name"] for row in conn.execute("PRAGMA table_info(assistant_turns)")}
            if "operation_json" not in turn_columns:
                conn.execute("ALTER TABLE assistant_turns ADD COLUMN operation_json TEXT")

    def create_conversation(self):
        cid, now = uuid4().hex, business_time()["datetime"]
        with self.connection(write=True) as conn:
            conn.execute("""INSERT INTO assistant_conversations(id,title,dify_user,created_at,updated_at)
                            VALUES(?,?,?,?,?)""", (cid, "新会话", "demo-local-" + cid, now, now))
        return self.conversation(cid)

    @staticmethod
    def _require_conversation(conn, cid):
        row = conn.execute("SELECT * FROM assistant_conversations WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
        if row is None:
            raise ServiceError("CONVERSATION_NOT_FOUND", "未找到这个会话。", 404)
        return row

    def private_conversation(self, cid):
        with self.connection() as conn:
            row = self._require_conversation(conn, cid)
        return dict(row)

    def conversations(self):
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM assistant_conversations WHERE deleted_at IS NULL ORDER BY updated_at DESC, rowid DESC").fetchall()
        return {"items": [{"id": row["id"], "title": row["title"], "createdAt": row["created_at"],
                           "updatedAt": row["updated_at"], "phase": json.loads(row["state_json"]).get("flow_state", "IDLE")}
                          for row in rows]}

    def delete_conversation(self, cid):
        """从本地助手移除会话，保留单据、回执及底层审计记录。"""
        with self.connection(write=True) as conn:
            row = conn.execute("SELECT * FROM assistant_conversations WHERE id=?", (cid,)).fetchone()
            if row is None:
                raise ServiceError("CONVERSATION_NOT_FOUND", "未找到这个会话。", 404)
            if row["deleted_at"] is None:
                if conn.execute("SELECT id FROM assistant_turns WHERE conversation_id=? AND status='running'", (cid,)).fetchone():
                    raise ServiceError("CONVERSATION_BUSY", "该会话仍在处理中，请完成后再删除。", 409)
                submission = public_state(json.loads(row["state_json"])).get("lastSubmission") or {}
                if submission.get("status") == "UNKNOWN":
                    raise ServiceError("SUBMISSION_UNCERTAIN", "该会话的提交结果尚未确认，请先查询提交结果再删除。", 409)
                conn.execute("UPDATE assistant_conversations SET deleted_at=?,generation=generation+1 WHERE id=?",
                             (business_time()["datetime"], cid))
        return {"id": cid, "deleted": True}

    def conversation(self, cid):
        row = self.private_conversation(cid)
        with self.connection() as conn:
            messages = conn.execute("SELECT * FROM assistant_messages WHERE conversation_id=? ORDER BY sequence", (cid,)).fetchall()
            active = conn.execute("SELECT id FROM assistant_turns WHERE conversation_id=? AND status='running'", (cid,)).fetchone()
        return {"id": cid, "title": row["title"], "createdAt": row["created_at"], "updatedAt": row["updated_at"],
                "messages": [{"id": item["id"], "role": item["role"],
                              "content": clean_answer(item["content"]) if item["role"] == "assistant" else item["content"],
                              "createdAt": item["created_at"], "status": item["status"],
                              "draftState": json.loads(item["draft_state_json"]) if item["draft_state_json"] else None} for item in messages],
                "state": public_state(json.loads(row["state_json"]), bool(row["synchronized"])),
                "activeTurnId": active["id"] if active else None}

    @staticmethod
    def form_hash(payload):
        return hashlib.sha256(encode({"operation": "FORM_SUBMIT", "payload": payload}).encode()).hexdigest()

    def form_request(self, cid, payload):
        """网络校验前读取；真正接受操作时会在写事务内再次检查。"""
        with self.connection() as conn:
            replay = self._form_replay(conn, cid, payload)
            if replay:
                return replay, None
            row = self._form_base(conn, cid, payload)
            return None, json.loads(row["state_json"])

    def _form_replay(self, conn, cid, payload):
        self._require_conversation(conn, cid)
        existing = conn.execute("SELECT * FROM assistant_turns WHERE client_request_id=?", (payload["clientRequestId"],)).fetchone()
        if existing:
            if existing["conversation_id"] != cid or existing["request_hash"] != self.form_hash(payload):
                raise ServiceError("REQUEST_CONFLICT", "同一个请求标识不能用于不同提交内容。", 409)
            return existing["id"]
        return None

    def _form_base(self, conn, cid, payload):
        row = self._require_conversation(conn, cid)
        if conn.execute("SELECT id FROM assistant_turns WHERE conversation_id=? AND status='running'", (cid,)).fetchone():
            raise ServiceError("CONVERSATION_BUSY", "当前操作还在处理中，请稍候再提交。", 409)
        raw = json.loads(row["state_json"])
        draft, last = raw.get("draft") or {}, raw.get("last_submission") or {}
        same_last = last.get("draft_id") == draft.get("draft_id") and last.get("revision") == draft.get("revision")
        if raw.get("flow_state") == "SUBMITTED" or (same_last and last.get("status") in {"FAILED", "UNKNOWN"}):
            raise ServiceError("DRAFT_SUBMISSION_LOCKED", "该草稿已有提交记录，请先查看提交结果；失败草稿可到差旅系统进一步编辑。", 409)
        if not row["synchronized"] or payload["draftId"] != draft.get("draft_id") or payload["revision"] != draft.get("revision"):
            raise ServiceError("CONFIRMATION_STALE", "草稿已经变化或尚未同步，请重新打开最新草稿。", 409)
        return row

    def start_form(self, cid, payload, gate, pending_state, *, expected_state):
        now, tid = business_time()["datetime"], uuid4().hex
        with self.connection(write=True) as conn:
            replay = self._form_replay(conn, cid, payload)
            if replay:
                return replay, False
            row = self._form_base(conn, cid, payload)
            if json.loads(row["state_json"]) != expected_state:
                raise ServiceError("CONFIRMATION_STALE", "草稿或待处理事项已经变化，请重新打开最新草稿。", 409)
            conn.execute("""INSERT INTO assistant_turns
                (id,conversation_id,client_request_id,request_hash,status,created_at,updated_at,operation_json)
                VALUES(?,?,?,?,'running',?,?,?)""", (tid, cid, payload["clientRequestId"], self.form_hash(payload), now, now, encode(gate)))
            conn.execute("""INSERT INTO assistant_messages(id,conversation_id,turn_id,role,content,status,created_at)
                            VALUES(?,?,?,'user','编辑明细并提交单据','succeeded',?)""", (uuid4().hex, cid, tid, now))
            conn.execute("""UPDATE assistant_conversations SET state_json=?,synchronized=1,push_pending=1,
                            updated_at=?,generation=generation+1 WHERE id=?""", (encode(pending_state), now, cid))
        return tid, True

    def mark_pushed(self, cid, expected_generation):
        with self.connection(write=True) as conn:
            conn.execute("UPDATE assistant_conversations SET push_pending=0 WHERE id=? AND generation=?", (cid, expected_generation))

    def start_turn(self, cid, text, request_id, confirmation=None):
        fingerprint = hashlib.sha256(encode({"text": text, "confirmation": confirmation}).encode()).hexdigest()
        now, turn_id = business_time()["datetime"], uuid4().hex
        with self.connection(write=True) as conn:
            row = self._require_conversation(conn, cid)
            existing = conn.execute("SELECT * FROM assistant_turns WHERE client_request_id=?", (request_id,)).fetchone()
            if existing:
                if existing["conversation_id"] != cid or existing["request_hash"] != fingerprint:
                    raise ServiceError("REQUEST_CONFLICT", "同一个请求标识不能用于不同消息。", 409)
                return existing["id"], False
            if conn.execute("SELECT id FROM assistant_turns WHERE conversation_id=? AND status='running'", (cid,)).fetchone():
                raise ServiceError("CONVERSATION_BUSY", "这一轮还在处理中，请等回复完成后再发送。", 409)
            if confirmation is not None:
                state = public_state(json.loads(row["state_json"]), bool(row["synchronized"]))
                expected = {key: state[key] for key in ("draftId", "revision", "fingerprint")}
                if not state["canSubmit"] or confirmation != expected or text != "确认提交":
                    raise ServiceError("CONFIRMATION_STALE", "草稿已经变化，请核对当前版本后再确认提交。", 409)
            conn.execute("""INSERT INTO assistant_turns
                (id,conversation_id,client_request_id,request_hash,status,created_at,updated_at)
                VALUES(?,?,?,?,'running',?,?)""", (turn_id, cid, request_id, fingerprint, now, now))
            conn.execute("""INSERT INTO assistant_messages(id,conversation_id,turn_id,role,content,status,created_at)
                            VALUES(?,?,?,'user',?,'succeeded',?)""", (uuid4().hex, cid, turn_id, text, now))
            title = text[:22] + ("…" if len(text) > 22 else "") if row["title"] == "新会话" else row["title"]
            conn.execute("UPDATE assistant_conversations SET title=?,updated_at=?,generation=generation+1 WHERE id=?", (title, now, cid))
        return turn_id, True

    def turn(self, turn_id):
        with self.connection() as conn:
            row = conn.execute("""SELECT t.* FROM assistant_turns t
                JOIN assistant_conversations c ON c.id=t.conversation_id
                WHERE t.id=? AND c.deleted_at IS NULL""", (turn_id,)).fetchone()
        if not row:
            raise ServiceError("TURN_NOT_FOUND", "未找到这次处理记录。", 404)
        return {"id": row["id"], "conversationId": row["conversation_id"], "status": row["status"],
                "answer": clean_answer(row["answer"]), "error": json.loads(row["error_json"])}

    def progress(self, turn_id, answer, dify_id):
        with self.connection(write=True) as conn:
            conn.execute("UPDATE assistant_turns SET answer=?,updated_at=? WHERE id=? AND status='running'",
                         (answer, business_time()["datetime"], turn_id))
            if dify_id:
                conn.execute("""UPDATE assistant_conversations SET dify_conversation_id=?
                                WHERE id=(SELECT conversation_id FROM assistant_turns WHERE id=?)""", (dify_id, turn_id))

    def finish(self, turn_id, answer, status, state=None, error=None, push_pending=False):
        now = business_time()["datetime"]
        with self.connection(write=True) as conn:
            row = conn.execute("SELECT * FROM assistant_turns WHERE id=?", (turn_id,)).fetchone()
            if not row or row["status"] != "running":
                return
            conversation = conn.execute("SELECT * FROM assistant_conversations WHERE id=?", (row["conversation_id"],)).fetchone()
            old = json.loads(conversation["state_json"])
            answer = present_answer(answer, old, state)
            conn.execute("UPDATE assistant_turns SET answer=?,status=?,error_json=?,updated_at=? WHERE id=?",
                         (answer, status, encode(error), now, turn_id))
            shown = answer or (error or {}).get("message") or "本轮没有取得回复，请重新核对会话。"
            snapshot = None
            if state and draft_view(state.get("draft")):
                current_public = public_state(state)
                old_public = public_state(old)
                previous = conn.execute("SELECT id FROM assistant_messages WHERE conversation_id=? AND draft_state_json IS NOT NULL LIMIT 1", (row["conversation_id"],)).fetchone()
                if not previous or current_public != old_public or row["operation_json"]:
                    snapshot = encode(current_public)
            conn.execute("""INSERT INTO assistant_messages(id,conversation_id,turn_id,role,content,status,created_at,draft_state_json)
                            VALUES(?,?,?,'assistant',?,?,?,?)""", (uuid4().hex, row["conversation_id"], turn_id, shown, status, now, snapshot))
            if state is not None:
                conn.execute("UPDATE assistant_conversations SET state_json=?,synchronized=1,push_pending=?,updated_at=? WHERE id=?",
                             (conversation["state_json"] if state == old else encode(state), int(push_pending), now, row["conversation_id"]))
            else:
                conn.execute("UPDATE assistant_conversations SET synchronized=CASE WHEN push_pending=1 THEN 1 ELSE 0 END,updated_at=? WHERE id=?", (now, row["conversation_id"]))

    def synchronize(self, cid, state, *, expected_generation):
        with self.connection(write=True) as conn:
            conn.execute("""UPDATE assistant_conversations SET state_json=?,synchronized=1
                WHERE id=? AND generation=? AND push_pending=0 AND deleted_at IS NULL AND NOT EXISTS (
                    SELECT 1 FROM assistant_turns WHERE conversation_id=? AND status='running')""",
                         (encode(state), cid, expected_generation, cid))

    def interrupt_running(self):
        with self.connection() as conn:
            rows = conn.execute("SELECT id,answer FROM assistant_turns WHERE status='running'").fetchall()
        for row in rows:
            self.finish(row["id"], row["answer"], "uncertain", error={"code": "SERVICE_RESTARTED",
                "message": "上次处理因本地服务重启中断。请先核对会话与模拟单据，确认结果后再继续。"})
