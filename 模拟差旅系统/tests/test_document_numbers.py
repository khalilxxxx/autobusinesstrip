"""演示单号的连续分配、旧数据兼容及回执一致性。"""
from concurrent.futures import ThreadPoolExecutor
import json

from mock_travel.lifecycle import LifecycleService
from mock_travel.lifecycle_seed import seed_documents
from mock_travel.store import Store, encode
from test_lifecycle import complete, operation, payload


def test_application_change_and_restart_share_one_sequence(tmp_path):
    store = Store(tmp_path / 'numbers.db')
    service = LifecycleService(store)
    first = store.create(payload(), 'first')['data']
    assert first['applicationNo'] == '123000001'
    approved = complete(service, service.document(first['applicationId']))
    changed = operation(service, approved, 'change', payload('DEMO_BEIJING'), 'change')
    assert changed['applicationNo'] == '123000002'
    assert store.create(payload(), 'first')['data'] == first
    assert service.operate(approved['applicationId'], 'change', 'change', approved['version'], payload('DEMO_BEIJING'))['document']['applicationNo'] == '123000002'
    withdrawn = operation(service, changed, 'withdraw')
    assert operation(service, withdrawn, 'resubmit', payload())['applicationNo'] == '123000002'
    restarted = Store(store.path)
    assert restarted.create(payload(), 'next')['data']['applicationNo'] == '123000003'


def test_concurrent_creates_allocate_unique_consecutive_numbers(tmp_path):
    store = Store(tmp_path / 'numbers.db')
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: store.create(payload(), f'create-{i}')['data'], range(8)))
    assert sorted(int(item['applicationNo']) for item in results) == list(range(123000001, 123000009))


def test_existing_demo_numbers_migrate_once_preserving_references_and_receipts(tmp_path):
    store = Store(tmp_path / 'legacy.db')
    service = LifecycleService(store)
    first = store.create(payload(), 'first')['data']
    approved = complete(service, service.document(first['applicationId']))
    changed = operation(service, approved, 'change', payload('DEMO_BEIJING'), 'change')
    before = service.document(approved['applicationId'])
    renamed = {first['applicationNo']: 'DEMO-CL-LEGACY', changed['applicationNo']: 'DEMO-BG-LEGACY'}

    def legacy(value):
        if isinstance(value, dict): return {k: legacy(v) for k, v in value.items()}
        if isinstance(value, list): return [legacy(v) for v in value]
        return renamed.get(value, value) if isinstance(value, str) else value

    with store.connection(write=True) as conn:
        for number, old in renamed.items():
            conn.execute('UPDATE applications SET application_no=? WHERE application_no=?', (old, number))
        for table in ('submissions', 'lifecycle_receipts'):
            for row in conn.execute(f'SELECT request_id,result_json FROM {table}').fetchall():
                conn.execute(f'UPDATE {table} SET result_json=? WHERE request_id=?', (encode(legacy(json.loads(row['result_json']))), row['request_id']))
        conn.execute('DROP TABLE IF EXISTS document_number_sequence')
        conn.execute('DROP TABLE IF EXISTS document_number_aliases')

    restarted = Store(store.path)
    current = LifecycleService(restarted)
    parent = current.document('DEMO-CL-LEGACY')
    child = current.document('DEMO-BG-LEGACY')
    assert parent['applicationNo'] == '123000001'
    assert child['applicationNo'] == '123000002' and child['rootNo'] == parent['applicationNo']
    for field in ('applicationId', 'status', 'version', 'tflag', 'isEffective', 'pendingChangeId', 'history'):
        assert parent[field] == before[field]
    assert current.list_documents({'keyword': 'DEMO-CL-LEGACY'})['items'][0]['applicationNo'] == '123000001'
    assert restarted.create(payload(), 'first')['data']['applicationNo'] == '123000001'
    assert restarted.submission('first')['result']['data']['applicationNo'] == '123000001'
    receipt = current.receipt('change')['result']['document']
    assert receipt['applicationNo'] == '123000002' and receipt['rootNo'] == '123000001'
    assert current.operate('DEMO-BG-LEGACY', 'withdraw', 'withdraw', child['version'])['document']['status'] == 'S005'
    again = Store(store.path)
    assert again.application(parent['applicationId'])['applicationNo'] == '123000001'
    assert again.create(payload(), 'third')['data']['applicationNo'] == '123000003'


def test_seed_documents_use_the_same_sequence_without_reset(tmp_path):
    store = Store(tmp_path / 'seed.db')
    service = LifecycleService(store)
    first = store.create(payload(), 'first')['data']
    seeded = seed_documents(service)
    numbers = [int(service.document(identifier)['applicationNo']) for identifier in seeded['applicationIds']]
    assert first['applicationNo'] == '123000001'
    assert sorted(numbers) == list(range(123000002, 123000002 + seeded['created']))
    assert seed_documents(service)['created'] == 0
    assert int(store.create(payload(), 'last')['data']['applicationNo']) == 123000002 + len(numbers)


def test_saved_creation_cards_show_current_number_without_changing_confirmation(tmp_path):
    from test_draft_interaction import fixture_state, seed
    database = tmp_path / 'cards.db'
    application = Store(database).create(payload(), 'created')['data']
    state = fixture_state()
    state['last_submission'] = dict(status='SUCCEEDED', draft_id='D-form', revision=1,
        application_id=application['applicationId'], application_no='DEMO-OLD-CARD', request_id='created')
    store, cid = seed(database, state)
    with store.connection(write=True) as conn:
        rows = conn.execute('SELECT id,draft_state_json FROM assistant_messages WHERE draft_state_json IS NOT NULL').fetchall()
        for row in rows:
            snapshot = json.loads(row['draft_state_json'])
            snapshot['draft'].update(department='演示业务部', payerCompany='演示科技公司')
            conn.execute('UPDATE assistant_messages SET draft_state_json=? WHERE id=?', (encode(snapshot), row['id']))
    before = store.private_conversation(cid)['state_json']
    view = store.conversation(cid)
    for card in [view['state'], *[m['draftState'] for m in view['messages'] if m['draftState']]]:
        assert card['lastSubmission']['applicationNo'] == application['applicationNo']
        assert card['draft']['department'] == '数字化部'
        assert card['draft']['payerCompany'] == '杭州某科技公司'
    assert store.private_conversation(cid)['state_json'] == before
    assert view['state']['fingerprint'] == state['confirmation']['fingerprint']
