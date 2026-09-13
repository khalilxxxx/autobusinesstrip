import unittest
from graph_harness import Harness,event,change,add

class GraphTests(unittest.TestCase):
    def start(self,h):
        q='9月14日到深圳北站拜访客户，9月15日返回，全程火车一等座'
        ev=event([change('reason','拜访客户',q),change('all_transport','火车-一等座',q)],[add('NEW1','深圳北站','2026-09-14',q),add('NEW2','','2026-09-15',q,'RETURN')])
        return h.execute(q,ev)
    def test_complete_route_success_repeat_and_ids(self):
        h=Harness();s,answer=self.start(h);self.assertEqual(s['flow_state'],'READY_TO_CONFIRM');self.assertIn('深圳',answer)
        s,answer=h.execute('确认提交',event(intent='SUBMIT'),s);self.assertEqual(s['last_submission']['application_no'],'API-1');self.assertIn('H04',h.trace);self.assertEqual(len(h.creates),1)
        s,answer=h.execute('确认提交',event(intent='SUBMIT'),s);self.assertNotIn('H04',h.trace);self.assertEqual(len(h.creates),1)
    def test_complete_route_failure_retry_success(self):
        h=Harness();s,_=self.start(h);h.mode='MOCK_SUBMIT_FAILED';s,answer=h.execute('确认提交',event(intent='SUBMIT'),s);self.assertEqual(s['last_submission']['status'],'FAILED');self.assertIn('控制台实际失败说明',answer)
        h.mode='SUCCESS';s,answer=h.execute('确认提交',event(intent='SUBMIT'),s);self.assertEqual(s['last_submission']['status'],'SUCCEEDED');self.assertNotEqual(h.creates[0][0],h.creates[1][0])
    def test_http_rejection_message_preserved(self):
        h=Harness();s,_=self.start(h);h.mode='HTTP_422';s,answer=h.execute('确认提交',event(intent='SUBMIT'),s);self.assertIn('城市字段格式错误',answer);self.assertEqual(s['last_submission']['status'],'UNKNOWN')
    def test_repair_and_recovery_are_preserved(self):
        h=Harness();q='明天去成都出差';ev=event(trips=[add('NEW1','成都','2026-09-13',q)])
        s,_=h.execute(q,event(),repair=ev);self.assertIn('R02',h.trace);self.assertEqual(s['draft']['trips'][0]['depart_date']['value'],'2026-09-13')
        h=Harness();s,_=h.execute(q,event());self.assertIn('R03',h.trace);self.assertTrue(s['dialogue']['recovery'])
    def test_new_version_blocks_old_confirmation(self):
        h=Harness();s,_=self.start(h);old=s['confirmation'];q='事由改为参加展会';s,_=h.execute(q,event([change('reason','参加展会',q)]),s);self.assertGreater(s['draft']['revision'],old['revision']);s['confirmation']=old
        s,answer=h.execute('确认提交',event(intent='SUBMIT'),s);self.assertEqual(s['flow_state'],'COLLECTING');self.assertEqual(len(h.creates),0)
if __name__=='__main__':unittest.main()
