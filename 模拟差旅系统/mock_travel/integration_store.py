"""记录模拟接口调用的结果，不存请求正文、请求头或凭证。"""
import json
import logging
import time
from uuid import uuid4

from .catalog import business_time
from .store import Store


class IntegrationStore(Store):
    def __init__(self, db_path):
        super().__init__(db_path)
        with self.connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS integration_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL,
                created_at TEXT NOT NULL, source TEXT NOT NULL, method TEXT NOT NULL,
                path TEXT NOT NULL, http_status INTEGER NOT NULL, code TEXT NOT NULL,
                duration_ms INTEGER NOT NULL, request_id TEXT NOT NULL)""")

    def record(self, source, method, path, status, code, duration, request_id):
        with self.connection(write=True) as conn:
            conn.execute("""INSERT INTO integration_events
                (id,created_at,source,method,path,http_status,code,duration_ms,request_id)
                VALUES(?,?,?,?,?,?,?,?,?)""", (uuid4().hex, business_time()["datetime"], source[:48],
                method, path[:250], status, code[:80], duration, request_id[:128]))

    def events(self, limit=50):
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM integration_events ORDER BY sequence DESC LIMIT ?", (limit,)).fetchall()
        return {"items": [{"id": row["id"], "createdAt": row["created_at"], "source": row["source"],
                           "method": row["method"], "path": row["path"], "httpStatus": row["http_status"],
                           "code": row["code"], "durationMs": row["duration_ms"], "requestId": row["request_id"]}
                          for row in rows]}


class IntegrationRecorder:
    def __init__(self, app, store):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (scope["type"] != "http" or not path.startswith(("/mock/v1/", "/workflow/v1/"))
                or path == "/mock/v1/integration/events"):
            return await self.app(scope, receive, send)
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        started, status, body = time.monotonic(), 500, bytearray()

        async def capture(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and len(body) < 100000:
                body.extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            code = "HTTP_" + str(status)
            try:
                decoded = json.loads(body)
                if isinstance(decoded, dict):
                    code = str(decoded.get("code", code))
            except (ValueError, UnicodeError):
                pass
            try:
                self.store.record(headers.get("x-demo-source", "LOCAL"), scope["method"], path, status, code,
                                  round((time.monotonic() - started) * 1000),
                                  headers.get("x-workflow-run-id") or headers.get("x-client-request-id", ""))
            except Exception as error:
                logging.getLogger(__name__).error("接口记录写入失败，异常类别：%s", type(error).__name__)
