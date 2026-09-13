"""固定演示员工业务接口与独立的模拟控制台审批接口。"""
from typing import Literal, Optional
from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field
from .catalog import CITIES, employee_context, transport_options
from .models import Identifier


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['withdraw','void','change','resubmit']
    clientRequestId: Identifier
    expectedVersion: int = Field(ge=1,strict=True)
    payload: Optional[dict] = None
    reason: Optional[str] = Field(default=None,max_length=4000)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['start','complete','return']
    clientRequestId: Identifier
    expectedVersion: int = Field(ge=1,strict=True)
    reason: Optional[str] = Field(default=None,max_length=4000)


def register_lifecycle(app,envelope):
    service=app.state.lifecycle

    @app.get('/mock/v1/lifecycle/options',tags=['生命周期基础数据'],summary='查询编辑所需主数据')
    def options():
        context=employee_context()
        return envelope(dict(departments=context['departments'],payerCompanies=context['payerCompanies'],
                             travelTypes=[{'value':None,'label':'普通差旅'},{'value':'Y','label':'短期异地办公'}],
                             transports=transport_options(),cities=[entry['data'] for entry in CITIES],demoOnly=True))

    @app.get('/mock/v1/lifecycle/documents',tags=['生命周期单据'],summary='查询当前员工可见的差旅单据')
    def documents(keyword:Optional[str]=None,city:Optional[str]=None,dateFrom:Optional[str]=None,dateTo:Optional[str]=None,
                  temporal:Optional[Literal['past','current','future']]=None,dateBasis:Literal['trip','submitted']='trip',
                  status:Optional[str]=None,effectiveOnly:bool=False,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
        return envelope(service.list_documents(dict(keyword=keyword,city=city,dateFrom=dateFrom,dateTo=dateTo,
            temporal=temporal,dateBasis=dateBasis,status=status,effectiveOnly=effectiveOnly,limit=limit,offset=offset)))

    @app.get('/mock/v1/lifecycle/documents/{reference}',tags=['生命周期单据'],summary='按单号或 ID 查看当前可见内容')
    def document(reference:str): return envelope(service.document(reference))

    @app.post('/mock/v1/lifecycle/documents/{reference}/actions',tags=['生命周期员工操作'],summary='撤回、作废、变更或原单编辑重提')
    def action(reference:str,body:ActionRequest):
        return envelope(service.operate(reference,body.action,body.clientRequestId,body.expectedVersion,body.payload,body.reason))

    @app.get('/mock/v1/lifecycle/receipts/{request_id}',tags=['生命周期单据'],summary='查询操作回执')
    def receipt(request_id:str): return envelope(service.receipt(request_id))

    @app.post('/mock/v1/lifecycle/documents/{reference}/approval',tags=['模拟控制台'],summary='模拟开始审批、审批完成或退回')
    def approval(reference:str,body:ApprovalRequest):
        return envelope(service.approve(reference,body.action,body.clientRequestId,body.expectedVersion,body.reason))

    @app.post('/mock/v1/lifecycle/seed',tags=['模拟控制台'],summary='幂等生成演示样例，保留已有数据')
    def seed():
        from .lifecycle_seed import seed_documents
        return envelope(seed_documents(service))
