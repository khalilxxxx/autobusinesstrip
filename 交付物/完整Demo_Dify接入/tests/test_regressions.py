import copy
import json
import runpy
import unittest
from test_demo import ROOT,CAT,context,checked,ready,gate,run,dump,receipt,candidate

class RegressionTests(unittest.TestCase):
    def test_city_range_remains_in_repair_context(self):
        ctx=json.loads(context()['context_json'])
        for n in ['N04','R02']:
            ns=runpy.run_path(str(ROOT/'nodes'/ (n+'.py')))
            self.assertTrue(ns['possible_fact_signal']('到成都出差',ctx))
    def test_recommendation_and_recheck_keep_http_mapping(self):
        _,r=checked('深圳北站','');c=json.loads(r['checked_json']);response={'recommendations':[{'trip_id':t['trip_id'],'transport':'火车-一等座','reason':'离线人工建议'} for t in c['transport_requests']]}
        a=run('N07A',checked_json=r['checked_json'],response_text=dump(response),context_json=r['context_json']);d=json.loads(a['checked_json']);self.assertEqual(d['issues'],[]);self.assertEqual(d['draft']['trips'][0]['resolved_to']['code'],'DEMO_SHENZHEN')
        ns=runpy.run_path(str(ROOT/'nodes/N07.py'));recheck=ns['validate'](dump(d),r['context_json']);self.assertEqual(json.loads(recheck['checked_json'])['draft'],d['draft'])
    def test_failed_retry_loss_retransmits_same_next_id(self):
        s,p,c,ctx=ready();g=gate(s,p,c,ctx);failed=json.loads(receipt(g,'FAILED','MOCK_SUBMIT_FAILED')['result_json'])['state'];g2=gate(failed,p,c,ctx);g3=gate(failed,p,c,ctx);self.assertEqual(g2['request_id'],g3['request_id'])
    def test_repeat_confirm_revalidated_draft_keeps_fingerprint(self):
        s,p,c,ctx=ready();g=gate(s,p,c,ctx);s=json.loads(receipt(g)['result_json'])['state'];ns=runpy.run_path(str(ROOT/'nodes/N07.py'));new=ns['validate'](dump({**c,'draft':s['draft'],'action':'SUBMIT'}),dump(ctx));self.assertEqual(gate(s,p,json.loads(new['checked_json']),ctx)['route'],'RESULT')
    def test_missing_fields_rejected(self):
        s,p,c,ctx=ready();c['issues']=[{'code':'MISSING_REASON'}];self.assertEqual(gate(s,p,c,ctx)['route'],'RESULT')
    def test_short_term_body(self):
        s,p,c,ctx=ready();s['draft']['travel_type']=c['draft']['travel_type']='SHORT_TERM'
        from test_demo import fingerprint
        s['confirmation']['fingerprint']=fingerprint(c['draft']);self.assertEqual(json.loads(gate(s,p,c,ctx)['body'])['dqydbg'],'Y')
    def test_failure_receipt_query_is_definitive(self):
        g=gate();r={'code':'SUCCESS','data':{'clientRequestId':g['request_id'],'status':'FAILED','result':{'code':'MOCK_SUBMIT_FAILED','message':{'text':'真实失败'},'data':{'clientRequestId':g['request_id'],'action':'AI_CREATE','demoOnly':True}}}}
        result=run('Q01',gate_json=g['gate_json'],api_body=dump(r),status_code=200);s=json.loads(result['result_json']);self.assertEqual(s['state']['last_submission']['status'],'FAILED');self.assertIn('真实失败',s['reply_text'])
    def test_network_unknown_and_passthrough(self):
        g=gate();r=run('S99',gate_json=g['gate_json']);self.assertEqual(json.loads(r['result_json'])['state']['last_submission']['status'],'UNKNOWN')
        for node in ['Q02','S02']:self.assertEqual(run(node,result_json=r['result_json']),r)
    def test_context_http_failure_no_fake_data(self):
        with self.assertRaises(ValueError):run('N02',query='出差',cv_session='{}',demo_reference_date='',run_id='r',api_body=dump({'code':'ERROR','data':{}}))
    def test_city_http_failure_no_stale_maps(self):
        with self.assertRaises(ValueError):run('N07',candidate_json=dump(candidate()),context_json=context()['context_json'],api_body=dump({'code':'ERROR'}))
if __name__=='__main__':unittest.main()

class ReceiptAdapterTests(unittest.TestCase):
    def test_wrapped_404_continues_same_request(self):
        g=gate();body={'code':'SUCCESS','data':{'httpStatus':404,'result':{'code':'SUBMISSION_NOT_FOUND','data':{},'message':{}}}}
        r=run('Q01',gate_json=g['gate_json'],api_body=dump(body),status_code=200);self.assertEqual(r['route'],'CREATE')
    def test_wrapped_success_is_recognized(self):
        g=gate();inner={'code':'SUCCESS','data':{'clientRequestId':g['request_id'],'status':'SUCCEEDED','result':{'code':'SUCCESS','data':{'clientRequestId':g['request_id'],'action':'AI_CREATE','demoOnly':True,'applicationId':'A-W','applicationNo':'NO-W','createdAt':'date'},'message':{}}}}
        r=run('Q01',gate_json=g['gate_json'],api_body=dump({'code':'SUCCESS','data':{'httpStatus':200,'result':inner}}),status_code=200);self.assertEqual(json.loads(r['result_json'])['state']['last_submission']['status'],'SUCCEEDED')
