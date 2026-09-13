"""离线执行实际节点；API信封来自模拟目录函数，未调用Dify或模型。"""
import copy
import hashlib
import inspect
import json
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
CAT = runpy.run_path(str(ROOT.parents[1] / '模拟差旅系统/mock_travel/catalog.py'))
def dump(x): return json.dumps(x, ensure_ascii=False)
def fingerprint(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',', ':')).encode()).hexdigest()
def run(name, **kwargs):
    path = ROOT / 'nodes' / (name + '.py')
    assert path.exists(), '缺少API适配节点：' + name
    f = runpy.run_path(str(path))['main']
    assert set(kwargs) <= set(inspect.signature(f).parameters), '节点尚未接入API参数：' + name
    return f(**kwargs)
def envelope(data, code='SUCCESS'): return dump({'code':code,'data':data,'message':{}})
def context():
    data={'employeeContext':CAT['employee_context'](),'transportOptions':CAT['transport_options'](),'cityNames':[x['data']['cityName'] for x in CAT['CITIES']]+['昆山']}
    return run('N02',query='安排出差',cv_session='{}',demo_reference_date='2026-09-12',run_id='test',api_body=envelope(data))
def field(x): return {'value':x,'source':'USER' if x else '', 'evidence':x}
def candidate(to='深圳北站',transport='高铁二等座'):
    employee=CAT['employee_context']()
    draft={'draft_id':'D-test','revision':1,'next_trip_id':3,'applicant_id':'DEMO_EMP_001','applicant_name':'演示员工','department':employee['defaultDepartment']['name'],'payer_company':employee['defaultPayerCompany']['name'],'travel_type':'NORMAL','reason':'拜访"新客户"\n沟通方案','all_transport':field(''),'scope_requests':dict(companions='',activity='',excluded=''),'basic_sources':{},'open_clarifications':[],'trips':[]}
    for i, (a,b,k,dt) in enumerate([('',to,'OUTBOUND','2026-09-14'),('','','RETURN','2026-09-15')],1):
        draft['trips'].append(dict(id='T'+str(i),kind=k,from_city=field(a),to_city=field(b),depart_date=field(dt),arrive_date=field(''),transport=field(transport)))
    return {'draft':draft,'action':'REVIEW','merge_error':'','dialogue':{'focus':{'draft_id':'','revision':0,'questions':[]},'recovery':{}}}
def checked(to='深圳北站', transport='高铁二等座', overrides=None):
    ctx=context(); c=candidate(to,transport)
    q=run('C01',candidate_json=dump(c),context_json=ctx['context_json'])
    items=[{'query':s,'matches':CAT['query_cities'](s)} for s in json.loads(q['body'])['queries']]
    if overrides:
        for item in items:
            if item['query'] in overrides:item['matches']=overrides[item['query']]
    result=run('N07',candidate_json=dump(c),context_json=ctx['context_json'],api_body=envelope({'items':items}))
    return ctx,result

def ready():
    ctx,check=checked(); s=json.loads(ctx['state_json']);c=json.loads(check['checked_json']);d=c['draft']
    s.update(flow_state='READY_TO_CONFIRM',draft=d,confirmation=dict(draft_id=d['draft_id'],revision=d['revision'],fingerprint=fingerprint(d)))
    p={'query':'确认提交','action':'SUBMIT','event':{'basic_updates':[],'trip_operations':[]}}
    return s,p,c,json.loads(check['context_json'])
def gate(s=None,p=None,c=None,ctx=None):
    if s is None:s,p,c,ctx=ready()
    return run('N10',state_json=dump(s),plan_json=dump(p),checked_json=dump(c),context_json=dump(ctx))
def receipt(g, status='SUCCEEDED', code='SUCCESS',http=200):
    data={'action':'AI_CREATE','demoOnly':True,'clientRequestId':g['request_id']}
    if status=='SUCCEEDED':data.update(applicationId='A-API',applicationNo='API-2026-001',createdAt='2026-09-12T12:00:00+08:00')
    r={'code':code,'data':data,'message':{'text':'管理员设置的失败说明'}}
    return run('S01',gate_json=g['gate_json'],api_body=dump(r),status_code=http)

class DemoTests(unittest.TestCase):
    def test_context_uses_api(self):
        c=json.loads(context()['context_json']);self.assertEqual(c['employee']['name'],'演示员工');self.assertEqual(len(c['transports']),21);self.assertEqual(c['cities'],[])
    def test_new_city_alias_default_return(self):
        _,r=checked();c=json.loads(r['checked_json']);self.assertEqual(c['issues'],[]);self.assertEqual(c['draft']['trips'][0]['resolved_to']['code'],'DEMO_SHENZHEN');self.assertEqual(c['draft']['trips'][1]['resolved_to']['code'],'330100')
    def test_all_50_cities(self):
        for city in CAT['CITIES']:
            name=city['data']['cityName'];_,r=checked(name);trip=json.loads(r['checked_json'])['draft']['trips'][0];self.assertEqual(trip['resolved_to']['code'],city['data']['cityId'])
    def test_kunshan(self):
        _,r=checked('昆山');d=json.loads(r['checked_json'])['draft']['trips'][0]['resolved_to'];self.assertEqual((d['place'],d['name'],d['code'],d['mapped']),('昆山','苏州','DEMO_SUZHOU',True))
    def test_tonglu(self):
        _,r=checked('桐庐');d=json.loads(r['checked_json'])['draft']['trips'][0]['resolved_to'];self.assertEqual((d['name'],d['code']),('桐庐','330122'))
    def test_missing_city(self):
        _,r=checked('不存在城市');self.assertTrue(any(x['code']=='CITY_UNKNOWN' for x in json.loads(r['checked_json'])['issues']))
    def test_ambiguous_city(self):
        _,r=checked('深圳',overrides={'深圳':CAT['query_cities']('深圳')+CAT['query_cities']('苏州')});c=json.loads(r['checked_json']);self.assertTrue(any('多个' in x['question'] for x in c['issues']));self.assertEqual(c['draft']['trips'][0]['resolved_to']['code'],'')
    def test_all_21_transports(self):
        for t in CAT['transport_options']():
            _,r=checked(transport=t['value']);self.assertEqual(json.loads(r['checked_json'])['draft']['trips'][0]['resolved_transport']['code'],t['value'])
    def test_air_business_not_downgraded(self):
        _,r=checked(transport='飞机商务舱');self.assertTrue(any(x['code']=='TRANSPORT_UNAVAILABLE' for x in json.loads(r['checked_json'])['issues']))
    def test_city_payload_quotes_newlines(self):
        c=candidate('城市"\n名');q=run('C01',candidate_json=dump(c),context_json=context()['context_json']);self.assertIn('城市"\n名',json.loads(q['body'])['queries'])
    def test_submit_payload_success(self):
        g=gate();self.assertEqual(g['route'],'HTTP');b=json.loads(g['body']);self.assertEqual(b['remark'],'拜访"新客户"\n沟通方案');self.assertEqual(b['trips'][0]['tool'],'火车-二等座');self.assertEqual(b['departmentId'],'DEMO_DEPT_001');r=json.loads(receipt(g)['result_json']);self.assertEqual(r['state']['last_submission']['application_no'],'API-2026-001');self.assertEqual(r['state']['flow_state'],'SUBMITTED');run('N12',result_json=dump(r))
    def test_stale_confirmation_rejected(self):
        s,p,c,ctx=ready();s['confirmation']['revision']=0;g=gate(s,p,c,ctx);self.assertEqual(g['route'],'RESULT')
    def test_nonstandalone_rejected(self):
        s,p,c,ctx=ready();p['query']='确认提交并改事由';self.assertEqual(gate(s,p,c,ctx)['route'],'RESULT')
    def test_pending_recovery_rejected(self):
        s,p,c,ctx=ready();s['dialogue']['recovery']={'id':'pending'};self.assertEqual(gate(s,p,c,ctx)['route'],'RESULT')
    def test_repeat_confirm_replays(self):
        s,p,c,ctx=ready();g=gate(s,p,c,ctx);s=json.loads(receipt(g)['result_json'])['state'];r=gate(s,p,c,ctx);self.assertEqual(r['route'],'RESULT');self.assertIn('API-2026-001',r['result_json'])
    def test_failed_retry_new_id(self):
        s,p,c,ctx=ready();g=gate(s,p,c,ctx);r=json.loads(receipt(g,'FAILED','MOCK_SUBMIT_FAILED')['result_json']);self.assertEqual(r['state']['last_submission']['status'],'FAILED');self.assertIn('管理员设置的失败说明',r['reply_text']);g2=gate(r['state'],p,c,ctx);self.assertNotEqual(g['request_id'],g2['request_id']);run('N12',result_json=dump(r))
    def test_unknown_reuses_id(self):
        s,p,c,ctx=ready();g=gate(s,p,c,ctx);r=run('S01',gate_json=g['gate_json'],api_body='',status_code=0);state=json.loads(r['result_json'])['state'];self.assertEqual(state['last_submission']['status'],'UNKNOWN');self.assertEqual(gate(state,p,c,ctx)['request_id'],g['request_id']);run('N12',result_json=r['result_json'])
    def test_receipt_not_found_same_id_create(self):
        g=gate();r=run('Q01',gate_json=g['gate_json'],api_body=envelope({},'SUBMISSION_NOT_FOUND'),status_code=404);self.assertEqual(r['route'],'CREATE')
    def test_receipt_success_replayed(self):
        g=gate();resp={'code':'SUCCESS','data':{'status':'SUCCEEDED','clientRequestId':g['request_id'],'result':{'code':'SUCCESS','message':{},'data':{'action':'AI_CREATE','demoOnly':True,'clientRequestId':g['request_id'],'applicationId':'A-Q','applicationNo':'NO-Q','createdAt':'date'}}}}
        r=run('Q01',gate_json=g['gate_json'],api_body=dump(resp),status_code=200);self.assertEqual(r['route'],'RESULT');self.assertEqual(json.loads(r['result_json'])['state']['last_submission']['application_no'],'NO-Q')
    def test_bad_http_no_success(self):
        for status in [409,422,500]:
            r=json.loads(receipt(gate(),http=status)['result_json']);self.assertNotEqual(r['state']['flow_state'],'SUBMITTED')
    def test_wrong_request_receipt_unknown(self):
        g=gate();r=run('S01',gate_json=g['gate_json'],api_body=envelope({'applicationNo':'fake','clientRequestId':'other'}),status_code=200);self.assertEqual(json.loads(r['result_json'])['state']['last_submission']['status'],'UNKNOWN')
    def test_n12_rejects_bad_fingerprint(self):
        s,p,c,ctx=ready();s['confirmation']['fingerprint']='bad'
        with self.assertRaises(ValueError):run('N12',result_json=dump({'state':s,'reply_text':'核对'}))
if __name__=='__main__':unittest.main()
