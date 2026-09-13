"""直接作废只接受当前原话或服务器上下文确定的目标，模型引用不是授权。"""
import json
import pytest
from test_lifecycle import create, complete, operation, payload
from test_lifecycle_assistant import env
from test_lifecycle_workflow import turn


@pytest.mark.parametrize('context', ['none', 'multiple', 'selected_other'])
def test_model_reference_cannot_supply_or_override_deictic_void_target(env, context):
    app, c, cid, url = env; service = app.state.lifecycle
    a = complete(service, create(service)); b = complete(service, create(service))
    if context == 'multiple':
        turn(env, '查询所有单据', {'intent': 'QUERY'})
    elif context == 'selected_other':
        turn(env, '查看' + b['applicationNo'], {'intent': 'DETAIL', 'reference': b['applicationId']})
    result = turn(env, '作废这张', {'intent': 'VOID', 'reference': a['applicationId']})
    assert service.document(a['applicationId'])['status'] == 'S004'
    assert service.document(b['applicationId'])['status'] == 'S004'
    assert c.get(url).json()['lastReceipt'] is None
    assert '单号' in result['reply'] or '目标' in result['reply']


def test_explicit_void_number_must_agree_with_model_reference(env):
    app, c, cid, url = env; service = app.state.lifecycle
    a = complete(service, create(service)); b = complete(service, create(service))
    result = turn(env, '请作废差旅申请单 ' + b['applicationNo'],
                  {'intent': 'VOID', 'reference': a['applicationId']})
    assert service.document(a['applicationId'])['status'] == 'S004'
    assert service.document(b['applicationId'])['status'] == 'S004'
    assert c.get(url).json()['lastReceipt'] is None
    assert '不一致' in result['reply']


@pytest.mark.parametrize('label', ['单据', '申请单', '申请'])
def test_generic_document_label_accepts_explicit_number_and_retains_void_reason(env, label):
    app, c, cid, url = env; service = app.state.lifecycle
    a = complete(service, create(service)); b = complete(service, create(service))
    query = '请作废' + label + ' ' + a['applicationNo'] + '，原因：客户取消会议，不需要出差'
    denied = turn(env, '不要' + query, {'intent': 'VOID', 'reference': a['applicationId']})
    assert service.document(a['applicationId'])['status'] == 'S004'
    assert '未执行' in denied['reply']
    mismatched = turn(env, query, {'intent': 'VOID', 'reference': b['applicationId']})
    assert service.document(a['applicationId'])['status'] == 'S004'
    assert service.document(b['applicationId'])['status'] == 'S004'
    result = turn(env, query, {'intent': 'VOID', 'reference': a['applicationId']})
    after = service.document(a['applicationId'])
    assert after['status'] == 'S100'
    assert after['history'][-1]['reason'] == '客户取消会议，不需要出差'
    assert '已作废' in result['reply']
    assert '不一致' in mismatched['reply']


@pytest.mark.parametrize('model_fields', [{}, {'resultIndex': 2}])
def test_explicit_result_index_resolves_current_server_result_without_model_reference(env, model_fields):
    app, c, cid, url = env; service = app.state.lifecycle
    complete(service, create(service)); complete(service, create(service))
    turn(env, '查申请', {'intent': 'QUERY'})
    documents = c.get(url).json()['documents']
    result = turn(env, '作废第二张', {'intent': 'VOID', **model_fields})
    assert service.document(documents[0]['applicationId'])['status'] == 'S004'
    assert service.document(documents[1]['applicationId'])['status'] == 'S100'
    assert '已作废' in result['reply']


@pytest.mark.parametrize('claim', ['index', 'reference'])
def test_explicit_result_index_rejects_conflicting_model_target(env, claim):
    app, c, cid, url = env; service = app.state.lifecycle
    complete(service, create(service)); complete(service, create(service))
    turn(env, '查申请', {'intent': 'QUERY'})
    documents = c.get(url).json()['documents']
    fields = {'resultIndex': 1} if claim == 'index' else {'reference': documents[0]['applicationId']}
    result = turn(env, '作废第二张', {'intent': 'VOID', **fields})
    assert all(service.document(d['applicationId'])['status'] == 'S004' for d in documents)
    assert c.get(url).json()['lastReceipt'] is None
    assert '不一致' in result['reply']


@pytest.mark.parametrize('source', ['explicit', 'selected', 'single_result'])
def test_unique_server_or_explicit_void_target_does_not_require_model_reference(env, source):
    app, c, cid, url = env; service = app.state.lifecycle
    doc = complete(service, create(service)); query = '作废这张'
    if source == 'selected':
        turn(env, '查看' + doc['applicationNo'], {'intent': 'DETAIL', 'reference': doc['applicationId']})
    elif source == 'single_result':
        turn(env, '查申请', {'intent': 'QUERY'})
    else:
        query = '将' + doc['applicationNo'] + '作废'
    result = turn(env, query, {'intent': 'VOID'})
    assert service.document(doc['applicationId'])['status'] == 'S100'
    assert '已作废' in result['reply']


def test_explicit_old_number_is_not_retargeted_to_current_version(env):
    app, c, cid, url = env; service = app.state.lifecycle
    old = complete(service, create(service))
    current = complete(service, operation(service, old, 'change', data=payload('DEMO_BEIJING')))
    result = turn(env, '作废' + old['applicationNo'], {'intent': 'VOID', 'reference': current['applicationId']})
    assert service.document(current['applicationId'])['status'] == 'S004'
    assert c.get(url).json()['lastReceipt'] is None
    assert '不一致' in result['reply']


def test_legacy_query_cache_without_answer_context_refreshes_current_details(env):
    app, c, cid, url = env; service = app.state.lifecycle
    doc = complete(service, create(service))
    query = '查看这张申请'; command = {'intent': 'QUERY', 'filter': {'keyword': doc['applicationNo']}}
    turn(env, query, command, 'legacy-query-cache')
    store = app.state.assistant_manager.store
    with store.connection(write=True) as conn:
        conn.execute('UPDATE assistant_lifecycle_turns SET reply_json=? WHERE request_id=?',
                     (json.dumps({'handled': True, 'reply': doc['applicationNo'] + ' 2025-12-29 上海'}), 'legacy-query-cache'))
    latest = complete(service, operation(service, doc, 'change', data=payload(start='2026-03-01', end='2026-03-03')))
    replay = turn(env, query, command, 'legacy-query-cache')
    assert doc['applicationNo'] not in replay['reply']
    assert '2025-12-29' not in replay['reply']
    documents = replay['answerContext']['documents']
    assert len(documents) == 1 and documents[0]['applicationId'] == latest['applicationId']
    assert documents[0]['request']['trips'][0]['dateFrom'] == '2026-03-01'


@pytest.mark.parametrize('legacy', [False, True])
def test_replayed_query_refreshes_facts_without_replacing_current_cards_or_selection(env, legacy):
    app, c, cid, url = env; service = app.state.lifecycle
    store = app.state.assistant_manager.store
    old = complete(service, create(service)); other = complete(service, create(service))
    query = '查申请'; command = {'intent': 'QUERY', 'filter': {'keyword': old['applicationNo']}}
    q1, _ = store.start_turn(cid, query, 'query-card-q1')
    first = turn(env, query, command, 'query-run-q1')
    store.finish(q1, first['reply'], 'succeeded', state={})
    if legacy:
        with store.connection(write=True) as conn:
            conn.execute('UPDATE assistant_lifecycle_turns SET reply_json=? WHERE request_id=?',
                         (json.dumps({'handled': True, 'reply': old['applicationNo'] + '旧行程'}), 'query-run-q1'))
    # 当前选择来自另一次真实详情操作，旧查询重放不能覆盖它。
    turn(env, '查看' + other['applicationNo'], {'intent': 'DETAIL', 'reference': other['applicationId']})
    q2, _ = store.start_turn(cid, '谢谢', 'cardless-q2')
    store.finish(q2, '不客气', 'succeeded', state={})
    latest = complete(service, operation(service, old, 'change', data=payload(start='2026-03-01', end='2026-03-03')))
    before = app.state.lifecycle_assistant._read(cid)
    replay = turn(env, query, command, 'query-run-q1')
    after = app.state.lifecycle_assistant._read(cid)
    assert after == before
    assert replay['answerContext']['documents'][0]['applicationId'] == latest['applicationId']
    assert replay['answerContext']['documents'][0]['request']['trips'][0]['dateFrom'] == '2026-03-01'
    assert old['applicationNo'] not in replay['reply']
