"""Dify 仅提取命令，服务端负责对象定位、编辑校验、确认及真实回执。"""
from copy import deepcopy
import json
import re
from typing import Literal, Optional
from uuid import uuid4
from fastapi import Query
from pydantic import Field, ValidationError
from .catalog import CITIES, business_time, employee_context, transport_options
from .lifecycle_assistant import Filters, StrictModel, fingerprint
from .models import Identifier
from .store import ServiceError, encode


class Confirmation(StrictModel):
    draftId: Identifier
    revision: int = Field(ge=1)
    fingerprint: Identifier


class TripUpdate(StrictModel):
    index: int = Field(ge=1,le=40)
    dateFrom: Optional[str] = None
    dateTo: Optional[str] = None
    cityFrom: Optional[str] = None
    cityTo: Optional[str] = None
    tool: Optional[str] = None


class Patch(StrictModel):
    remark: Optional[str] = None
    dqydbg: Optional[Literal['Y']] = None
    departmentId: Optional[str] = None
    payerCompanyId: Optional[str] = None
    tripUpdates: list[TripUpdate] = Field(default_factory=list,max_length=40)
    addTrips: list[dict] = Field(default_factory=list,max_length=40)
    removeTripIndices: list[int] = Field(default_factory=list,max_length=40)


class Command(StrictModel):
    intent: Literal['CREATE_FLOW','QUERY','DETAIL','WITHDRAW','VOID','CHANGE','EDIT','RESUBMIT','CONFIRM','CANCEL','HELP']
    reference: Optional[Identifier] = None
    resultIndex: Optional[int] = Field(default=None,ge=1,le=100)
    filter: Optional[Filters] = None
    patch: Optional[Patch] = None
    # 由 Code 使用 context 原样填充，LLM 不生成确认值。
    confirmation: Optional[Confirmation] = None


class Turn(StrictModel):
    user: Identifier
    query: str = Field(min_length=1,max_length=4000)
    command: dict
    clientRequestId: Identifier


def document_text(doc):
    names={x['data']['cityId']:x['data']['cityName'] for x in CITIES}
    status={'S002':'待审批','S003':'审批中','S004':'已完成','S005':'已退回','S100':'已作废','UNKNOWN':'待核对'}.get(doc['status'],doc['status'])
    lines=[f"单号 {doc['applicationNo']}｜{status}（{doc['status']}）｜版本 {doc['version']}",
           f"事由：{doc['request'].get('remark','')}；{'当前有效' if doc['isEffective'] else '尚未生效或已失效'}"]
    for index,trip in enumerate(doc['request'].get('trips',[]),1):
        lines.append(f"第{index}段：{trip['dateFrom']} 至 {trip['dateTo']}，{names.get(trip['cityFrom'],trip['cityFrom'])} → {names.get(trip['cityTo'],trip['cityTo'])}，{trip['tool']}")
    for location in doc.get('locations',[]): lines.append(location['explanation'])
    return '\n'.join(lines)


def draft_text(view):
    draft=view['draft']; doc=view['selectedDocument']
    changes=draft['differences']
    labels={'remark':'事由','dqydbg':'差旅类型','departmentId':'部门','payerCompanyId':'付款公司','trips':'行程'}
    detail='；'.join(f"{labels.get(x['field'],x['field'])}：{json.dumps(x['before'],ensure_ascii=False)} → {json.dumps(x['after'],ensure_ascii=False)}" for x in changes) or '尚未修改字段，保留原单全部内容。'
    title='变更' if draft['mode']=='change' else '原号重提'
    return (f"已准备{title}草稿，目标单号 {doc['applicationNo']}，草稿版本 {draft['revision']}。\n"
            +document_text({**doc,'request':draft['payload']})+'\n差异：'+detail+f"\n请继续说明修改内容；核对后说“确认提交{title}”。")


def receipt_text(view):
    receipt=view['lastReceipt']; rid=receipt['clientRequestId']; result=receipt['result']
    if receipt['status']=='UNKNOWN': return f'办理结果尚未确认，原请求号 {rid} 已保留。请再次确认同一草稿以查询该号，勿另换请求号。'
    if receipt['status']=='FAILED': return f"办理未成功，回执请求号 {rid}：{result['message']}"
    prefix='原操作结果已查到；以下为当前单据。' if result.get('documentResolvedToCurrent') else '已取得真实业务回执。'
    return prefix+f"\n操作：{ {'withdraw':'撤回','void':'作废','change':'变更提交','resubmit':'原号重提'}.get(result['action'],result['action'])}；请求号 {rid}\n"+document_text(result['document'])


class LifecycleWorkflow:
    def __init__(self,assistant): self.assistant=assistant; self.store=assistant.store

    def conversation(self,user):
        with self.assistant.lock:
            with self.store.connection() as conn:
                row=conn.execute('SELECT id,deleted_at FROM assistant_conversations WHERE dify_user=?',(user,)).fetchone()
            if row:
                if row['deleted_at']: raise ServiceError('CONVERSATION_NOT_FOUND','此会话已移除，请开启新会话。',404)
                return row['id']
            if user.startswith('demo-local-'): raise ServiceError('CONVERSATION_NOT_FOUND','本地会话标识无效，请重新打开会话。',404)
            cid=self.store.create_conversation()['id']
            with self.store.connection(write=True) as conn:
                conn.execute('UPDATE assistant_conversations SET dify_user=?,title=? WHERE id=?',(user,'Dify 独立演示会话',cid))
            return cid

    def context(self,user,creation_editing=None):
        cid=self.conversation(user); row=self.store.private_conversation(cid)
        with self.assistant.lock:
            lifecycle_state=self.assistant._read(cid)
            if creation_editing is not None:
                lifecycle_state['creationEditing']=creation_editing
                self.assistant._write(cid,lifecycle_state)
        creation=json.loads(row['state_json']); view=self.assistant.view(cid)
        def minimal(doc):
            return {key:doc[key] for key in ('applicationId','applicationNo','status','version','documentType','actions','tripStart','tripEnd')} if doc else None
        context=employee_context()
        draft=view['draft']
        return dict(creationEditing=bool(lifecycle_state.get('creationEditing') or (creation.get('draft') and creation.get('flow_state') not in ('SUBMITTED','IDLE'))),
            draft=draft,selectedDocument=minimal(view['selectedDocument']),documents=[minimal(d) for d in view['documents']],
            querySummary=view['querySummary'],businessDate=business_time()['date'],
            options=dict(departments=context['departments'],payerCompanies=context['payerCompanies'],
                travelTypes=[{'value':None,'label':'普通差旅'},{'value':'Y','label':'短期异地办公'}],transports=transport_options(),
                cities=[{'id':x['data']['cityId'],'name':x['data']['cityName']} for x in CITIES]))

    def turn(self,body):
        cid=self.conversation(body.user)
        with self.assistant.lock:
            key=fingerprint(body.model_dump())
            with self.store.connection(write=True) as conn:
                old=conn.execute('SELECT * FROM assistant_lifecycle_turns WHERE request_id=?',(body.clientRequestId,)).fetchone()
                if old and (old['cid']!=cid or old['fingerprint']!=key):
                    return dict(handled=True,reply='无法复用此请求号处理不同消息，请使用对应的原请求号。')
                if old and old['reply_json']:
                    operation=conn.execute('SELECT request_id FROM assistant_lifecycle_requests WHERE cid=? AND request_id=?',(cid,body.clientRequestId)).fetchone()
                    if operation:
                        receipt=self.assistant.service.receipt(body.clientRequestId)
                        return dict(handled=True,reply=receipt_text({'lastReceipt':receipt}))
                    return json.loads(old['reply_json'])
                conn.execute('INSERT OR IGNORE INTO assistant_lifecycle_turns VALUES(?,?,?,NULL)',(body.clientRequestId,cid,key))
            try:
                command=Command.model_validate(body.command)
                result=self._dispatch(cid,body,command)
            except ValidationError:
                result=dict(handled=True,reply='无法理解本轮办理字段。请明确单号、操作或修改内容，已有草稿仍保留。')
            except ServiceError as error:
                details=getattr(error,'issues',[])
                reply=error.text
                if details: reply+='\n'+'；'.join(f"{x['field']}：{x['message']}" for x in details)
                result=dict(handled=True,reply=reply)
            # 未知结果不缓存终态；同号重试仍可核对业务回执。
            state=self.assistant._read(cid)
            if not (state['lastReceipt'] and state['lastReceipt']['status']=='UNKNOWN'):
                with self.store.connection(write=True) as conn:
                    conn.execute('UPDATE assistant_lifecycle_turns SET reply_json=? WHERE request_id=?',(encode(result),body.clientRequestId))
            return result

    def _dispatch(self,cid,body,command):
        query=body.query.strip(); intent=command.intent
        reply=lambda text:dict(handled=True,reply=text)
        fallthrough=dict(handled=False,reply='')
        state=self.assistant._read(cid); draft=state['draft']
        # 语言守卫不信任模型将咨询/否定误判成写入授权。
        local_cancel=bool(re.search(r'(撤销|取消|放弃).{0,8}(修改|编辑|草稿|变更草稿)',query))
        if local_cancel:
            if draft:
                self.assistant.cancel(cid); return reply('已放弃本地生命周期编辑，单据业务状态未改变。')
            return reply('当前没有生命周期编辑草稿，未办理单据撤回或作废。')
        if intent in {'WITHDRAW','VOID','CHANGE','RESUBMIT','CONFIRM','EDIT','CANCEL'}:
            if re.search(r'不要|不想|别|暂不|先不|不能|不需要|勿|能否|能.*吗|可以.*[吗么]|是否|怎么|如何|[？?]',query):
                return reply('本轮是咨询或否定表达，未执行办理。请查看单据当前状态和可用操作；明确要求后才办理。')
            if re.search(r'审批|审核|批准',query):
                return reply('助手不执行员工审批；请在模拟控制台按正常流程审批或退回。')
        if state['lastReceipt'] and state['lastReceipt']['status']=='UNKNOWN' and intent in {'WITHDRAW','VOID','CHANGE','RESUBMIT','CONFIRM','EDIT','CANCEL'}:
            return reply('先核对上次未确认办理，未执行新的操作。\n'+receipt_text(self.assistant.recover(cid)))
        if intent=='CONFIRM' and command.patch:
            if not draft: return reply('请先准备需要修改的生命周期草稿。')
            return reply(draft_text(self.patch(cid,command.patch)))
        if intent=='CREATE_FLOW': return fallthrough
        if intent=='HELP': return reply('可查询、查看单据，明确单号后撤回或作废，或先编辑变更／原号重提草稿再确认提交。审批中 S003 需模拟控制台正常退回。')
        if intent=='QUERY':
            view=self.assistant.query(cid,command.filter.model_dump(exclude_none=True) if command.filter else {})
            summary=view['querySummary']; lines=[f"共查询到 {summary['total']} 张单据，本页显示 {len(view['documents'])} 张。"]
            lines.extend(f"{i}. "+document_text(doc) for i,doc in enumerate(view['documents'],1))
            return reply('\n\n'.join(lines))
        if intent=='CANCEL':
            if not draft: return fallthrough
            self.assistant.cancel(cid); return reply('已放弃本地生命周期编辑，单据状态未改变。')
        if intent=='EDIT':
            if not draft: return fallthrough
            if not command.patch: return reply('请说明要修改的具体字段或第几段行程，草稿已保留。')
            return reply(draft_text(self.patch(cid,command.patch)))
        if intent=='CONFIRM':
            if not draft:
                if re.search(r'变更|重提',query): return reply('当前没有待确认的生命周期草稿，请先查看办理回执或准备对应草稿。')
                return fallthrough
            context=self.context(body.user)
            if context['creationEditing']:
                if re.search(r'新申请|新建',query): return fallthrough
                if not re.search(r'变更|重提',query): return reply('当前同时有新申请与生命周期草稿，请明确“确认提交新申请”或“确认提交变更／原号重提”。')
            if not re.search(r'确认.*(提交|重提)|提交.*(变更|重提)|确认变更',query):
                return reply('请核对当前草稿后明确确认提交变更或原号重提。')
            if not command.confirmation: return reply('确认信息缺失，请重新查看草稿并核对当前版本后确认。')
            request=command.confirmation.model_dump()
            request['clientRequestId']=draft.get('requestId') or body.clientRequestId
            return reply(receipt_text(self.assistant.submit(cid,request)))
        reference=self.assistant.reference(cid,command.reference,command.resultIndex)
        if intent=='DETAIL': return reply(document_text(self.assistant.detail(cid,reference)['selectedDocument']))
        if intent in {'CHANGE','RESUBMIT'}:
            doc=self.assistant.service.document(reference)
            if doc['status']=='S003': return reply('单据正在审批中（S003），请在模拟控制台正常退回后，再沿原单号编辑重提。助手不能代为审批或撤回。')
            view=self.assistant.prepare(cid,reference,'change' if intent=='CHANGE' else 'resubmit')
            if command.patch: view=self.patch(cid,command.patch)
            return reply(draft_text(view))
        if intent in {'WITHDRAW','VOID'}:
            expected_word='撤回' if intent=='WITHDRAW' else '作废'
            if expected_word not in query: return reply(f'请明确要求{expected_word}具体单据，当前未办理。')
            with self.store.connection() as conn:
                pending=conn.execute('SELECT operation_json FROM assistant_lifecycle_requests WHERE cid=? AND request_id=?',(cid,body.clientRequestId)).fetchone()
            if pending:
                return reply(receipt_text(self.assistant.action(cid,json.loads(pending[0]))))
            doc=self.assistant.service.document(reference)
            if doc['status']=='S003': return reply('这张单据正在审批中（S003），员工不能撤回或代替审批；请在模拟控制台正常退回后再继续。')
            if intent=='VOID' and doc['documentType']=='CHANGE' and doc['status']=='S002':
                return reply('这张变更仍在待审批（S002），需要先明确撤回，取得撤回回执后再单独作废，当前尚未作废。')
            # 原始引用传给业务服务，禁止读取重定向带来静默操作新单。
            body_action=dict(reference=reference,action=intent.lower(),clientRequestId=body.clientRequestId,expectedVersion=doc['version'])
            return reply(receipt_text(self.assistant.action(cid,body_action)))
        return reply('请明确需要办理的单据与操作。')

    def patch(self,cid,patch):
        draft=self.assistant._read(cid)['draft']; payload=deepcopy(draft['payload'])
        changes=patch.model_dump(exclude_unset=True)
        if not changes: raise ServiceError('PATCH_REQUIRED','请说明要修改的具体字段，草稿已保留。',422)
        updates=changes.pop('tripUpdates',[]); adds=changes.pop('addTrips',[]); removes=changes.pop('removeTripIndices',[])
        trips=payload['trips']; seen=set()
        for update in updates:
            index=update.pop('index')
            if index>len(trips) or index in seen or index in removes:
                raise ServiceError('INVALID_TRIP_INDEX','行程序号须在当前草稿范围内且不能重复或同时删除，请重新说明。',422)
            seen.add(index); trip=trips[index-1]
            # 仅服务器原快照明确同日段时可以沿用同日约束；跨日段不得猜到达日。
            if ('dateFrom' in update)!=('dateTo' in update):
                if trip['dateFrom']!=trip['dateTo']:
                    raise ServiceError('DATE_CLARIFICATION','这是一段跨日行程，请同时说明出发日与到达日，草稿已保留。',422)
                key='dateFrom' if 'dateFrom' in update else 'dateTo'
                update['dateTo' if key=='dateFrom' else 'dateFrom']=update[key]
            trip.update(update)
        if len(removes)!=len(set(removes)) or any(type(i) is not int or i<1 or i>len(trips) for i in removes):
            raise ServiceError('INVALID_TRIP_INDEX','删除行程请提供不重复且有效的一基序号，草稿已保留。',422)
        payload.update(changes); payload['trips']=[trip for i,trip in enumerate(trips,1) if i not in removes]+adds
        return self.assistant.save(cid,dict(draftId=draft['id'],revision=draft['revision'],payload=payload))


def register_lifecycle_workflow(app):
    workflow=LifecycleWorkflow(app.state.lifecycle_assistant)
    app.state.lifecycle_workflow=workflow
    @app.get('/workflow/v1/lifecycle/context',include_in_schema=False)
    def context(user:str=Query(min_length=1,max_length=128),creationEditing:Optional[bool]=None):
        return workflow.context(user,creationEditing)
    @app.post('/workflow/v1/lifecycle/turn',include_in_schema=False)
    def turn(body:Turn): return workflow.turn(body)
