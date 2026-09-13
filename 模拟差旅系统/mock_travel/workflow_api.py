"""面向 Dify 的批量适配；员工、交通和城市仍通过原模拟 HTTP 契约获取。"""
import asyncio
from typing import List

import httpx
from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing_extensions import Annotated

from .catalog import CITIES
from .integration_store import IntegrationRecorder, IntegrationStore
from .store import ServiceError


CityFilter = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100)]


class CityQueries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: List[CityFilter] = Field(max_length=81)


def register_workflow(app, envelope):
    records = IntegrationStore(app.state.store.path)
    app.state.integration_store = records
    app.add_middleware(IntegrationRecorder, store=records)
    router = APIRouter()

    def internal_client(request):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8766",
                                 trust_env=False,
                                 headers={"X-Demo-Source": request.headers.get("X-Demo-Source", "LOCAL") + ":ADAPTER",
                                          "X-Workflow-Run-Id": request.headers.get("X-Workflow-Run-Id", "")})

    def read_data(response):
        if response.status_code != 200:
            raise ServiceError("MOCK_API_UNAVAILABLE", "模拟基础数据接口调用失败，请稍后再试。", 502)
        result = response.json()
        if not isinstance(result, dict) or result.get("code") != "SUCCESS":
            raise ServiceError("MOCK_API_UNAVAILABLE", "模拟基础数据接口未返回成功结果。", 502)
        return result["data"]

    @router.get("/workflow/v1/context", tags=["工作流适配"], summary="按现有接口聚合员工与交通上下文")
    async def context(request: Request):
        async with internal_client(request) as client:
            employee, transports = await asyncio.gather(client.get("/mock/v1/employee-context"),
                                                        client.get("/mock/v1/transport-options"))
        return envelope({"employeeContext": read_data(employee), "transportOptions": read_data(transports),
                         "cityNames": [city["aliases"][0] for city in CITIES] + ["昆山"], "demoOnly": True})

    @router.post("/workflow/v1/cities/resolve", tags=["工作流适配"], summary="批量查询本轮涉及的城市")
    async def cities(payload: CityQueries, request: Request):
        items = []
        async with internal_client(request) as client:
            for query in dict.fromkeys(payload.queries):
                response = await client.post("/mock/v1/cities/query", data={"filter": query})
                items.append({"query": query, "matches": read_data(response)})
        return envelope({"items": items})

    @router.get("/workflow/v1/submissions/{request_id}", tags=["工作流适配"], summary="保留原 HTTP 状态的工作流回执查询")
    async def receipt(request: Request, request_id: str = Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")):
        async with internal_client(request) as client:
            response = await client.get("/mock/v1/submissions/" + request_id)
        if response.status_code not in (200, 404):
            raise ServiceError("MOCK_API_UNAVAILABLE", "回执查询暂时不可用，请保留原请求号稍后重试。", 502)
        return envelope({"httpStatus": response.status_code, "result": response.json()})

    @router.get("/mock/v1/integration/events", tags=["接口调用记录"], summary="查看最近模拟接口调用")
    def events(limit: int = Query(50, ge=1, le=200)):
        return envelope(records.events(limit))

    app.include_router(router)
