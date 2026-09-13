from fastapi.testclient import TestClient
from mock_travel.app import create_app
from test_lifecycle import payload, create, complete, operation


def test_http_actions_receipts_approval_options_and_legacy_visibility(tmp_path):
    app=create_app(tmp_path/'api.db'); service=app.state.lifecycle
    with TestClient(app) as client:
        options=client.get('/mock/v1/lifecycle/options')
        assert options.status_code==200
        data=options.json()['data']
        assert {'DEMO_DEPT_001','DEMO_DEPT_002'}=={x['id'] for x in data['departments']}
        assert {'DEMO_COMPANY_001','DEMO_COMPANY_002'}=={x['id'] for x in data['payerCompanies']}
        assert len(data['transports'])==21 and data['cities'] and data['travelTypes']
        a=create(service)
        url='/mock/v1/lifecycle/documents/'+a['applicationId']
        response=client.post(url+'/actions',json={'action':'withdraw','clientRequestId':'http-withdraw','expectedVersion':a['version']})
        assert response.status_code==200 and response.json()['data']['document']['status']=='S005'
        assert client.get('/mock/v1/lifecycle/receipts/http-withdraw').json()['data']['status']=='SUCCEEDED'
        wrong=client.post(url+'/actions',json={'action':'complete','clientRequestId':'bad','expectedVersion':2})
        assert wrong.status_code==422
        failed=client.post(url+'/actions',json={'action':'void','clientRequestId':'bad-void','expectedVersion':2})
        assert failed.status_code==409
        assert client.get('/mock/v1/lifecycle/receipts/bad-void').json()['data']['status']=='FAILED'
        a=operation(service,service.document(a['applicationId']),'resubmit',payload())
        started=client.post(url+'/approval',json={'action':'start','clientRequestId':'http-start','expectedVersion':a['version']}).json()['data']['document']
        a=client.post(url+'/approval',json={'action':'complete','clientRequestId':'http-complete','expectedVersion':started['version']}).json()['data']['document']
        newer=complete(service,operation(service,a,'change',payload('DEMO_BEIJING')))
        assert client.get(url).json()['data']['applicationId']==newer['applicationId']
        assert client.get('/mock/v1/travel/applications/'+a['applicationId']).json()['data']['applicationId']==newer['applicationId']
        assert client.get('/mock/v1/travel/applications').json()['data']['total']==1
        assert client.get('/mock/v1/lifecycle/documents',params={'effectiveOnly':True,'city':'上海'}).json()['data']['total']==0


def test_seed_is_repeatable_preserves_user_data_and_has_required_scenarios(tmp_path):
    app=create_app(tmp_path/'seed.db'); own=create(app.state.lifecycle)
    with TestClient(app) as client:
        one=client.post('/mock/v1/lifecycle/seed'); assert one.status_code==200
        first=client.get('/mock/v1/lifecycle/documents',params={'limit':100}).json()['data']
        two=client.post('/mock/v1/lifecycle/seed'); assert two.status_code==200
        second=client.get('/mock/v1/lifecycle/documents',params={'limit':100}).json()['data']
        assert first['total']==second['total']
        assert own['applicationId'] in {x['applicationId'] for x in second['items']}
        assert {'S002','S003','S004','S005'}<={x['status'] for x in second['items']}
        assert any(x['tflag']=='YBX' for x in second['items'])
        assert any(x['status']=='S005' and x['documentType']=='CHANGE' for x in second['items'])
        assert all(x['request']['applicantId']=='DEMO_EMP_001' for x in second['items'])
        for temporal in ['past','current','future']:
            assert client.get('/mock/v1/lifecycle/documents',params={'temporal':temporal,'effectiveOnly':True}).json()['data']['total']>=1


def test_http_field_issues_no_identity_override_and_input_bounds(tmp_path):
    app=create_app(tmp_path/'validation.db'); service=app.state.lifecycle
    a=complete(service,create(service)); url='/mock/v1/lifecycle/documents/'+a['applicationId']+'/actions'
    with TestClient(app) as client:
        bad=payload(); bad.pop('departmentId')
        response=client.post(url,json=dict(action='change',clientRequestId='missing',expectedVersion=a['version'],payload=bad))
        assert response.status_code==422
        assert any(x['field']=='departmentId' for x in response.json()['message']['details'])
        response=client.post(url,json=dict(action='void',clientRequestId='spoof',expectedVersion=a['version'],applicantId='other'))
        assert response.status_code==422
        assert client.get('/mock/v1/lifecycle/documents?limit=0').status_code==422


def test_business_failure_http_replay_preserves_error_shape(tmp_path):
    app=create_app(tmp_path/'error-replay.db'); a=create(app.state.lifecycle)
    body=dict(action='void',clientRequestId='failed-replay',expectedVersion=a['version'])
    with TestClient(app) as client:
        url='/mock/v1/lifecycle/documents/'+a['applicationId']+'/actions'
        first=client.post(url,json=body).json(); again=client.post(url,json=body).json()
        assert first['code']==again['code']
        assert first['message']==again['message']
