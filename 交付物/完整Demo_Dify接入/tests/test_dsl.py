import inspect
import json
from pathlib import Path
import re
import runpy
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[1]
class DSLTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT/'差旅申请助手-完整Demo-可导入.yml').exists(),'尚未生成API接入DSL')
        self.doc=yaml.safe_load((ROOT/'差旅申请助手-完整Demo-可导入.yml').read_text());self.nodes={n['id']:n['data'] for n in self.doc['workflow']['graph']['nodes']}
    def test_all_selectors_and_signatures(self):
        outputs={'sys':{'query','workflow_run_id'},'env':{'DEMO_API_BASE_URL','DEMO_API_TOKEN'},'conversation':{'cv_session'}}
        for i,n in self.nodes.items():
            outputs[i]=set(n.get('outputs',{}))
            if n['type']=='start':outputs[i]|={v['variable'] for v in n['variables']}
            if n['type']=='llm':outputs[i]|={'text','structured_output','reasoning_content'}
            if n['type']=='http-request':outputs[i]|={'body','status_code','headers','files'}
            if n['type']=='variable-aggregator':outputs[i].add('output')
            if n['type']=='code':
                ns={};exec(n['code'],ns);self.assertEqual(set(inspect.signature(ns['main']).parameters),{v['variable'] for v in n['variables']})
        def visit(x):
            if isinstance(x,dict):
                for k,v in x.items():
                    if k in ('value_selector','variable_selector') and v:self.assertIn(v[1],outputs.get(v[0],set()),str(v))
                    visit(v)
            elif isinstance(x,list):
                if len(x)==2 and all(isinstance(v,str) for v in x) and x[0] in outputs:self.assertIn(x[1],outputs[x[0]],str(x))
                for v in x:visit(v)
            elif isinstance(x,str):
                for i,f in re.findall(r'\{\{#([^.{}]+)\.([^#{}]+)#\}\}',x):self.assertIn(f,outputs.get(i,set()),i+'.'+f)
        visit(self.doc['workflow'])
    def test_edge_handles_and_reachable(self):
        edges=self.doc['workflow']['graph']['edges'];reached={i for i,n in self.nodes.items() if n['type']=='start'}
        for e in edges:
            self.assertIn(e['source'],self.nodes);self.assertIn(e['target'],self.nodes)
            n=self.nodes[e['source']];handles={'source'}
            if n.get('error_strategy')=='fail-branch':handles.add('fail-branch')
            if n['type']=='if-else':handles={'false'}|{c['case_id'] for c in n['cases']}
            self.assertIn(e['sourceHandle'],handles)
        for _ in self.nodes:
            reached|={e['target'] for e in edges if e['source'] in reached}
        self.assertEqual(reached,set(self.nodes))
    def test_http_auth_and_body(self):
        http=[n for n in self.nodes.values() if n['type']=='http-request'];self.assertEqual(len(http),4)
        for n in http:
            self.assertIn('{{#env.DEMO_API_TOKEN#}}',n['headers']);self.assertIn('{{#sys.workflow_run_id#}}',n['headers'])
            if n['method']=='post':self.assertRegex(n['body']['data'][0]['value'],r'^\{\{#[^.]+\.body#\}\}$')
    def test_no_secrets_in_prompts(self):
        for n in self.nodes.values():
            if n['type']=='llm':self.assertNotIn('DEMO_API_TOKEN',json.dumps(n));self.assertEqual(n['model']['name'],'deepseek-v4-flash')
        self.assertTrue(all(v['value']=='' for v in self.doc['workflow']['environment_variables']))
    def test_single_state_writer(self):
        writers=[n for n in self.nodes.values() if n['type']=='assigner'];self.assertEqual(len(writers),1);self.assertTrue(writers[0]['title'].startswith('N13'))
if __name__=='__main__':unittest.main()
