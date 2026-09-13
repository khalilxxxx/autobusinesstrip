"""SQLite 持久化与请求回放，不包含权限或历史行程冲突计算。"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .catalog import business_time
from .document_numbers import initialize_document_numbers, next_document_number


class ServiceError(Exception):
    def __init__(self, code, text, status=400):
        super().__init__(text)
        self.code, self.text, self.status = code, text, status


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, db_path):
        self.path = Path(db_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS applications (
                    id TEXT PRIMARY KEY, application_no TEXT NOT NULL UNIQUE,
                    applicant_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    confirmation_key TEXT UNIQUE
                );
                CREATE TABLE IF NOT EXISTS submissions (
                    request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, confirmation_key TEXT,
                    status TEXT NOT NULL, result_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS applications_applicant ON applications(applicant_id);
            """)
            from .lifecycle import initialize_schema
            initialize_schema(conn)
            initialize_document_numbers(conn)
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('scenario',?)", (encode({
                "submissionResult": "SUCCESS", "failureMessage": "本次为模拟提单失败场景，请稍后重试。"}),))

    @contextmanager
    def connection(self, write=False):
        conn = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def scenario(self):
        with self.connection() as conn:
            return json.loads(conn.execute("SELECT value FROM settings WHERE key='scenario'").fetchone()[0])

    def update_scenario(self, updates):
        with self.connection(write=True) as conn:
            current = json.loads(conn.execute("SELECT value FROM settings WHERE key='scenario'").fetchone()[0])
            current.update(updates)
            conn.execute("UPDATE settings SET value=? WHERE key='scenario'", (encode(current),))
            return current

    def create(self, payload, request_id, draft_id=None, draft_version=None):
        serialized = encode(payload)
        fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
        confirmation = encode([payload["applicantId"], draft_id, draft_version]) if draft_id else None
        with self.connection(write=True) as conn:
            existing = conn.execute("SELECT * FROM submissions WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                if existing["payload_hash"] != fingerprint or existing["confirmation_key"] != confirmation:
                    raise ServiceError("REQUEST_CONFLICT", "同一请求标识不能用于不同内容或不同确认版本。", 409)
                return self.submission_result(conn, json.loads(existing["result_json"]))

            application = None
            if confirmation:
                application = conn.execute("SELECT * FROM applications WHERE confirmation_key=?", (confirmation,)).fetchone()
                if application and application["payload_hash"] != fingerprint:
                    raise ServiceError("DRAFT_CONFLICT", "该草稿版本已提交，内容不同须核对新版本后再提交。", 409)

            scenario = json.loads(conn.execute("SELECT value FROM settings WHERE key='scenario'").fetchone()[0])
            now = business_time()
            result = {"uuid": {"value": "MOCK-REQ-" + uuid4().hex}, "code": "SUCCESS", "message": {},
                      "data": {"action": "AI_CREATE", "demoOnly": True, "clientRequestId": request_id}}

            if application or scenario["submissionResult"] == "SUCCESS":
                if not application:
                    app_id = "MOCK-APP-" + uuid4().hex
                    number = next_document_number(conn)
                    conn.execute("""INSERT INTO applications
                        (id,application_no,applicant_id,created_at,payload_json,payload_hash,confirmation_key)
                        VALUES(?,?,?,?,?,?,?)""", (app_id, number, payload["applicantId"], now["datetime"],
                                                   serialized, fingerprint, confirmation))
                    application = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
                    from .lifecycle import initialize_document
                    initialize_document(conn, application)
                result["data"].update({"applicationId": application["id"], "applicationNo": application["application_no"],
                                       "createdAt": application["created_at"]})
            else:
                result["code"] = "MOCK_SUBMIT_FAILED"
                result["message"] = {"text": scenario["failureMessage"]}

            conn.execute("""INSERT INTO submissions
                (request_id,created_at,payload_hash,confirmation_key,status,result_json) VALUES(?,?,?,?,?,?)""",
                         (request_id, now["datetime"], fingerprint, confirmation,
                          "SUCCEEDED" if result["code"] == "SUCCESS" else "FAILED", encode(result)))
            return result

    @staticmethod
    def submission_result(conn, result):
        identifier = result.get('data', {}).get('applicationId')
        if identifier:
            row = conn.execute('SELECT application_no FROM applications WHERE id=?', (identifier,)).fetchone()
            if row: result['data']['applicationNo'] = row['application_no']
        return result

    @staticmethod
    def application_data(row):
        return {"applicationId": row["id"], "applicationNo": row["application_no"],
                "createdAt": row["created_at"], "demoOnly": True, "request": json.loads(row["payload_json"])}

    def applications(self, applicant_id=None, limit=20, offset=0):
        from .lifecycle import LifecycleService
        return LifecycleService(self).list_documents({'limit': limit, 'offset': offset}, applicant_id or 'DEMO_EMP_001')

    def application(self, application_id):
        from .lifecycle import LifecycleService
        return LifecycleService(self).document(application_id)

    def submission(self, request_id):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM submissions WHERE request_id=?", (request_id,)).fetchone()
            if not row:
                raise ServiceError("SUBMISSION_NOT_FOUND", "尚未找到该请求的处理记录；这不等于提交已经失败。", 404)
            return {"clientRequestId": row["request_id"], "createdAt": row["created_at"],
                    "status": row["status"], "result": self.submission_result(conn, json.loads(row["result_json"]))}
