"""自然语言边界调用真实服务，命令不能授权身份、审批或含糊写入。"""
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from mock_travel.app import create_app
from test_lifecycle import payload,create,complete,approval,operation
from test_lifecycle_assistant import env, prepared, confirm


def turn(env,query,command,rid=None):
    app,c,cid,url=env
    user=app.state.assistant_manager.store.private_conversation(cid)['dify_user']
    if command.get('intent')=='CONFIRM' and 'confirmation' not in command:
        d=c.get(url).json()['draft']
        if d: command={**command,'confirmation':{k:v for k,v in confirm(d).items() if k!='clientRequestId'}}
    r=c.post('/workflow/v1/lifecycle/turn',json=dict(user=user,query=query,command=command,clientRequestId=rid or str(uuid4())))
    assert r.status_code==200,r.text
    return r.json()


def test_initial_query_context_and_second_result(env):
    app,c,cid,url=env
    a=create(app.state.lifecycle); b=create(app.state.lifecycle)
    user=app.state.assistant_manager.store.private_conversation(cid)['dify_user']
    r=c.get('/workflow/v1/lifecycle/context',params={'user':user})
    assert r.status_code==200,'工作流生命周期上下文尚未接入'
    assert r.json()['creationEditing'] is False
    assert turn(env,'查我的申请',{'intent':'QUERY'})['handled']
    reply=turn(env,'查看第二张',{'intent':'DETAIL','resultIndex':2})['reply']
    assert a['applicationNo'] in reply and b['applicationNo'] not in reply
    assert app.state.assistant_manager.store.private_conversation(cid)['state_json']=='{}'

@pytest.mark.parametrize('query,intent',[('不要撤回','WITHDRAW'),('能作废吗','VOID'),('撤销刚才的修改','VOID'),('帮我审批通过','CONFIRM')])
def test_negative_inquiry_and_cancel_never_write(env,query,intent):
    app,c,cid,url=env; a=create(app.state.lifecycle)
    turn(env,query,dict(intent=intent,reference=a['applicationId']))
    assert app.state.lifecycle.document(a['applicationId'])['status']=='S002'
    with app.state.store.connection() as conn: assert conn.execute('SELECT count(*) FROM lifecycle_receipts').fetchone()[0]==0


def test_ambiguous_withdraw_requires_unique_object_and_s003_guidance(env):
    app,c,cid,url=env; a=create(app.state.lifecycle); create(app.state.lifecycle)
    turn(env,'查申请',{'intent':'QUERY'})
    reply=turn(env,'撤回',{'intent':'WITHDRAW'})['reply']; assert '单号' in reply
    a=approval(app.state.lifecycle,a,'start')
    reply=turn(env,'撤回'+a['applicationNo'],dict(intent='WITHDRAW',reference=a['applicationNo']))['reply']
    assert '模拟控制台' in reply and '退回' in reply
    assert app.state.lifecycle.document(a['applicationId'])['status']=='S003'


def test_patch_inherits_fields_validates_indices_and_same_day_return(env):
    app,c,cid,url=env; data=payload(); data.update(departmentId='DEMO_DEPT_002',payerCompanyId='DEMO_COMPANY_002')
    a=complete(app.state.lifecycle,create(app.state.lifecycle,data))
    turn(env,'变更'+a['applicationNo'],dict(intent='CHANGE',reference=a['applicationNo']))
    before=c.get(url).json()['draft']
    turn(env,'改第二段出发日为2026-01-05',dict(intent='EDIT',patch={'tripUpdates':[{'index':2,'dateFrom':'2026-01-05'}]}))
    d=c.get(url).json()['draft']; assert d['payload']['trips'][1]['dateTo']=='2026-01-05'
    assert d['payload']['payerCompanyId']=='DEMO_COMPANY_002' and d['revision']==2
    reply=turn(env,'改第零段',dict(intent='EDIT',patch={'tripUpdates':[{'index':0,'tool':'飞机-经济舱'}]}))['reply']
    assert c.get(url).json()['draft']==d and reply
    turn(env,'改事由',dict(intent='EDIT',patch={'remark':'项目讨论'}))
    assert c.get(url).json()['draft']['payload']['remark']=='项目讨论'


def test_dual_drafts_ambiguous_confirm_and_query_interleaving(env):
    app,c,cid,url=env; a,d=prepared(env)
    store=app.state.assistant_manager.store
    with store.connection(write=True) as conn:
        conn.execute('UPDATE assistant_conversations SET state_json=? WHERE id=?',('{"draft":{"draft_id":"new"},"flow_state":"READY_TO_CONFIRM"}',cid))
    reply=turn(env,'确认提交',{'intent':'CONFIRM'})['reply']; assert '新申请' in reply and '变更' in reply
    assert app.state.lifecycle.list_documents({})['total']==1
    turn(env,'查询申请',{'intent':'QUERY'})
    command={'intent':'CONFIRM','confirmation':{k:v for k,v in confirm(d).items() if k!='clientRequestId'}}
    reply=turn(env,'确认提交变更',command,'confirmed')
    assert reply['handled'] and '回执' in reply['reply']
    again=turn(env,'确认提交变更',command,'confirmed')
    assert again==reply and app.state.lifecycle.list_documents({})['total']==2

@pytest.mark.parametrize('command',[{'intent':'APPROVE'},{'intent':'QUERY','applicantId':'other'}, {'intent':'EDIT','patch':{'applicantId':'other'}}, {'intent':'WITHDRAW','reference':'x','expectedVersion':1}])
def test_command_allowlist_rejects_forged_fields(env,command):
    reply=turn(env,'操作',command)
    assert reply['handled'] and '无法' in reply['reply']


def test_create_falls_through_and_preview_user_is_independent(env):
    app,c,cid,url=env
    assert turn(env,'我要新建出差申请',{'intent':'CREATE_FLOW'})=={'handled':False,'reply':''}
    r=c.get('/workflow/v1/lifecycle/context',params={'user':'dify-preview-a'})
    assert r.status_code==200 and r.json()['creationEditing'] is False
    assert len(app.state.assistant_manager.store.conversations()['items'])==2


def test_context_confirmation_stale_after_edit_is_rejected(env):
    app,c,cid,url=env; a,d=prepared(env)
    old={k:v for k,v in confirm(d).items() if k!='clientRequestId'}
    turn(env,'事由改为复盘会议',dict(intent='EDIT',patch={'remark':'复盘会议'}))
    reply=turn(env,'确认提交变更',dict(intent='CONFIRM',confirmation=old))['reply']
    assert '已变化' in reply and app.state.lifecycle.list_documents({})['total']==1


def test_explicit_lifecycle_confirm_without_draft_never_submits_create(env):
    reply=turn(env,'确认提交变更',{'intent':'CONFIRM'})
    assert reply['handled'] is True


def test_cross_day_clarification_and_bad_catalog_preserve_draft(env):
    app,c,cid,url=env; data=payload();data['trips'][1]['dateTo']='2026-01-04'
    a,d=prepared(env,doc=complete(app.state.lifecycle,create(app.state.lifecycle,data)))
    reply=turn(env,'返程延到5日',{'intent':'EDIT','patch':{'tripUpdates':[{'index':2,'dateFrom':'2026-01-05'}]}})['reply']
    assert '到达日' in reply and c.get(url).json()['draft']==d
    for patch in [{'tripUpdates':[{'index':1,'tool':'宇宙飞船'}]}, {'tripUpdates':[{'index':1,'cityTo':'不存在'}]}, {'departmentId':'other'},{'removeTripIndices':[True]}]:
        turn(env,'修改行程',{'intent':'EDIT','patch':patch})
        assert c.get(url).json()['draft']==d


def test_add_remove_trips_and_travel_type(env):
    app,c,cid,url=env;a,d=prepared(env)
    new=payload('DEMO_BEIJING',start='2026-02-01',end='2026-02-03')['trips']
    turn(env,'替换两段行程并改为短期异地办公',{'intent':'EDIT','patch':{'removeTripIndices':[1,2],'addTrips':new,'dqydbg':'Y'}})
    latest=c.get(url).json()['draft'];assert latest['payload']['trips']==new and latest['payload']['dqydbg']=='Y'
    turn(env,'改为普通差旅',{'intent':'EDIT','patch':{'dqydbg':None}})
    assert c.get(url).json()['draft']['payload']['dqydbg'] is None


def test_unknown_submission_preserves_request_and_recovers_real_receipt(env,monkeypatch):
    app,c,cid,url=env;a,d=prepared(env); service=app.state.lifecycle
    real=service.receipt
    def unavailable(rid,*args,**kwargs):
        from mock_travel.store import ServiceError
        try: receipt=real(rid,*args,**kwargs)
        except ServiceError: raise
        raise OSError('response lost after commit')
    monkeypatch.setattr(service,'receipt',unavailable)
    result=c.post(url+'/submit',json=confirm(d,'uncertain')).json()
    assert result['draft']['requestId']=='uncertain' and result['lastReceipt']['status']=='UNKNOWN'
    assert app.state.lifecycle.list_documents({})['total']==2
    assert c.delete(url+'/draft').status_code==409
    monkeypatch.setattr(service,'receipt',real)
    result=turn(env,'确认提交变更',dict(intent='CONFIRM'))
    assert 'uncertain' in result['reply'] and '回执' in result['reply']
    assert c.get(url).json()['draft'] is None and service.list_documents({})['total']==2


def test_unknown_withdraw_after_commit_replays_exact_original_operation(env,monkeypatch):
    app,c,cid,url=env; service=app.state.lifecycle;a=create(service);real=service.receipt
    def unavailable(rid,*args,**kwargs):
        result=real(rid,*args,**kwargs)
        raise OSError('response lost')
    monkeypatch.setattr(service,'receipt',unavailable)
    command=dict(intent='WITHDRAW',reference=a['applicationId'])
    first=turn(env,'撤回这张',command,'unknown-withdraw')
    assert '尚未确认' in first['reply']
    monkeypatch.setattr(service,'receipt',real)
    second=turn(env,'撤回这张',command,'unknown-withdraw')
    assert '真实业务回执' in second['reply']
    assert service.document(a['applicationId'])['status']=='S005'


def test_gateway_exposes_only_lifecycle_context_and_turn(env):
    import httpx
    from mock_travel.gateway import create_gateway
    app,c,cid,url=env
    user=app.state.assistant_manager.store.private_conversation(cid)['dify_user']
    gateway=TestClient(create_gateway(token='test-only',transport=httpx.ASGITransport(app=app)))
    headers={'Authorization':'Bearer test-only'}
    assert gateway.get('/workflow/v1/lifecycle/context',params={'user':user},headers=headers).status_code==200
    result=gateway.post('/workflow/v1/lifecycle/turn',json=dict(user=user,query='查询',command={'intent':'QUERY'},clientRequestId='gateway-query'),headers=headers)
    assert result.status_code==200 and result.json()['handled'] is True
    for route in ['/mock/v1/lifecycle/seed','/mock/v1/lifecycle/documents/x/approval','/assistant/api/conversations']:
        assert gateway.post(route,json={},headers=headers).status_code==404


def test_unknown_action_recovers_original_id_on_new_dify_run(env,monkeypatch):
    app,c,cid,url=env; service=app.state.lifecycle;a=create(service);real=service.receipt
    def unavailable(rid,*args,**kwargs):
        real(rid,*args,**kwargs)
        raise OSError('response lost')
    monkeypatch.setattr(service,'receipt',unavailable)
    turn(env,'撤回这张',dict(intent='WITHDRAW',reference=a['applicationId']),'lost-original')
    monkeypatch.setattr(service,'receipt',real)
    reply=turn(env,'撤回这张',dict(intent='WITHDRAW',reference=a['applicationId']),'new-dify-run')['reply']
    assert 'lost-original' in reply and '真实业务回执' in reply
    with app.state.store.connection() as conn:
        assert conn.execute('SELECT count(*) FROM lifecycle_receipts').fetchone()[0]==1


def test_confirm_with_edits_only_saves_new_revision(env):
    app,c,cid,url=env; a,d=prepared(env)
    reply=turn(env,'事由改为拜访客户，确认提交变更',{'intent':'CONFIRM','patch':{'remark':'拜访客户'}})
    latest=c.get(url).json()['draft']
    assert latest is not None and latest['revision']==2 and latest['payload']['remark']=='拜访客户'
    assert app.state.lifecycle.list_documents({})['total']==1


def test_preparing_s003_explains_normal_approval_return(env):
    app,c,cid,url=env;a=approval(app.state.lifecycle,create(app.state.lifecycle),'start')
    reply=turn(env,'我要修改这张申请',dict(intent='CHANGE',reference=a['applicationId']))['reply']
    assert '模拟控制台' in reply and '退回' in reply


def test_replayed_success_projects_current_visible_document(env):
    app,c,cid,url=env;service=app.state.lifecycle;a=create(service)
    command=dict(intent='WITHDRAW',reference=a['applicationId'])
    turn(env,'撤回这张',command,'withdraw-replay')
    a=service.document(a['applicationId']); a=complete(service,operation(service,a,'resubmit',payload()))
    newer=complete(service,operation(service,a,'change',payload('DEMO_BEIJING')))
    reply=turn(env,'撤回这张',command,'withdraw-replay')['reply']
    assert '以下为当前单据' in reply and newer['applicationNo'] in reply
    assert a['applicationNo'] not in reply


def test_dify_preview_creation_flag_prevents_ambiguous_dual_draft_confirm(env):
    app,c,cid,url=env;service=app.state.lifecycle;a=complete(service,create(service));user='preview-with-create'
    context=c.get('/workflow/v1/lifecycle/context',params={'user':user,'creationEditing':'true'}).json()
    assert context['creationEditing'] is True
    response=c.post('/workflow/v1/lifecycle/turn',json=dict(user=user,query='变更这张',command=dict(intent='CHANGE',reference=a['applicationId']),clientRequestId='preview-prepare'))
    assert response.status_code==200
    context=c.get('/workflow/v1/lifecycle/context',params={'user':user,'creationEditing':'true'}).json();d=context['draft']
    command={'intent':'CONFIRM','confirmation':{k:v for k,v in confirm(d).items() if k!='clientRequestId'}}
    result=c.post('/workflow/v1/lifecycle/turn',json=dict(user=user,query='确认提交',command=command,clientRequestId='preview-confirm')).json()
    assert '新申请' in result['reply'] and '变更' in result['reply']
    assert service.list_documents({})['total']==1
