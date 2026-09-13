"""普通员工模拟差旅接口；运行方式见项目 README。"""
import os
import json
from copy import deepcopy
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import Body, FastAPI, Form, Header, Query, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .catalog import employee_context, query_cities, transport_options
from .models import ApplicationRequest, ScenarioUpdate
from .store import ServiceError, Store
from .assistant_api import register_assistant
from .workflow_api import register_workflow

BASE = Path(__file__).resolve().parent.parent


def envelope(data, code="SUCCESS", message=None, creation=False):
    identifier = "MOCK-REQ-" + uuid4().hex
    return {"uuid": {"value": identifier} if creation else identifier, "code": code,
            "message": message or {}, "data": data}


def response_docs(data, *, creation=False, errors=None, failure=False):
    """只补充 OpenAPI 示例，不改变运行时响应或模拟规则。"""
    identifier = {"value": "MOCK-REQ-EXAMPLE"} if creation else "MOCK-REQ-EXAMPLE"

    def example(value, code="SUCCESS", message=None):
        return {"uuid": identifier, "code": code, "message": message or {}, "data": value}

    def documented(examples, description):
        return {"description": description, "content": {"application/json": {
            "schema": {"type": "object"}, "examples": examples}}}

    examples = {"success": {"summary": "成功响应", "value": example(data)}}
    if failure:
        examples["failure"] = {"summary": "预设失败，同样返回 HTTP 200", "value": example(
            {"action": "AI_CREATE", "demoOnly": True, "clientRequestId": "demo-submit-001"},
            "MOCK_SUBMIT_FAILED", {"text": "本次为模拟提单失败场景，请稍后重试。"})}
    result = {200: documented(examples, "请读取 code 判断业务结果。" if failure else "成功响应。")}
    for status, cases in (errors or {}).items():
        result[status] = documented({code: {"summary": message, "value": example({}, code, {"text": message})}
                                    for code, message in cases.items()}, "错误响应，说明位于 message.text。")
    return result


def create_app(db_path=None, *, dify_service=None):
    store = Store(db_path or os.environ.get("MOCK_TRAVEL_DB", str(BASE / "data" / "mock_travel.sqlite3")))
    app = FastAPI(
        title="普通员工模拟差旅系统", version="0.1.1",
        description="本地模拟接口：普通员工、21 项交通、城市查询、预设成功／失败创建及持久化查询。"
                    "不执行提单权限或历史行程等业务校验。创建与城市字段参考用户截图，其余是本地扩展。",
        docs_url=None, redoc_url=None,
        swagger_ui_parameters={"defaultModelsExpandDepth": -1, "displayRequestDuration": True},
        openapi_tags=[{"name": "基础数据", "description": "固定普通员工、交通选项和城市样本"},
                      {"name": "模拟提交", "description": "结果由场景开关决定，结构错误仍返回 422"},
                      {"name": "单据与回执", "description": "SQLite 中的模拟申请和每次提交结果"},
                      {"name": "场景控制", "description": "只影响后续新请求，重传旧请求仍回放原结果"}],
    )
    app.state.store = store
    from .lifecycle import LifecycleService
    app.state.lifecycle = LifecycleService(store)
    register_assistant(app, store.path, dify_service=dify_service)
    app.mount("/assets/swagger", StaticFiles(directory=str(BASE / "mock_travel" / "static" / "swagger")), name="swagger-assets")
    frontend = BASE / "frontend" / "dist"
    app.mount("/ui", StaticFiles(directory=str(frontend), check_dir=False), name="assistant-assets")
    request_example = json.loads((BASE / "examples" / "create-application.json").read_text())
    created_example = {"action": "AI_CREATE", "demoOnly": True, "clientRequestId": "demo-submit-001",
                       "applicationId": "MOCK-APP-EXAMPLE", "applicationNo": "123000001",
                       "createdAt": "2026-09-11T16:00:00+08:00"}
    application_example = {key: created_example[key] for key in ("applicationId", "applicationNo", "createdAt", "demoOnly")}
    application_example["request"] = request_example
    structure_error = {422: {"INVALID_REQUEST": "请求结构不符合接口约定，请核对参数。"}}
    scenario_example = {"submissionResult": "SUCCESS", "failureMessage": "本次为模拟提单失败场景，请稍后重试。"}

    @app.get("/docs", include_in_schema=False)
    def docs():
        return get_swagger_ui_html(
            openapi_url="/openapi.json", title="普通员工模拟差旅 · 接口调试",
            swagger_js_url="/assets/swagger/swagger-ui-bundle.js",
            swagger_css_url="/assets/swagger/swagger-ui.css", swagger_favicon_url="data:,",
            swagger_ui_parameters={"defaultModelsExpandDepth": -1, "displayRequestDuration": True},
        )

    def error_response(request, code, text, status, details=None):
        if request.url.path.startswith("/assistant/api/"):
            return JSONResponse(status_code=status, content={"error": {"code": code, "message": text,
                                **({"issues": details} if details is not None else {})}})
        message = {"text": text}
        if details is not None:
            message["details"] = details
        creation = request.method == "POST" and request.url.path == "/mock/v1/travel/applications"
        return JSONResponse(status_code=status, content=envelope({}, code, message, creation))

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError):
        return error_response(request, error.code, error.text, error.status, getattr(error, "issues", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        details = [{"field": ".".join(str(x) for x in item["loc"]), "message": item["msg"]} for item in error.errors()]
        return error_response(request, "INVALID_REQUEST", "请求结构不符合接口约定，请核对参数。", 422, details)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return error_response(request, "NOT_FOUND" if error.status_code == 404 else "HTTP_ERROR",
                              "请求的接口不存在。" if error.status_code == 404 else str(error.detail), error.status_code)

    @app.get("/", include_in_schema=False)
    def index():
        return RedirectResponse("/assistant")

    @app.get("/assistant", include_in_schema=False)
    @app.get("/simulator", include_in_schema=False)
    def frontend_page():
        index_file = frontend / "index.html"
        if not index_file.exists():
            return JSONResponse(status_code=503, content={"message": "助手页面尚未构建，请在 frontend 目录运行 npm run build。"})
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})

    @app.get("/health", summary="检查本地服务", tags=["基础数据"], responses={200: {
        "description": "本地服务正常。", "content": {"application/json": {"schema": {"type": "object"},
        "example": {"status": "ok", "service": "mock-travel", "demoOnly": True}}}}})
    def health():
        return {"status": "ok", "service": "mock-travel", "demoOnly": True}

    @app.get("/mock/v1/employee-context", summary="获取普通员工及固定上下文", tags=["基础数据"],
             responses=response_docs(employee_context(), errors={**structure_error,
                 404: {"EMPLOYEE_NOT_FOUND": "首版只配置了一名普通演示员工：DEMO_EMP_001。"}}))
    def context(employeeId: str = Query("DEMO_EMP_001", description="首版只有 DEMO_EMP_001")):
        if employeeId != "DEMO_EMP_001":
            raise ServiceError("EMPLOYEE_NOT_FOUND", "首版只配置了一名普通演示员工：DEMO_EMP_001。", 404)
        return envelope(employee_context())

    @app.get("/mock/v1/transport-options", summary="获取普通员工的 21 项交通选项", tags=["基础数据"],
             responses=response_docs(transport_options()))
    def transports():
        return envelope(transport_options())

    @app.post("/mock/v1/cities/query", summary="通过表单查询城市", tags=["基础数据"],
              responses=response_docs(query_cities("桐庐"), errors=structure_error),
              description="只需提交 filter，支持国内主要省会、直辖市及常见出差城市。"
                          "昆山按明确业务映射返回苏州；未匹配时返回成功及空数组。")
    def cities(filter: str = Form(..., min_length=1, max_length=100, description="城市名称、关键词、站点别名或城市编码")):
        if not filter.strip():
            raise ServiceError("INVALID_REQUEST", "城市查询关键词不能为空。", 422)
        return envelope(query_cities(filter))

    @app.get("/mock/v1/scenario", summary="查看当前预设提交结果", tags=["场景控制"],
             responses=response_docs(scenario_example))
    def scenario():
        return envelope(store.scenario())

    @app.put("/mock/v1/scenario", summary="切换成功／失败场景", tags=["场景控制"],
             responses=response_docs(scenario_example, errors=structure_error))
    def update_scenario(payload: ScenarioUpdate):
        return envelope(store.update_scenario(payload.model_dump(exclude_none=True)))

    @app.post("/mock/v1/travel/applications", summary="创建模拟差旅申请", tags=["模拟提交"],
              responses=response_docs(created_example, creation=True, failure=True, errors={**structure_error,
                  409: {"REQUEST_CONFLICT": "同一请求标识不能用于不同内容或不同确认版本。",
                        "DRAFT_CONFLICT": "该草稿版本已提交，内容不同须核对新版本后再提交。"}}),
              description="输入 JSON 根对象，trips 为数组。默认场景 SUCCESS；失败不生成申请。"
                          "同一次网络重试沿用 X-Client-Request-Id。可选草稿 ID／版本必须同时提供。")
    def create_application(
        payload: ApplicationRequest = Body(..., openapi_examples={
            "ordinary": {"summary": "普通员工杭州往返桐庐", "value": request_example}
        }),
        request_id: Optional[str] = Header(None, alias="X-Client-Request-Id", min_length=1, max_length=128,
                                          pattern=r"^[A-Za-z0-9_.:-]+$", description="重试沿用此值；省略则生成并在响应中返回"),
        draft_id: Optional[str] = Header(None, alias="X-Draft-Id", min_length=1, max_length=128),
        draft_version: Optional[int] = Header(None, alias="X-Draft-Version", ge=1),
    ):
        if (draft_id is None) != (draft_version is None) or (draft_id is not None and not draft_id.strip()):
            raise ServiceError("INVALID_REQUEST", "草稿 ID 与正整数版本须同时提供，或同时省略。", 422)
        return store.create(payload.model_dump(), request_id or str(uuid4()), draft_id, draft_version)

    @app.get("/mock/v1/travel/applications", summary="查看模拟申请列表", tags=["单据与回执"],
             responses=response_docs({"items": [application_example], "total": 1, "limit": 20, "offset": 0}, errors=structure_error))
    def applications(applicantId: Optional[str] = Query(None), limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return envelope(store.applications(applicantId, limit, offset))

    @app.get("/mock/v1/travel/applications/{application_id}", summary="查看模拟申请详情", tags=["单据与回执"],
             responses=response_docs(application_example, errors={**structure_error,
                 404: {"APPLICATION_NOT_FOUND": "未找到这张模拟申请。"}}))
    def application(application_id: str):
        return envelope(store.application(application_id))

    @app.get("/mock/v1/submissions/{request_id}", summary="按原请求标识查询提交结果", tags=["单据与回执"],
             responses=response_docs({"clientRequestId": "demo-submit-001", "createdAt": created_example["createdAt"],
                 "status": "SUCCEEDED", "result": {"uuid": {"value": "MOCK-REQ-EXAMPLE"}, "code": "SUCCESS",
                 "message": {}, "data": created_example}}, errors={**structure_error,
                 404: {"SUBMISSION_NOT_FOUND": "尚未找到该请求的处理记录；这不等于提交已经失败。"}}))
    def submission(request_id: str):
        return envelope(store.submission(request_id))

    from .lifecycle_api import register_lifecycle
    register_lifecycle(app, envelope)
    register_workflow(app, envelope)

    # FastAPI 生成 OpenAPI 时递归排除 None；恢复业务示例中必须保留的 JSON null。
    schema = app.openapi()
    request_content = schema["paths"]["/mock/v1/travel/applications"]["post"]["requestBody"]["content"]["application/json"]
    request_content["examples"]["ordinary"]["value"] = deepcopy(request_example)
    for path, data in (
        ("/mock/v1/travel/applications", {"items": [application_example], "total": 1, "limit": 20, "offset": 0}),
        ("/mock/v1/travel/applications/{application_id}", application_example),
    ):
        response_content = schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]
        response_content["examples"]["success"]["value"]["data"] = deepcopy(data)

    return app
