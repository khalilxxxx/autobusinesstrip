"""助手真实业务验收：丢失草稿、错误对象、陈旧确认及重复办理都必须失败。"""
from copy import deepcopy
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from mock_travel.app import create_app
from test_lifecycle import payload, create, complete, operation, approval

@pytest.fixture
def env(tmp_path):
    app=create_app(tmp_path/'assistant.db')
    client=TestClient(app)
    cid=client.post('/assistant/api/conversations',json={}).json()['id']
    return app,client,cid,'/assistant/api/conversations/'+cid+'/lifecycle'

def prepared(env, mode='change', doc=None):
    app,c,cid,url=env
    doc=doc or complete(app.state.lifecycle,create(app.state.lifecycle))
    r=c.post(url+'/prepare',json={'reference':doc['applicationId'],'mode':mode})
    assert r.status_code==200, r.text
    return doc,r.json()['draft']

def confirm(d, rid='submit-1'):
    return dict(draftId=d['id'],revision=d['revision'],fingerprint=d['fingerprint'],clientRequestId=rid)

def test_query_detail_withdraw_preserve_create_state_bytes(env):
    app,c,cid,url=env; store=app.state.assistant_manager.store
    with store.connection(write=True) as conn:
        conn.execute('UPDATE assistant_conversations SET state_json=? WHERE id=?',('{"draft":{"remark":"未完成的新申请"}, "flow_state":"COLLECTING"}',cid))
    before=store.private_conversation(cid)['state_json']; a=create(app.state.lifecycle)
    r=c.post(url+'/query',json={})
    assert r.status_code==200, '生命周期查询尚未接入助手'
    assert r.json()['documents'][0]['applicationId']==a['applicationId']
    assert c.get(url).status_code==200
    r=c.post(url+'/action',json=dict(reference=a['applicationId'],action='withdraw',clientRequestId='withdraw',expectedVersion=a['version']))
    assert r.status_code==200 and r.json()['lastReceipt']['result']['document']['status']=='S005'
    assert store.private_conversation(cid)['state_json']==before

def test_save_inherits_company_department_and_rejects_old_confirmation(env):
    app,c,cid,url=env; data=payload(); data.update(departmentId='DEMO_DEPT_002',payerCompanyId='DEMO_COMPANY_002')
    a,d=prepared(env,doc=complete(app.state.lifecycle,create(app.state.lifecycle,data)))
    changed=deepcopy(d['payload']); changed['remark']='调整客户会议'
    r=c.put(url+'/draft',json=dict(draftId=d['id'],revision=d['revision'],payload=changed)); assert r.status_code==200
    new=r.json()['draft']; assert new['revision']==2 and new['fingerprint']!=d['fingerprint']
    assert new['payload']['departmentId']=='DEMO_DEPT_002' and new['payload']['payerCompanyId']=='DEMO_COMPANY_002'
    assert c.post(url+'/submit',json=confirm(d)).status_code==409
    r=c.post(url+'/submit',json=confirm(new)); assert r.status_code==200
    assert r.json()['lastReceipt']['result']['document']['request']['payerCompanyId']=='DEMO_COMPANY_002'
    assert c.post(url+'/submit',json=confirm(new)).json()['lastReceipt']==r.json()['lastReceipt']
    assert app.state.lifecycle.list_documents({})['total']==2

def test_s005_resubmit_same_number_restart_and_cancel_local_only(env):
    app,c,cid,url=env; a=operation(app.state.lifecycle,create(app.state.lifecycle),'withdraw')
    a,d=prepared(env,'resubmit',a)
    restarted=TestClient(create_app(app.state.store.path))
    assert restarted.get(url).json()['draft']==d
    result=restarted.post(url+'/submit',json=confirm(d)).json()['lastReceipt']['result']['document']
    assert result['applicationNo']==a['applicationNo'] and result['status']=='S002' and result['submissionRound']==2
    a=operation(app.state.lifecycle,result,'withdraw'); prepared(env,'resubmit',a)
    assert c.delete(url+'/draft').json()['draft'] is None
    assert app.state.lifecycle.document(a['applicationId'])['status']=='S005'

def test_prepare_does_not_overwrite_and_query_does_not_change_draft(env):
    app,c,cid,url=env; a,d=prepared(env); b=complete(app.state.lifecycle,create(app.state.lifecycle))
    assert c.post(url+'/prepare',json=dict(reference=b['applicationId'],mode='change')).status_code==409
    assert c.post(url+'/query',json={}).json()['draft']==d


def test_draft_exposes_its_target_document_independent_of_selection(env):
    app,c,cid,url=env; a,d=prepared(env); b=complete(app.state.lifecycle,create(app.state.lifecycle))
    assert c.post(url+'/prepare',json=dict(reference=b['applicationId'],mode='change')).status_code==409
    assert app.state.lifecycle_assistant.detail(cid,b['applicationId'])['selectedDocument']['applicationId']==b['applicationId']
    view=c.get(url).json()
    assert view['selectedDocument']['applicationId']==b['applicationId']
    assert view['draft']['targetId']==a['applicationId']
    assert view['draft']['targetDocument']['applicationId']==a['applicationId']

def test_employee_cannot_approve_or_withdraw_s003(env):
    app,c,cid,url=env; a=approval(app.state.lifecycle,create(app.state.lifecycle),'start')
    for action in ['complete','return','withdraw']:
        r=c.post(url+'/action',json=dict(reference=a['applicationId'],action=action,expectedVersion=a['version'],clientRequestId=str(uuid4())))
        assert r.status_code in (409,422)
    assert app.state.lifecycle.document(a['applicationId'])['status']=='S003'

def test_stale_reference_does_not_void_current_and_identity_is_rejected(env):
    app,c,cid,url=env; old=complete(app.state.lifecycle,create(app.state.lifecycle)); new=complete(app.state.lifecycle,operation(app.state.lifecycle,old,'change',payload()))
    r=c.post(url+'/action',json=dict(reference=old['applicationId'],action='void',expectedVersion=new['version'],clientRequestId='old'))
    assert r.status_code==409
    assert app.state.lifecycle.document(new['applicationId'])['status']=='S004'
    assert c.post(url+'/query',json={'applicantId':'other'}).status_code==422


def test_unchanged_dify_state_sync_preserves_create_state_bytes(env):
    app,c,cid,url=env; store=app.state.assistant_manager.store
    raw='{ "draft": null, "flow_state": "IDLE" }'
    with store.connection(write=True) as conn: conn.execute('UPDATE assistant_conversations SET state_json=? WHERE id=?',(raw,cid))
    turn_id,_=store.start_turn(cid,'查询申请','sync-query')
    import json
    store.finish(turn_id,'查询完成','succeeded',state=json.loads(raw))
    assert store.private_conversation(cid)['state_json']==raw


def test_existing_foreign_business_request_cannot_be_claimed_as_own_success(env):
    app,c,cid,url=env;service=app.state.lifecycle
    a=create(service);b=create(service)
    operation(service,b,'withdraw',request_id='already-used')
    response=c.post(url+'/action',json=dict(reference=a['applicationId'],action='withdraw',clientRequestId='already-used',expectedVersion=a['version']))
    assert response.status_code==409
    assert service.document(a['applicationId'])['status']=='S002'
    assert c.get(url).json()['lastReceipt'] is None
