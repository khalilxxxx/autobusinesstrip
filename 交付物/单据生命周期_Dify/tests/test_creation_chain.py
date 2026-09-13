"""执行完整新 DSL 创建链；模型与创建 HTTP 为固定夹具，生命周期 HTTP 为真实服务。"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parents[1]/'模拟差旅系统'))
sys.path.append(str(ROOT.parent/'完整Demo_Dify接入/tests'))
from fastapi.testclient import TestClient
from mock_travel.app import create_app
from test_demo import ready
from creation_harness import Harness,event

class CreationChainTests(unittest.TestCase):
    def test_explicit_new_application_confirmation_passes_all_creation_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            app=create_app(Path(directory)/'chain.db');client=TestClient(app);cid=client.post('/assistant/api/conversations',json={}).json()['id']
            user=app.state.assistant_manager.store.private_conversation(cid)['dify_user']
            payload=dict(applicantId='DEMO_EMP_001',departmentId='DEMO_DEPT_001',payerCompanyId='DEMO_COMPANY_001',remark='待变更原申请',dqydbg=None,trips=[dict(cityFrom='330100',cityTo='DEMO_BEIJING',dateFrom='2026-10-01',dateTo='2026-10-01',tool='火车-二等座'),dict(cityFrom='DEMO_BEIJING',cityTo='330100',dateFrom='2026-10-05',dateTo='2026-10-05',tool='火车-二等座')])
            a=app.state.lifecycle.document(app.state.store.create(payload,'base')['data']['applicationId'])
            for action in ['start','complete']:a=app.state.lifecycle.approve(a['applicationId'],action,'approval-'+action,a['version'])['document']
            lifecycle_draft=app.state.lifecycle_assistant.prepare(cid,a['applicationId'],'change')['draft']
            state,_,_,_=ready();h=Harness(client,user)
            after,answer=h.execute('确认提交新申请',event(intent='SUBMIT'),state)
            self.assertEqual(after['flow_state'],'SUBMITTED',answer)
            for node in ['LC_TURN','N05P','N10','H04','N13']:self.assertIn(node,h.trace)
            self.assertEqual(len(h.creates),1)
            self.assertEqual(app.state.lifecycle_assistant.view(cid)['draft'],lifecycle_draft)
            self.assertEqual(h.creates[0][1]['remark'],state['draft']['reason'])
            # 同一条归一化链仍必须拒绝创建草稿的旧确认版本。
            state['confirmation']['revision']=0
            rejected,answer=h.execute('确认提交新申请',event(intent='SUBMIT'),state)
            self.assertNotEqual(rejected['flow_state'],'SUBMITTED')
            self.assertIn('N10',h.trace)
            self.assertEqual(len(h.creates),1)
            self.assertEqual(app.state.lifecycle_assistant.view(cid)['draft'],lifecycle_draft)

if __name__=='__main__':unittest.main()
