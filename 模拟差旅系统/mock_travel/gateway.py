"""只向 Dify 开放固定接口的本地网关；运行于 127.0.0.1:8767。"""
import json
import logging
import os
from pathlib import Path
import re
import secrets

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


BRIDGE_CONFIG = Path(os.environ.get(
    "MOCK_TRAVEL_BRIDGE_CONFIG",
    Path(__file__).resolve().parents[1] / ".local" / "bridge.json",
))
logger = logging.getLogger(__name__)

ALLOWED = {
    ("GET", "/workflow/v1/lifecycle/context"),
    ("POST", "/workflow/v1/lifecycle/turn"),
    ("GET", "/workflow/v1/context"),
    ("POST", "/workflow/v1/cities/resolve"),
    ("GET", "/mock/v1/employee-context"),
    ("GET", "/mock/v1/transport-options"),
    ("POST", "/mock/v1/cities/query"),
    ("POST", "/mock/v1/travel/applications"),
}
FORWARDED_HEADERS = {"content-type", "x-client-request-id", "x-draft-id", "x-draft-version", "x-workflow-run-id"}


def create_gateway(*, token=None, transport=None, upstream_url=None):
    if token is None:
        try:
            bridge = json.loads(BRIDGE_CONFIG.read_text(encoding="utf-8"))
            token = bridge["token"]
            upstream_url = upstream_url or bridge.get("upstream_url")
        except (OSError, ValueError, KeyError):
            raise RuntimeError(f"请先准备网关凭证配置：{BRIDGE_CONFIG}") from None
    if not isinstance(token, str) or not token or not token.isascii() or not token.isprintable():
        raise RuntimeError("网关凭证格式无效。")
    upstream_url = upstream_url or "http://127.0.0.1:8766"
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def error(status, code, message):
        return JSONResponse(status_code=status, content={"code": code, "message": {"text": message}, "data": {}})

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def forward(request: Request, path: str):
        provided = request.headers.get("authorization", "")
        if not provided.isascii() or not secrets.compare_digest(provided, "Bearer " + token):
            return error(401, "UNAUTHORIZED", "接口鉴权失败。")
        route = "/" + path
        receipt = request.method == "GET" and re.fullmatch(r"/(?:mock|workflow)/v1/submissions/[A-Za-z0-9_.:-]{1,128}", route)
        if (request.method, route) not in ALLOWED and not receipt:
            return error(404, "NOT_FOUND", "该接口未向工作流开放。")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                return error(413, "REQUEST_TOO_LARGE", "请求内容过大。")
        headers = {key: value for key, value in request.headers.items() if key.lower() in FORWARDED_HEADERS}
        headers["X-Demo-Source"] = "DIFY"
        try:
            async with httpx.AsyncClient(base_url=upstream_url, timeout=30, follow_redirects=False,
                                         trust_env=False, transport=transport) as client:
                response = await client.request(request.method, route, params=list(request.query_params.multi_items()),
                                                headers=headers, content=bytes(body))
        except httpx.RequestError:
            return error(502, "MOCK_UNREACHABLE", "本地模拟服务暂时不可用；提交结果不明确时请按原请求号查询。")
        if 300 <= response.status_code < 400:
            return error(502, "UPSTREAM_REDIRECT", "模拟接口返回了未允许的跳转。")
        logger.info("工作流网关 %s %s 状态=%s", request.method, route, response.status_code)
        return Response(response.content, status_code=response.status_code,
                        headers={"Content-Type": response.headers.get("content-type", "application/json")})

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_gateway(), host="127.0.0.1", port=8767, access_log=False)
