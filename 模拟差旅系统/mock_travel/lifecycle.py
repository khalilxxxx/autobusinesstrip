"""差旅单据生命周期。资格判断、链变更与回执均在立即写事务中完成。"""
from datetime import date
import hashlib
import json
from uuid import uuid4

from pydantic import ValidationError
from .catalog import CITIES, business_time, employee_context, transport_options
from .models import ApplicationRequest
from .store import ServiceError, encode

EMPLOYEE = 'DEMO_EMP_001'
JOIN = '''SELECT a.*, d.status, d.tflag, d.document_type, d.version,
 d.submission_round, d.root_id, d.predecessor_id, d.replacement_id, d.history_json,
 d.submitted_at, r.effective_id FROM applications a
 JOIN lifecycle_documents d ON d.application_id=a.id
 JOIN lifecycle_roots r ON r.root_id=d.root_id'''


def initialize_schema(conn):
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS lifecycle_roots(root_id TEXT PRIMARY KEY, effective_id TEXT);
      CREATE TABLE IF NOT EXISTS lifecycle_documents(
        application_id TEXT PRIMARY KEY, status TEXT NOT NULL, tflag TEXT NOT NULL,
        document_type TEXT NOT NULL, version INTEGER NOT NULL, submission_round INTEGER NOT NULL,
        root_id TEXT NOT NULL, predecessor_id TEXT, replacement_id TEXT,
        history_json TEXT NOT NULL, submitted_at TEXT NOT NULL);
      CREATE UNIQUE INDEX IF NOT EXISTS lifecycle_one_pending ON lifecycle_documents(root_id)
        WHERE document_type='CHANGE' AND status IN ('S002','S003','S005');
      CREATE TABLE IF NOT EXISTS lifecycle_snapshots(
        application_id TEXT NOT NULL, submission_round INTEGER NOT NULL,
        payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(application_id,submission_round));
      CREATE TABLE IF NOT EXISTS lifecycle_receipts(
        request_id TEXT PRIMARY KEY, applicant_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
        created_at TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT NOT NULL);
    ''')
    conn.execute('BEGIN IMMEDIATE')
    try:
        for row in conn.execute('SELECT * FROM applications WHERE id NOT IN (SELECT application_id FROM lifecycle_documents)').fetchall():
            initialize_document(conn,row, status='UNKNOWN')
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def event(action, before, after, round_number, role, reason=None):
    return dict(action=action, fromStatus=before, toStatus=after, submissionRound=round_number,
                at=business_time()['datetime'], role=role, **({'reason':reason} if reason else {}))


def initialize_document(conn, row, status='S002', predecessor=None, reason=None):
    root = predecessor['root_id'] if predecessor else row['id']
    conn.execute('INSERT OR IGNORE INTO lifecycle_roots(root_id) VALUES(?)',(root,))
    history=[event('change' if predecessor else 'create' if status=='S002' else 'migration',None,status,1,'EMPLOYEE' if status=='S002' else 'SYSTEM',reason)]
    conn.execute('''INSERT INTO lifecycle_documents VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                 (row['id'],status,'D','CHANGE' if predecessor else 'APPLICATION',1,1,root,
                  predecessor['id'] if predecessor else None,None,encode(history),row['created_at']))
    conn.execute('INSERT INTO lifecycle_snapshots VALUES(?,?,?,?)', (row['id'],1,row['payload_json'],row['created_at']))


def validate_payload(payload, applicant_id):
    issues=[]
    def issue(field,text): issues.append({'field':field,'message':text})
    if not isinstance(payload,dict):
        issue('payload','请提供完整申请内容。')
    else:
        for field in ('applicantId','departmentId','payerCompanyId','remark','dqydbg','trips'):
            if field not in payload: issue(field,'请补齐此字段。')
        try: ApplicationRequest.model_validate(payload)
        except ValidationError as exc:
            for error in exc.errors(): issue('.'.join(map(str,error['loc'])),'字段缺失、类型错误或格式不符合要求。')
    if issues:
        error=ServiceError('INVALID_APPLICATION','申请内容不完整或格式有误。',422); error.issues=issues; raise error
    normalized=ApplicationRequest.model_validate(payload).model_dump()
    context=employee_context()
    for field,options in [('departmentId',context['departments']),('payerCompanyId',context['payerCompanies'])]:
        if normalized[field] not in {x['id'] for x in options}: issue(field,'请选择当前员工范围内的选项。')
    if normalized['applicantId']!=applicant_id: issue('applicantId','申请人必须与当前员工一致。')
    cities={x['data']['cityId'] for x in CITIES}; transports={x['value'] for x in transport_options()}
    trips=normalized['trips']; previous=None
    for i,trip in enumerate(trips):
        for key in ('cityFrom','cityTo'):
            if trip[key] not in cities: issue(f'trips.{i}.{key}','城市编码不在主数据中。')
        if trip['cityFrom']==trip['cityTo']: issue(f'trips.{i}.cityTo','出发城市与到达城市不能相同。')
        if trip['tool'] not in transports: issue(f'trips.{i}.tool','交通选项不在主数据中。')
        valid=True
        for key in ('dateFrom','dateTo'):
            try: date.fromisoformat(trip[key])
            except ValueError: issue(f'trips.{i}.{key}','请填写真实有效的日期。'); valid=False
        if valid and trip['dateFrom']>trip['dateTo']: issue(f'trips.{i}.dateTo','到达日不能早于出发日。')
        if previous:
            if previous['cityTo']!=trip['cityFrom']: issue(f'trips.{i}.cityFrom','本段出发城市须衔接上段到达城市。')
            if previous['dateTo']>trip['dateFrom']: issue(f'trips.{i}.dateFrom','本段不能早于上段到达日。')
        previous=trip
    if trips[0]['cityFrom']!=trips[-1]['cityTo']: issue('trips','行程须返回首段出发城市，形成闭环。')
    if issues:
        error=ServiceError('INVALID_APPLICATION','申请内容未通过业务校验。',422); error.issues=issues; raise error
    return normalized


class LifecycleService:
    def __init__(self,store): self.store=store

    def _row(self,conn,reference,applicant_id=None):
        row=conn.execute(JOIN+' WHERE (a.id=? OR a.application_no=?)',(reference,reference)).fetchone()
        if not row or (applicant_id is not None and row['applicant_id']!=applicant_id):
            raise ServiceError('APPLICATION_NOT_FOUND','未找到当前员工的这张单据。',404)
        return row

    def _pending(self,conn,root):
        row=conn.execute("SELECT application_id FROM lifecycle_documents WHERE root_id=? AND document_type='CHANGE' AND status IN ('S002','S003','S005')",(root,)).fetchone()
        return row[0] if row else None

    def _actions(self,conn,row):
        pending=self._pending(conn,row['root_id'])
        effective=row['effective_id']==row['id']
        active=not row['replacement_id'] and row['tflag']!='YBX'
        base=active and effective and row['status']=='S004' and not pending and row['tflag']=='D'
        valid_change=(row['document_type']=='CHANGE' and pending==row['id'] and
                      row['effective_id']==row['predecessor_id'])
        allowed=dict(withdraw=active and row['status']=='S002',void=base or (
            active and row['status']=='S005' and valid_change),change=base,
            resubmit=active and row['status']=='S005' and (row['document_type']=='APPLICATION' or valid_change))
        reasons={'withdraw':'仅本次提交尚未审批的 S002 单据可撤回。','void':'仅无在途变更的有效已完成单据或已退回的在途变更可作废。',
                 'change':'仅未转报销、无在途变更的当前有效已完成单据可变更。','resubmit':'仅 S005 单据可沿原单号重提，变更前序须仍有效。'}
        return {key:{'allowed':bool(value),'reason':None if value else reasons[key]} for key,value in allowed.items()}

    def _dto(self,conn,row):
        root=conn.execute('SELECT application_no FROM applications WHERE id=?',(row['root_id'],)).fetchone()[0]
        request=json.loads(row['payload_json']); trips=request.get('trips',[])
        return dict(applicationId=row['id'],applicationNo=row['application_no'],createdAt=row['created_at'],request=request,demoOnly=True,
                    status=row['status'],tflag=row['tflag'],documentType=row['document_type'],version=row['version'],
                    submissionRound=row['submission_round'],rootId=row['root_id'],rootNo=root,predecessorId=row['predecessor_id'],
                    currentEffectiveId=row['effective_id'],isEffective=row['id']==row['effective_id'],isSuperseded=bool(row['replacement_id']),
                    pendingChangeId=self._pending(conn,row['root_id']),history=json.loads(row['history_json']),actions=self._actions(conn,row),
                    submittedAt=row['submitted_at'],tripStart=min((x['dateFrom'] for x in trips),default=None),
                    tripEnd=max((x['dateTo'] for x in trips),default=None))

    def _document(self,conn,reference,applicant_id):
        row=self._row(conn,reference,applicant_id); redirected=bool(row['replacement_id'])
        while row['replacement_id']: row=self._row(conn,row['replacement_id'],applicant_id)
        result=self._dto(conn,row)
        if redirected: result['resolvedFrom']=reference
        return result

    def document(self,reference,applicant_id=EMPLOYEE):
        with self.store.connection() as conn:
            conn.execute('BEGIN')
            return self._document(conn,reference,applicant_id)

    def list_documents(self,filters,applicant_id=EMPLOYEE):
        from .lifecycle_query import query_documents
        with self.store.connection() as conn:
            conn.execute('BEGIN')
            rows=conn.execute(JOIN+' WHERE a.applicant_id=? AND d.replacement_id IS NULL ORDER BY a.created_at DESC,a.rowid DESC',(applicant_id,)).fetchall()
            documents=[self._dto(conn,row) for row in rows]
            # 旧单号仅作为当前版本的匹配别名，旧申请内容不参与筛选。
            aliases={}
            for old in conn.execute(JOIN+' WHERE a.applicant_id=? AND d.replacement_id IS NOT NULL',(applicant_id,)).fetchall():
                current=self._document(conn,old['id'],applicant_id)['applicationId']
                aliases.setdefault(current,[]).extend([old['id'],old['application_no']])
            return query_documents(documents,filters,aliases)

    def operate(self,reference,action,request_id,expected_version,payload=None,reason=None,applicant_id=EMPLOYEE):
        return self._execute(reference,action,request_id,expected_version,payload,reason,applicant_id,'EMPLOYEE')

    def approve(self,reference,action,request_id,expected_version,reason=None):
        return self._execute(reference,action,request_id,expected_version,None,reason,EMPLOYEE,'APPROVER')

    def _project_result(self,conn,result,applicant_id):
        if 'document' in result:
            row=self._row(conn,result['document']['applicationId'],applicant_id)
            if row['replacement_id'] or json.loads(row['payload_json']) != result['document']['request']:
                result={**result,'document':self._document(conn,row['id'],applicant_id),
                        'documentResolvedToCurrent':True}
        return result

    def receipt(self,request_id,applicant_id=EMPLOYEE):
        with self.store.connection() as conn:
            conn.execute('BEGIN')
            row=conn.execute('SELECT * FROM lifecycle_receipts WHERE request_id=? AND applicant_id=?',(request_id,applicant_id)).fetchone()
            if not row: raise ServiceError('RECEIPT_NOT_FOUND','尚未找到该操作回执，这不代表操作已经失败。',404)
            result=self._project_result(conn,json.loads(row['result_json']),applicant_id)
            return dict(clientRequestId=request_id,createdAt=row['created_at'],status=row['status'],result=result,demoOnly=True)

    def _execute(self,reference,action,request_id,expected_version,payload,reason,applicant_id,role):
        if not isinstance(request_id,str) or not request_id.strip() or len(request_id)>128:
            raise ServiceError('INVALID_REQUEST','请提供有效的客户端请求标识。',422)
        fingerprint=hashlib.sha256(encode([reference,action,expected_version,payload,reason,applicant_id,role]).encode()).hexdigest()
        error=None; result=None
        with self.store.connection(write=True) as conn:
            existing=conn.execute('SELECT * FROM lifecycle_receipts WHERE request_id=?',(request_id,)).fetchone()
            if existing:
                if existing['applicant_id']!=applicant_id or existing['fingerprint']!=fingerprint:
                    raise ServiceError('REQUEST_CONFLICT','同一请求标识不能用于不同身份、操作或内容。',409)
                result=json.loads(existing['result_json'])
                if existing['status']=='FAILED': error=self._restore_error(result)
                else: result=self._project_result(conn,result,applicant_id)
            else:
                conn.execute('SAVEPOINT lifecycle_action')
                try:
                    row=self._row(conn,reference,applicant_id)
                    if row['replacement_id']: raise ServiceError('SUPERSEDED_DOCUMENT','此单已被替代，请重新查看当前单据后操作。',409)
                    if type(expected_version) is not int or row['version']!=expected_version:
                        raise ServiceError('VERSION_CONFLICT','单据已变化，请刷新并核对最新内容。',409)
                    if role=='EMPLOYEE':
                        rules=self._actions(conn,row)
                        if action not in rules: raise ServiceError('INVALID_ACTION','不支持此员工操作。',422)
                        if not rules[action]['allowed']: raise ServiceError('ACTION_NOT_ALLOWED',rules[action]['reason'],409)
                    elif action not in {'start','complete','return'}:
                        raise ServiceError('INVALID_ACTION','不支持此模拟审批操作。',422)
                    elif (action=='start' and row['status']!='S002') or (action=='complete' and row['status']!='S003') or (action=='return' and row['status'] not in {'S002','S003'}):
                        raise ServiceError('ACTION_NOT_ALLOWED','当前状态不允许此模拟审批操作。',409)
                    if action in {'change','resubmit'}: payload=validate_payload(payload,applicant_id)
                    elif payload is not None: raise ServiceError('INVALID_REQUEST','此操作不接受申请内容。',422)
                    result_id=self._mutate(conn,row,action,payload,reason,role)
                    result=dict(clientRequestId=request_id,action=action,document=self._dto(conn,self._row(conn,result_id)),demoOnly=True)
                except ServiceError as exc:
                    conn.execute('ROLLBACK TO lifecycle_action'); error=exc
                    result=dict(code=exc.code,message=exc.text,httpStatus=exc.status,issues=getattr(exc,'issues',[]),clientRequestId=request_id,action=action,demoOnly=True)
                conn.execute('RELEASE lifecycle_action')
                conn.execute('INSERT INTO lifecycle_receipts VALUES(?,?,?,?,?,?)',
                             (request_id,applicant_id,fingerprint,business_time()['datetime'],'FAILED' if error else 'SUCCEEDED',encode(result)))
        if error: raise error
        return result

    @staticmethod
    def _restore_error(result):
        error=ServiceError(result['code'],result['message'],result['httpStatus'])
        if result.get('issues'): error.issues=result['issues']
        return error

    def _mutate(self,conn,row,action,payload,reason,role):
        now=business_time()['datetime']; target=row['id']
        if action=='change':
            target='MOCK-APP-'+uuid4().hex
            number='DEMO-BG-'+business_time()['date'].replace('-','')+'-'+uuid4().hex[:12].upper()
            serialized=encode(payload)
            conn.execute('INSERT INTO applications(id,application_no,applicant_id,created_at,payload_json,payload_hash) VALUES(?,?,?,?,?,?)',
                         (target,number,row['applicant_id'],now,serialized,hashlib.sha256(serialized.encode()).hexdigest()))
            initialize_document(conn,conn.execute('SELECT * FROM applications WHERE id=?',(target,)).fetchone(),predecessor=row,reason=reason)
            conn.execute("UPDATE lifecycle_documents SET tflag='YBG',version=version+1 WHERE application_id=?",(row['id'],))
            return target
        state={'withdraw':'S005','void':'S100','resubmit':'S002','start':'S003','complete':'S004','return':'S005'}[action]
        round_number=row['submission_round']+(action=='resubmit')
        history=json.loads(row['history_json'])+[event(action,row['status'],state,round_number,role,reason)]
        conn.execute('UPDATE lifecycle_documents SET status=?,version=version+1,submission_round=?,history_json=? WHERE application_id=?',
                     (state,round_number,encode(history),target))
        if action=='resubmit':
            serialized=encode(payload)
            conn.execute('UPDATE applications SET payload_json=?,payload_hash=? WHERE id=?',(serialized,hashlib.sha256(serialized.encode()).hexdigest(),target))
            conn.execute('UPDATE lifecycle_documents SET submitted_at=? WHERE application_id=?',(now,target))
            conn.execute('INSERT INTO lifecycle_snapshots VALUES(?,?,?,?)',(target,round_number,serialized,now))
        if action=='complete':
            if row['predecessor_id']:
                if row['effective_id']!=row['predecessor_id']: raise ServiceError('INVALID_PREDECESSOR','变更前序已失效，不能完成审批。',409)
                conn.execute('UPDATE lifecycle_documents SET replacement_id=?,version=version+1 WHERE application_id=?',(target,row['predecessor_id']))
            conn.execute('UPDATE lifecycle_roots SET effective_id=? WHERE root_id=?',(target,row['root_id']))
        if action=='void':
            if row['status']=='S005':
                conn.execute("UPDATE lifecycle_documents SET tflag='D',version=version+1 WHERE application_id=?",(row['predecessor_id'],))
            else: conn.execute('UPDATE lifecycle_roots SET effective_id=NULL WHERE root_id=?',(row['root_id'],))
        return target
