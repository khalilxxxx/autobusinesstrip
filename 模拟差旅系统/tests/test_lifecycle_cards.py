"""卡片绑定每轮对话；语义操作须确认，不能绕过版本检查。"""
from test_lifecycle import create, complete, operation, approval, payload
from test_lifecycle_assistant import env
from test_lifecycle_workflow import turn


def test_each_query_retains_its_own_cards_and_resolves_current_version(env):
    app,c,cid,url=env; service=app.state.lifecycle; store=app.state.assistant_manager.store
    a=complete(service,create(service)); b=create(service,payload(start='2026-02-01',end='2026-02-03'))
    groups=[]
    for n,doc in enumerate((a,b)):
        tid,_=store.start_turn(cid,'查询单据',f'cards-{n}')
        turn(env,'查询单据',dict(intent='QUERY',filter={'keyword':doc['applicationNo']}))
        store.finish(tid,'已找到相关单据','succeeded',state={})
        groups.append(tid)
    result=c.get(url).json()['cardGroups']
    assert [x['turnId'] for x in result]==groups
    assert [[d['applicationId'] for d in x['documents']] for x in result]==[[a['applicationId']],[b['applicationId']]]
    assert store.conversation(cid)['messages'][1]['turnId']==groups[0]
    a1=operation(service,a,'change',data=payload(start='2026-03-01',end='2026-03-03'))
    complete(service,a1)
    latest=c.get(url).json()['cardGroups'][0]['documents']
    assert latest[0]['applicationId']==a1['applicationId']
    assert latest[0]['request']['trips'][0]['dateFrom']=='2026-03-01'


def test_semantic_withdraw_requires_second_confirmation_and_rejects_stale_version(env):
    app,c,cid,url=env; a=create(app.state.lifecycle)
    first=turn(env,'撤回这张',dict(intent='WITHDRAW',reference=a['applicationId']))
    assert app.state.lifecycle.document(a['applicationId'])['status']=='S002'
    assert '确认撤回' in first['reply']
    pending=c.get(url).json()['pendingAction']
    assert pending['action']=='withdraw' and pending['targetVersion']==1
    approval(app.state.lifecycle,a,'start')
    result=turn(env,'确认撤回',dict(intent='HELP'))
    assert '已变化' in result['reply']
    assert app.state.lifecycle.document(a['applicationId'])['status']=='S003'


def test_semantic_void_reason_is_retained_but_not_required(env):
    app,c,cid,url=env; a=complete(app.state.lifecycle,create(app.state.lifecycle))
    first=turn(env,'作废这张，原因：客户取消会议，不需要出差',dict(intent='VOID',reference=a['applicationId']))
    assert '确认作废' in first['reply']
    assert app.state.lifecycle.document(a['applicationId'])['status']=='S004'
    assert c.get(url).json()['pendingAction']['reason']=='客户取消会议，不需要出差'
    result=turn(env,'确认作废',dict(intent='CONFIRM'))
    assert 'S100' in result['reply']
    assert app.state.lifecycle.document(a['applicationId'])['history'][-1]['reason']=='客户取消会议，不需要出差'
    b=complete(app.state.lifecycle,create(app.state.lifecycle))
    turn(env,'作废这张',dict(intent='VOID',reference=b['applicationId']))
    turn(env,'确认作废',dict(intent='HELP'))
    assert app.state.lifecycle.document(b['applicationId'])['status']=='S100'


def test_confirmation_cannot_switch_action_or_target_and_cancellation_clears_it(env):
    app,c,cid,url=env; a=create(app.state.lifecycle); b=create(app.state.lifecycle)
    turn(env,'撤回这张',dict(intent='WITHDRAW',reference=a['applicationId']))
    for query in ('确认作废','确认撤回 '+b['applicationNo'],'不要确认撤回'):
        turn(env,query,dict(intent='HELP'))
        assert app.state.lifecycle.document(a['applicationId'])['status']=='S002'
    turn(env,'取消撤回',dict(intent='HELP'))
    assert c.get(url).json()['pendingAction'] is None
    turn(env,'确认撤回',dict(intent='HELP'))
    assert app.state.lifecycle.document(a['applicationId'])['status']=='S002'


def test_card_action_proposal_is_read_only_and_semantic_confirmation_uses_reason(env):
    app,c,cid,url=env; a=complete(app.state.lifecycle,create(app.state.lifecycle))
    r=c.post(url+'/propose-action',json=dict(reference=a['applicationId'],action='void'))
    assert r.status_code==200
    assert r.json()['pendingAction']['targetDocument']['applicationId']==a['applicationId']
    assert app.state.lifecycle.document(a['applicationId'])['status']=='S004'
    turn(env,'确认作废 '+a['applicationNo']+'，原因：行程取消',dict(intent='HELP'))
    final=app.state.lifecycle.document(a['applicationId'])
    assert final['status']=='S100' and final['history'][-1]['reason']=='行程取消'
    assert c.get(url).json()['pendingAction'] is None
