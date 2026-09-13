"""独立生命周期编辑上下文；状态资格、业务写入与回执由 LifecycleService 决定。"""
from copy import deepcopy
import hashlib
import json
from threading import RLock
from typing import Literal, Optional
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from .assistant_store import AssistantStore
from .lifecycle import EMPLOYEE, validate_payload
from .lifecycle_api import ActionRequest
from .models import Identifier
from .store import ServiceError, encode


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Filters(StrictModel):
    keyword: Optional[str] = None
    city: Optional[str] = None
    dateFrom: Optional[str] = None
    dateTo: Optional[str] = None
    temporal: Optional[Literal['past','current','future']] = None
    dateBasis: Literal['trip','submitted'] = 'trip'
    status: Optional[str] = None
    effectiveOnly: bool = False
    limit: int = Field(default=20,ge=1,le=100)
    offset: int = Field(default=0,ge=0)


class Prepare(StrictModel):
    reference: Identifier
    mode: Literal['change','resubmit']


class Save(StrictModel):
    draftId: Identifier
    revision: int = Field(ge=1)
    payload: dict


class Submit(StrictModel):
    draftId: Identifier
    revision: int = Field(ge=1)
    fingerprint: Identifier
    clientRequestId: Identifier


class Action(ActionRequest):
    reference: Identifier
    action: Literal['withdraw','void']


def fingerprint(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def differences(original, payload):
    return [{'field':key,'before':original.get(key),'after':payload.get(key)}
            for key in payload if payload.get(key)!=original.get(key)]


class LifecycleAssistant:
    def __init__(self, db_path, service):
        self.store=AssistantStore(db_path)
        self.service=service
        self.lock=RLock()
        with self.store.connection() as conn:
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS assistant_lifecycle_sessions(
                cid TEXT PRIMARY KEY, state_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS assistant_lifecycle_requests(
                request_id TEXT PRIMARY KEY, cid TEXT NOT NULL, fingerprint TEXT NOT NULL,
                operation_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS assistant_lifecycle_turns(
                request_id TEXT PRIMARY KEY, cid TEXT NOT NULL, fingerprint TEXT NOT NULL, reply_json TEXT);
            ''')
            columns={row['name'] for row in conn.execute('PRAGMA table_info(assistant_lifecycle_turns)')}
            if 'business_request_id' not in columns:
                conn.execute('ALTER TABLE assistant_lifecycle_turns ADD COLUMN business_request_id TEXT')

    def _read(self,cid):
        self.store.private_conversation(cid)
        with self.store.connection() as conn:
            row=conn.execute('SELECT state_json FROM assistant_lifecycle_sessions WHERE cid=?',(cid,)).fetchone()
        return json.loads(row[0]) if row else dict(resultIds=[],selectedReference=None,draft=None,lastReceipt=None,querySummary=None)

    def _write(self,cid,state):
        with self.store.connection(write=True) as conn:
            conn.execute('INSERT OR REPLACE INTO assistant_lifecycle_sessions VALUES(?,?)',(cid,encode(state)))

    def view(self,cid):
        state=self._read(cid)
        documents=[]
        for reference in state['resultIds']:
            doc=self.service.document(reference)
            filters=(state.get('querySummary') or {}).get('filters',{})
            if filters.get('dateFrom') and filters.get('dateFrom')==filters.get('dateTo'):
                matching=self.service.list_documents(dict(keyword=doc['applicationId'],dateFrom=filters['dateFrom'],dateTo=filters['dateTo']))
                if matching['items']: doc=matching['items'][0]
            if doc['applicationId'] not in {x['applicationId'] for x in documents}: documents.append(doc)
        selected=self.service.document(state['selectedReference']) if state['selectedReference'] else None
        draft=deepcopy(state['draft'])
        if draft:
            draft['targetDocument']=self.service.document(draft['targetId'])
        receipt=state['lastReceipt']
        if receipt and receipt['status']!='UNKNOWN': receipt=self.service.receipt(receipt['clientRequestId'])
        return dict(documents=documents,selectedDocument=selected,draft=draft,lastReceipt=receipt,querySummary=state['querySummary'])

    def query(self,cid,filters):
        with self.lock:
            state=self._read(cid); result=self.service.list_documents(Filters.model_validate(filters).model_dump(exclude_none=True))
            state['resultIds']=[doc['applicationId'] for doc in result['items']]
            # 新结果集不继承上一次单据指代；编辑草稿仍独立保留。
            state['selectedReference']=None
            state['querySummary']=dict(filters=filters,total=result['total'],limit=result['limit'],offset=result['offset'])
            self._write(cid,state)
            return self.view(cid)

    def reference(self,cid,reference=None,result_index=None):
        state=self._read(cid)
        if reference: return reference
        if result_index is not None:
            if type(result_index) is not int or not 1<=result_index<=len(state['resultIds']):
                raise ServiceError('OBJECT_REQUIRED','请指出当前结果中有效的一基序号或单号。',422)
            return state['resultIds'][result_index-1]
        if state['selectedReference']: return state['selectedReference']
        if len(state['resultIds'])==1: return state['resultIds'][0]
        raise ServiceError('OBJECT_REQUIRED','请明确单号，或指定查询结果中的第几张单据。',409)

    def detail(self,cid,reference):
        with self.lock:
            state=self._read(cid); self.service.document(reference)
            state['selectedReference']=reference; self._write(cid,state)
            return self.view(cid)

    def prepare(self,cid,reference,mode):
        Prepare(reference=reference,mode=mode)
        with self.lock:
            state=self._read(cid); doc=self.service.document(reference)
            existing=state['draft']
            if existing:
                if existing['targetId']==doc['applicationId'] and existing['mode']==mode: return self.view(cid)
                raise ServiceError('DRAFT_EXISTS','已有另一份生命周期草稿，请继续编辑或明确放弃后再准备新草稿。',409)
            eligibility=doc['actions'][mode]
            if not eligibility['allowed']: raise ServiceError('ACTION_NOT_ALLOWED',eligibility['reason'],409)
            draft=dict(id=uuid4().hex,revision=1,mode=mode,targetId=doc['applicationId'],targetVersion=doc['version'],
                       payload=deepcopy(doc['request']),original=deepcopy(doc['request']),differences=[])
            draft['fingerprint']=fingerprint(draft)
            state['draft']=draft; state['selectedReference']=doc['applicationId']; self._write(cid,state)
            return self.view(cid)

    def save(self,cid,body):
        body=Save.model_validate(body).model_dump()
        with self.lock:
            state=self._read(cid); draft=state['draft']
            self._check(draft,body)
            self._editable(draft)
            updated=validate_payload(body['payload'],EMPLOYEE)
            draft['payload']=updated; draft['revision']+=1
            draft['differences']=differences(draft['original'],updated)
            draft.pop('fingerprint'); draft['fingerprint']=fingerprint(draft)
            self._write(cid,state); return self.view(cid)

    @staticmethod
    def _check(draft,body):
        if not draft or draft['id']!=body['draftId'] or draft['revision']!=body['revision'] or ('fingerprint' in body and draft['fingerprint']!=body['fingerprint']):
            raise ServiceError('CONFIRMATION_STALE','草稿已变化，请核对最新对象、版本与差异后再确认。',409)

    @staticmethod
    def _editable(draft):
        if draft and draft.get('requestId'):
            raise ServiceError('SUBMISSION_UNCERTAIN','此草稿已有办理请求，请先按原请求号 '+draft['requestId']+' 查询结果。',409)

    def cancel(self,cid):
        with self.lock:
            state=self._read(cid); self._editable(state['draft']); state['draft']=None
            self._write(cid,state); return self.view(cid)

    def _existing(self,cid,body):
        with self.store.connection() as conn:
            row=conn.execute('SELECT * FROM assistant_lifecycle_requests WHERE request_id=?',(body['clientRequestId'],)).fetchone()
        if row and (row['cid']!=cid or row['fingerprint']!=fingerprint(body)):
            raise ServiceError('REQUEST_CONFLICT','同一个请求号不能用于不同会话或办理内容。',409)
        return json.loads(row['operation_json']) if row else None

    def recover(self,cid):
        with self.lock:
            state=self._read(cid); receipt=state['lastReceipt']
            if not receipt or receipt['status']!='UNKNOWN': return self.view(cid)
            with self.store.connection() as conn:
                row=conn.execute('SELECT operation_json FROM assistant_lifecycle_requests WHERE cid=? AND request_id=?',(cid,receipt['clientRequestId'])).fetchone()
            if not row: raise ServiceError('RECEIPT_NOT_FOUND','尚未找到原办理内容，请保留原请求号联系搭建人员核对。',409)
            op=json.loads(row[0])
            if op.get('draftId'):
                draft=state['draft']
                body=dict(draftId=draft['id'],revision=draft['revision'],fingerprint=draft['fingerprint'],clientRequestId=receipt['clientRequestId'])
            else: body=op
            return self._perform(cid,body,op)

    def _perform(self,cid,body,op):
        rid=body['clientRequestId']; state=self._read(cid)
        with self.store.connection(write=True) as conn:
            already=conn.execute('SELECT request_id FROM assistant_lifecycle_requests WHERE request_id=?',(rid,)).fetchone()
            if not already:
                try: self.service.receipt(rid)
                except ServiceError as error:
                    if error.code!='RECEIPT_NOT_FOUND': raise
                else: raise ServiceError('REQUEST_CONFLICT','此请求号已用于另一项业务操作，请勿复用。',409)
            conn.execute('INSERT OR IGNORE INTO assistant_lifecycle_requests VALUES(?,?,?,?)',(rid,cid,fingerprint(body),encode(op)))
            stored=conn.execute('SELECT cid,fingerprint FROM assistant_lifecycle_requests WHERE request_id=?',(rid,)).fetchone()
            if stored['cid']!=cid or stored['fingerprint']!=fingerprint(body):
                raise ServiceError('REQUEST_CONFLICT','同一个请求号不能用于不同会话或办理内容。',409)
        if state['draft'] and op.get('draftId')==state['draft']['id']:
            state['draft']['requestId']=rid
        state['lastReceipt']=dict(clientRequestId=rid,status='UNKNOWN',result={'message':'结果尚未确认，请按原请求号继续查询。'})
        self._write(cid,state)
        try:
            try: receipt=self.service.receipt(rid)
            except ServiceError as error:
                if error.code!='RECEIPT_NOT_FOUND': raise
                # 丢响应/重启仍只发送已持久化的同号、同内容操作。
                try: self.service.operate(op['reference'],op['action'],rid,op['expectedVersion'],op.get('payload'),op.get('reason'))
                except ServiceError:
                    receipt=self.service.receipt(rid)
                else: receipt=self.service.receipt(rid)
        except Exception:
            return self.view(cid)
        state=self._read(cid); state['lastReceipt']=receipt
        if state['draft'] and op.get('draftId')==state['draft']['id']:
            if receipt['status']=='SUCCEEDED': state['draft']=None
            else: state['draft'].pop('requestId',None)
        if receipt['status']=='SUCCEEDED': state['selectedReference']=receipt['result']['document']['applicationId']
        self._write(cid,state)
        if receipt['status']=='FAILED': raise self.service._restore_error(receipt['result'])
        return self.view(cid)

    def submit(self,cid,body):
        body=Submit.model_validate(body).model_dump()
        with self.lock:
            state=self._read(cid); op=self._existing(cid,body)
            if not op:
                draft=state['draft']; self._check(draft,body); self._editable(draft)
                op=dict(reference=draft['targetId'],action=draft['mode'],expectedVersion=draft['targetVersion'],payload=draft['payload'],draftId=draft['id'])
            return self._perform(cid,body,op)

    def action(self,cid,body):
        body=Action.model_validate(body).model_dump()
        with self.lock:
            self._read(cid); op=self._existing(cid,body) or body
            return self._perform(cid,body,op)


def register_assistant_lifecycle(app,router,db_path):
    assistant=LifecycleAssistant(db_path,app.state.lifecycle)
    app.state.lifecycle_assistant=assistant
    prefix='/conversations/{cid}/lifecycle'
    @router.get(prefix)
    def view(cid:str): return assistant.view(cid)
    @router.post(prefix+'/query')
    def query(cid:str,body:Filters): return assistant.query(cid,body.model_dump(exclude_none=True))
    @router.post(prefix+'/prepare')
    def prepare(cid:str,body:Prepare): return assistant.prepare(cid,body.reference,body.mode)
    @router.put(prefix+'/draft')
    def save(cid:str,body:Save): return assistant.save(cid,body.model_dump())
    @router.post(prefix+'/submit')
    def submit(cid:str,body:Submit): return assistant.submit(cid,body.model_dump())
    @router.post(prefix+'/action')
    def action(cid:str,body:Action): return assistant.action(cid,body.model_dump())
    @router.delete(prefix+'/draft')
    def cancel(cid:str): return assistant.cancel(cid)
