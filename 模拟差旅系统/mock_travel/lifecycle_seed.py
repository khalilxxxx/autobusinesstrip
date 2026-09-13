"""一次事务生成明确状态的演示样例；重复运行不删除或重置单据。"""
from datetime import date, timedelta
import hashlib
import json
from .catalog import business_time
from .lifecycle import initialize_document
from .store import encode


def seed_documents(service):
    key='lifecycle-seed-v1'; now=business_time(); today=date.fromisoformat(now['date'])
    with service.store.connection(write=True) as conn:
        existing=conn.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        if existing: return {**json.loads(existing[0]),'created':0}
        ids=[]
        def make(name,offset,duration=4):
            identifier='MOCK-SEED-'+name; start=(today+timedelta(days=offset)).isoformat(); end=(today+timedelta(days=offset+duration)).isoformat()
            payload=dict(applicantId='DEMO_EMP_001',departmentId='DEMO_DEPT_001',payerCompanyId='DEMO_COMPANY_001',
                         remark='演示样例：'+name,dqydbg=None,trips=[
                             dict(dateFrom=start,dateTo=start,cityFrom='330100',cityTo='DEMO_SHANGHAI',tool='火车-二等座'),
                             dict(dateFrom=end,dateTo=end,cityFrom='DEMO_SHANGHAI',cityTo='330100',tool='火车-二等座')])
            serialized=encode(payload)
            conn.execute('INSERT INTO applications(id,application_no,applicant_id,created_at,payload_json,payload_hash) VALUES(?,?,?,?,?,?)',
                         (identifier,'DEMO-SEED-'+name,'DEMO_EMP_001',now['datetime'],serialized,hashlib.sha256(serialized.encode()).hexdigest()))
            initialize_document(conn,conn.execute('SELECT * FROM applications WHERE id=?',(identifier,)).fetchone())
            ids.append(identifier); return identifier
        def advance(identifier,action,payload=None):
            return service._mutate(conn,service._row(conn,identifier),action,payload,None,'APPROVER' if action in {'start','complete','return'} else 'EMPLOYEE')
        def approve(identifier):
            advance(identifier,'start');advance(identifier,'complete');return identifier
        approve(make('历史差旅',-40))
        approve(make('当前停留',-2))
        approve(make('未来差旅',15))
        make('待审批申请',8)
        advance(make('审批中申请',9),'start')
        advance(make('退回普通申请',10),'return')
        parent=approve(make('变更前序',11))
        changed=json.loads(service._row(conn,parent)['payload_json']); changed['remark']='演示样例：退回变更'; changed['departmentId']='DEMO_DEPT_002'
        child=advance(parent,'change',changed); ids.append(child);advance(child,'return')
        reimbursed=approve(make('已转报销',-15))
        conn.execute("UPDATE lifecycle_documents SET tflag='YBX',version=version+1 WHERE application_id=?",(reimbursed,))
        result=dict(applicationIds=ids,created=len(ids),demoOnly=True)
        conn.execute('INSERT INTO settings(key,value) VALUES(?,?)',(key,encode(result)))
        return result
