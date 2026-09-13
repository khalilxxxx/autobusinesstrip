from test_lifecycle import create, complete, operation, payload
from test_lifecycle_assistant import env
from test_lifecycle_workflow import turn


def test_query_limits_visible_references_and_passes_raw_details_to_llm(env):
    app,c,cid,url=env; service=app.state.lifecycle
    for _ in range(5): complete(service,create(service))
    result=turn(env,'查一下2026年1月1日我在哪里出差',dict(intent='QUERY',filter={'dateFrom':'2026-01-01','dateTo':'2026-01-01'}))
    state=c.get(url).json()
    assert len(state['documents'])==3 and state['querySummary']['total']==5
    assert state['cardGroups'][-1]['kind']=='query'
    context=result['answerContext']
    assert context['total']==5 and context['shown']==3
    assert len(context['documents'])==3 and context['cityNames']['DEMO_SHANGHAI']=='上海'
    assert context['documents'][0]['request']['trips'][0]['dateFrom']=='2025-12-29'
    assert all('locations' not in d and 'stay' not in d for d in context['documents'])
    assert '5' in result['reply'] and '3' in result['reply']
    assert all(d['applicationNo'] not in result['reply'] for d in state['documents'])
    result=turn(env,'查看第四张',dict(intent='DETAIL',resultIndex=4))
    assert '有效' in result['reply'] and '序号' in result['reply']


def test_change_first_turn_applies_patch_and_returns_draft_card_without_detail_echo(env):
    app,c,cid,url=env; service=app.state.lifecycle; store=app.state.assistant_manager.store
    doc=complete(service,create(service))
    tid,_=store.start_turn(cid,'改成去北京','focused-change')
    result=turn(env,'我要变更一下行程，改成去北京',dict(intent='CHANGE',reference=doc['applicationId'],patch={'tripUpdates':[{'index':1,'cityTo':'DEMO_BEIJING'},{'index':2,'cityFrom':'DEMO_BEIJING'}]}))
    store.finish(tid,result['reply'],'succeeded',state={})
    view=c.get(url).json(); group=view['cardGroups'][-1]
    assert group['kind']=='draft' and group['draft']['payload']['trips'][0]['cityTo']=='DEMO_BEIJING'
    assert group['draft']['targetDocument']['applicationId']==doc['applicationId']
    assert '北京' in result['reply'] and '草稿' in result['reply']
    assert doc['applicationNo'] not in result['reply'] and '第1段' not in result['reply'] and '版本' not in result['reply']
    assert service.document(doc['applicationId'])['request']['trips'][0]['cityTo']=='DEMO_SHANGHAI'
    user=store.private_conversation(cid)['dify_user']
    context=c.get('/workflow/v1/lifecycle/context',params={'user':user}).json()
    assert context['selectedDocument']['request']['trips']==doc['request']['trips']


def test_explicit_semantic_void_executes_without_proposal_but_denial_never_does(env):
    app,c,cid,url=env; service=app.state.lifecycle
    doc=complete(service,create(service))
    turn(env,'查看'+doc['applicationNo'],dict(intent='DETAIL',reference=doc['applicationId']))
    denied=turn(env,'作废这张，原因：客户取消会议；先不要作废',dict(intent='VOID',reference=doc['applicationId']))
    assert service.document(doc['applicationId'])['status']=='S004' and '未执行' in denied['reply']
    result=turn(env,'作废这张，原因：客户取消会议，不需要出差',dict(intent='VOID',reference=doc['applicationId']))
    after=service.document(doc['applicationId'])
    assert after['status']=='S100' and after['history'][-1]['reason']=='客户取消会议，不需要出差'
    assert c.get(url).json()['pendingAction'] is None
    assert '已作废' in result['reply'] and '第1段' not in result['reply'] and doc['applicationNo'] not in result['reply']


def test_ui_card_remembers_its_interaction_turn_after_a_later_cardless_reply(env):
    app,c,cid,url=env; service=app.state.lifecycle; store=app.state.assistant_manager.store
    doc=complete(service,create(service))
    first,_=store.start_turn(cid,'查看这张','query-owner')
    result=turn(env,'查看这张',dict(intent='DETAIL',reference=doc['applicationId']))
    store.finish(first,result['reply'],'succeeded',state={})
    c.post(url+'/prepare',json=dict(reference=doc['applicationId'],mode='change')).raise_for_status()
    ui_group=c.get(url).json()['cardGroups'][-1]
    assert ui_group['turnId'] is None and ui_group['interactionTurnId']==first
    later,_=store.start_turn(cid,'谢谢','cardless-followup')
    store.finish(later,'不客气','succeeded',state={})
    reread=c.get(url).json()['cardGroups'][-1]
    assert reread['interactionTurnId']==first and reread['interactionTurnId']!=later


def test_draft_card_keeps_each_turn_snapshot_but_hides_replaced_targets(env):
    app,c,cid,url=env; service=app.state.lifecycle; store=app.state.assistant_manager.store
    doc=complete(service,create(service))
    first,_=store.start_turn(cid,'变更这张','snapshot-before')
    result=turn(env,'变更这张',dict(intent='CHANGE',reference=doc['applicationId']))
    store.finish(first,result['reply'],'succeeded',state={})
    second,_=store.start_turn(cid,'事由改为会议复盘','snapshot-after')
    result=turn(env,'事由改为会议复盘',dict(intent='EDIT',patch={'remark':'会议复盘'}))
    store.finish(second,result['reply'],'succeeded',state={})
    groups=c.get(url).json()['cardGroups']
    assert groups[0]['draft']['payload']['remark']==doc['request']['remark']
    assert groups[1]['draft']['payload']['remark']=='会议复盘'
    latest=complete(service,operation(service,doc,'change',data=payload(start='2026-03-01',end='2026-03-03')))
    groups=c.get(url).json()['cardGroups']
    assert all('draft' not in group for group in groups)
    assert all(group['documents'][0]['applicationId']==latest['applicationId'] for group in groups)


def test_cached_query_replay_never_returns_replaced_raw_details(env):
    app,c,cid,url=env; service=app.state.lifecycle
    doc=complete(service,create(service))
    query='查这张申请'; command=dict(intent='QUERY',filter={'keyword':doc['applicationNo']})
    first=turn(env,query,command,'focused-cached-query')
    assert first['answerContext']['documents'][0]['applicationId']==doc['applicationId']
    latest=complete(service,operation(service,doc,'change',data=payload(start='2026-03-01',end='2026-03-03')))
    replay=turn(env,query,command,'focused-cached-query')
    documents=replay['answerContext']['documents']
    assert len(documents)==1 and documents[0]['applicationId']==latest['applicationId']
    assert documents[0]['request']['trips'][0]['dateFrom']=='2026-03-01'
