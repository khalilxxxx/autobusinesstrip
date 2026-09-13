"""生命周期真实事务测试，覆盖状态、有效版本、重试与竞态。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest
from mock_travel.app import create_app
from mock_travel.store import ServiceError, Store


def payload(city='DEMO_SHANGHAI', start='2025-12-29', end='2026-01-03'):
    return dict(applicantId='DEMO_EMP_001', departmentId='DEMO_DEPT_001',
                payerCompanyId='DEMO_COMPANY_001', remark='客户拜访', dqydbg=None,
                trips=[dict(dateFrom=start,dateTo=start,cityFrom='330100',cityTo=city,tool='火车-二等座'),
                       dict(dateFrom=end,dateTo=end,cityFrom=city,cityTo='330100',tool='火车-二等座')])


@pytest.fixture
def service(tmp_path):
    app = create_app(tmp_path / 'life.db')
    assert hasattr(app.state, 'lifecycle'), '创建接口尚未初始化生命周期业务服务'
    return app.state.lifecycle


def create(service, data=None):
    result = service.store.create(data or payload(), str(uuid4()))
    return service.document(result['data']['applicationId'])


def operation(service, doc, action, data=None, request_id=None):
    return service.operate(doc['applicationId'], action, request_id or str(uuid4()), doc['version'], data)['document']


def approval(service, doc, action):
    return service.approve(doc['applicationId'], action, str(uuid4()), doc['version'])['document']


def complete(service, doc):
    return approval(service, approval(service, doc, 'start'), 'complete')


def test_change_withdraw_void_restores_direct_predecessor(tmp_path):
    store = Store(tmp_path / 'business.db')
    created = store.create(payload(), 'initial')['data']
    a = store.application(created['applicationId'])
    assert a.get('status') == 'S002', '首次提交必须进入待审批状态，而不是没有业务状态'
    from mock_travel.lifecycle import LifecycleService
    service = LifecycleService(store)
    a = service.document(a['applicationId'])
    assert (a['status'], a['tflag'], a['isEffective']) == ('S002', 'D', False)
    a = complete(service, a)
    a1 = operation(service, a, 'change', payload('DEMO_BEIJING'))
    original = service.document(a['applicationId'])
    assert original['tflag'] == 'YBG' and original['isEffective']
    a1 = operation(service, a1, 'withdraw')
    assert a1['status'] == 'S005'
    cancelled = operation(service, a1, 'void')
    assert (cancelled['status'],cancelled['tflag']) == ('S100','D')
    restored = service.document(a['applicationId'])
    assert restored['tflag'] == 'D' and restored['isEffective']
    assert operation(service, restored, 'change', payload())['status'] == 'S002'


def test_multigeneration_references_hide_old_content_and_void_never_restores(service):
    a = complete(service, create(service))
    a1 = complete(service, operation(service, a, 'change', payload('DEMO_BEIJING')))
    a2 = complete(service, operation(service, a1, 'change', payload('DEMO_SUZHOU')))
    for old in [a,a1]:
        current = service.document(old['applicationNo'])
        assert current['applicationId'] == a2['applicationId']
        assert current['resolvedFrom'] == old['applicationNo']
        assert current['request']['trips'][0]['cityTo'] == 'DEMO_SUZHOU'
        with pytest.raises(ServiceError):
            operation(service, old, 'void')
    assert len(service.list_documents({})['items']) == 1
    a2 = operation(service,a2,'void')
    assert not a2['isEffective'] and a2['currentEffectiveId'] is None
    assert service.list_documents({'effectiveOnly':True})['total'] == 0
    assert service.document(a['applicationId'])['applicationId'] == a2['applicationId']


def test_resubmit_keeps_number_history_but_withdraw_checks_current_round(service):
    a = approval(service,create(service),'start')
    with pytest.raises(ServiceError): operation(service,a,'withdraw')
    a = approval(service,a,'return')
    with pytest.raises(ServiceError): operation(service,a,'void')
    number = a['applicationNo']
    a = operation(service,a,'resubmit',payload('DEMO_BEIJING'))
    assert a['applicationNo'] == number and a['submissionRound'] == 2
    assert any(e['action']=='start' and e['submissionRound']==1 for e in a['history'])
    a = operation(service,a,'withdraw')
    assert a['status']=='S005'


def test_idempotency_failure_receipts_restart_identity_and_content(service):
    a = create(service)
    result = service.operate(a['applicationId'],'withdraw','retry',a['version'])
    assert service.operate(a['applicationId'],'withdraw','retry',a['version']) == result
    with pytest.raises(ServiceError) as conflict:
        service.operate(a['applicationId'],'void','retry',a['version'])
    assert conflict.value.status == 409
    with pytest.raises(ServiceError):
        service.operate(a['applicationId'],'withdraw','retry',a['version'],applicant_id='other')
    with pytest.raises(ServiceError): service.receipt('retry',applicant_id='other')
    with pytest.raises(ServiceError): operation(service,a,'void',request_id='failed')
    from mock_travel.lifecycle import LifecycleService
    restarted = LifecycleService(Store(service.store.path))
    assert restarted.receipt('retry')['result'] == result
    assert restarted.receipt('failed')['status']=='FAILED'
    with pytest.raises(ServiceError): operation(restarted,a,'void',request_id='failed')


@pytest.mark.parametrize('race', ['change-change','change-void','resubmit-void'])
def test_two_connections_only_one_racing_operation_succeeds(service,race):
    a = complete(service,create(service))
    if race=='resubmit-void': a=operation(service,operation(service,a,'change',payload()),'withdraw')
    actions=race.split('-')
    def run(action):
        try: return operation(service,a,action,payload() if action in {'change','resubmit'} else None)
        except ServiceError: return None
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,actions))
    assert sum(r is not None for r in results)==1


@pytest.mark.parametrize('mutation,field',[
    (lambda p:p.pop('departmentId'),'departmentId'),
    (lambda p:p.update(payerCompanyId='unknown'),'payerCompanyId'),
    (lambda p:p['trips'][0].update(dateFrom='2025-02-30'),'trips.0.dateFrom'),
    (lambda p:p['trips'][0].update(cityTo='unknown'),'trips.0.cityTo'),
    (lambda p:p['trips'][0].update(tool='飞机-头等舱'),'trips.0.tool'),
    (lambda p:p['trips'][-1].update(cityTo='DEMO_BEIJING'),'trips'),
    (lambda p:p['trips'][-1].update(cityFrom='DEMO_BEIJING'),'trips.1.cityFrom'),
    (lambda p:p['trips'][-1].update(dateFrom='2025-01-01',dateTo='2025-01-01'),'trips.1.dateFrom'),
])
def test_full_payload_validation_is_field_specific_and_atomic(service,mutation,field):
    a=complete(service,create(service)); bad=payload(); mutation(bad)
    with pytest.raises(ServiceError) as error: operation(service,a,'change',bad)
    assert any(i['field']==field for i in error.value.issues)
    assert service.document(a['applicationId'])['tflag']=='D'
    assert service.list_documents({})['total']==1


def test_migration_does_not_assume_legacy_approval(tmp_path):
    import sqlite3
    db=tmp_path/'legacy.db'
    store=Store(db)
    a=store.create(payload(),'legacy')['data']
    with sqlite3.connect(db) as conn:
        # 删除本轮状态，模拟只有旧 applications 的数据库。
        conn.execute('DELETE FROM lifecycle_snapshots')
        conn.execute('DELETE FROM lifecycle_documents')
        conn.execute('DELETE FROM lifecycle_roots')
    from mock_travel.lifecycle import LifecycleService
    doc=LifecycleService(Store(db)).document(a['applicationId'])
    assert doc['status']=='UNKNOWN' and not doc['isEffective']
    assert all(not rule['allowed'] for rule in doc['actions'].values())


def test_receipt_never_reveals_superseded_submission_contents(service):
    a=create(service)
    first=service.operate(a['applicationId'],'withdraw','old-content',a['version'])
    a=operation(service,first['document'],'resubmit',payload('DEMO_BEIJING'))
    receipt=service.receipt('old-content')['result']['document']
    assert receipt['request']['trips'][0]['cityTo']=='DEMO_BEIJING'
    replay=service.operate(first['document']['applicationId'],'withdraw','old-content',1)
    assert replay['document']['request']['trips'][0]['cityTo']=='DEMO_BEIJING'
    with service.store.connection() as conn:
        snapshots=conn.execute('SELECT payload_json FROM lifecycle_snapshots WHERE application_id=? ORDER BY submission_round',(a['applicationId'],)).fetchall()
    assert len(snapshots)==2
    assert 'DEMO_SHANGHAI' in snapshots[0][0] and 'DEMO_BEIJING' in snapshots[1][0]


def test_cancel_second_generation_only_restores_direct_predecessor(service):
    a=complete(service,create(service))
    a1=complete(service,operation(service,a,'change',payload('DEMO_BEIJING')))
    a2=operation(service,a1,'change',payload('DEMO_SUZHOU'))
    a2=approval(service,a2,'start'); a2=approval(service,a2,'return')
    a2=operation(service,a2,'resubmit',payload('DEMO_SUZHOU'))
    predecessor=service.document(a1['applicationId'])
    assert predecessor['tflag']=='YBG' and predecessor['isEffective'] and a2['tflag']=='D'
    operation(service,operation(service,a2,'withdraw'),'void')
    assert service.document(a1['applicationId'])['tflag']=='D'
    with service.store.connection() as conn:
        assert conn.execute('SELECT tflag FROM lifecycle_documents WHERE application_id=?',(a['applicationId'],)).fetchone()[0]=='YBG'


def test_ybx_and_foreign_document_never_allow_employee_changes(service):
    a=complete(service,create(service))
    with service.store.connection(write=True) as conn:
        conn.execute("UPDATE lifecycle_documents SET tflag='YBX' WHERE application_id=?",(a['applicationId'],))
    a=service.document(a['applicationId'])
    for action in ['void','change']:
        assert not a['actions'][action]['allowed']
        with pytest.raises(ServiceError): operation(service,a,action,payload() if action=='change' else None)
    with pytest.raises(ServiceError): service.document(a['applicationId'],applicant_id='other')
    assert service.list_documents({},applicant_id='other')['total']==0


def test_withdraw_racing_first_approval_has_one_winner(service):
    a=create(service)
    def run(action):
        try: return operation(service,a,action) if action=='withdraw' else approval(service,a,action)
        except ServiceError: return None
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,['withdraw','start']))
    assert sum(result is not None for result in results)==1
    assert service.document(a['applicationId'])['status'] in {'S003','S005'}


def test_failure_replay_is_stable_and_cannot_change_to_approval_role(service):
    a=create(service)
    with pytest.raises(ServiceError) as first: operation(service,a,'void',request_id='invalid-void')
    receipt=service.receipt('invalid-void')
    a=complete(service,a)
    with pytest.raises(ServiceError) as replay:
        service.operate(a['applicationId'],'void','invalid-void',1)
    assert replay.value.code==first.value.code
    assert service.receipt('invalid-void')==receipt
    with pytest.raises(ServiceError) as conflict:
        service.approve(a['applicationId'],'start','invalid-void',1)
    assert conflict.value.status==409


def test_change_records_reason_and_all_editable_nontrip_fields(service):
    a=complete(service,create(service)); changed=payload('DEMO_BEIJING')
    changed.update(remark='研发驻场',dqydbg='Y',departmentId='DEMO_DEPT_002',payerCompanyId='DEMO_COMPANY_002')
    a1=service.operate(a['applicationNo'],'change','reason-change',a['version'],changed,reason='客户调整安排')['document']
    assert a1['history'][-1].get('reason')=='客户调整安排'
    a1=complete(service,a1)
    assert service.document(a['applicationNo'])['request']==changed
    assert a1['isEffective'] and a1['tflag']=='D'


def test_success_receipt_of_replaced_document_resolves_current_content(service):
    a=complete(service,create(service))
    a1=service.operate(a['applicationId'],'change','chain-receipt',a['version'],payload('DEMO_BEIJING'))['document']
    a1=complete(service,a1)
    a2=complete(service,operation(service,a1,'change',payload('DEMO_SUZHOU')))
    receipt=service.receipt('chain-receipt')['result']
    assert receipt['document']['applicationId']==a2['applicationId']
    assert receipt['documentResolvedToCurrent'] is True
    assert 'DEMO_BEIJING' not in str(receipt)
