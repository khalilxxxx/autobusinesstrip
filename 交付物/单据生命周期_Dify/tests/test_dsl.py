"""执行节点纯函数及构建后的实际图；禁止生命周期路径落入创建状态赋值。"""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent/'完整Demo_Dify接入/差旅申请助手-完整Demo-可导入.yml'

class DSLTests(unittest.TestCase):
    def load(self,name):
        path=ROOT/name
        self.assertTrue(path.exists(),f'尚未实现 {name}')
        spec=importlib.util.spec_from_file_location(path.stem,path); module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_build_isolated_graph_and_valid_selectors(self):
        before=OLD.read_bytes(); old=yaml.safe_load(before)
        doc=self.load('build_dsl.py').build(); graph=doc['workflow']['graph']
        self.assertEqual(before,OLD.read_bytes())
        self.assertNotEqual(doc['app']['name'],old['app']['name'])
        self.assertTrue(all(v['value']=='' for v in doc['workflow']['environment_variables']))
        cv=next(v for v in doc['workflow']['conversation_variables'] if v['name']=='cv_session')
        self.assertEqual(json.loads(cv['value']),{})
        nodes={n['id']:n for n in graph['nodes']}; names={n['data']['title'].split('-')[0]:n['id'] for n in nodes.values()}
        edges=graph['edges']; adjacency={n:[] for n in nodes}
        for edge in edges:
            self.assertIn(edge['source'],nodes); self.assertIn(edge['target'],nodes)
            adjacency[edge['source']].append(edge['target'])
        def descendants(start):
            seen=set(); pending=[start]
            while pending:
                node=pending.pop()
                if node in seen: continue
                seen.add(node); pending.extend(adjacency[node])
            return seen
        handled=next(e['target'] for e in edges if e['source']==names['LC_BRANCH'] and e['sourceHandle']=='true')
        fallback=next(e['target'] for e in edges if e['source']==names['LC_BRANCH'] and e['sourceHandle']=='false')
        self.assertNotIn(names['N13'],descendants(handled)); self.assertNotIn(names['H01'],descendants(handled))
        self.assertEqual(fallback,names['H01'])
        for n in nodes.values():
            data=n['data']
            if data['type']=='code':
                tree=ast.parse(data['code'])
                self.assertFalse(any(isinstance(a,(ast.Import,ast.ImportFrom)) and any(x.name.split('.')[0] in {'requests','httpx','urllib','socket','subprocess'} for x in a.names) for a in ast.walk(tree)))
                for v in data.get('variables',[]):
                    selector=v['value_selector']; self.assertTrue(selector[0] in nodes or selector[0] in {'sys','env','conversation'})
                    if selector[0] in nodes and nodes[selector[0]]['data']['type']=='code': self.assertIn(selector[1],nodes[selector[0]]['data']['outputs'])
        llm=nodes[names['LC_ROUTER']]['data']
        self.assertEqual(llm['model']['name'],'deepseek-v4-flash')
        self.assertIs(llm['model']['completion_params']['thinking'],False)

    def test_creation_flag_from_cv_session_without_writing_it(self):
        module=self.load('nodes/creation_state.py')
        self.assertEqual(module.main('{}'),{'creation_editing':'false'})
        self.assertEqual(module.main('{"draft":{"draft_id":"d1"},"flow_state":"COLLECTING"}'),{'creation_editing':'true'})
        self.assertEqual(module.main('{"draft":{"draft_id":"d1"},"flow_state":"SUBMITTED"}'),{'creation_editing':'false'})
        with self.assertRaises(ValueError): module.main('not json')

    def test_pack_context_confirmation_identity_and_malformed_command(self):
        module=self.load('nodes/pack.py')
        context=json.dumps({'draft':{'id':'d1','revision':2,'fingerprint':'fp'}})
        result=module.main('{"intent":"CONFIRM"}',context,'preview-user','确认提交变更','run-1')
        body=json.loads(result['body'])
        self.assertEqual(body['command']['confirmation'],{'draftId':'d1','revision':2,'fingerprint':'fp'})
        self.assertEqual(body['user'],'preview-user')
        self.assertEqual(body['clientRequestId'],'lifecycle-run-1')
        for value in ['not json','{"intent":"QUERY","user":"other"}','{"intent":"CONFIRM","confirmation":{"draftId":"forged"}}','{"intent":"APPROVE"}']:
            result=module.main(value,context,'real','查询','run-2')
            self.assertEqual(result['valid'],'false')
        self.assertEqual(module.main('{"intent":"QUERY"}','bad context','real','查询','run-3')['valid'],'false')

    def test_unpack_errors_never_enter_create_branch(self):
        module=self.load('nodes/unpack.py')
        for code,body in [(502,'oops'),(200,'{}'),(200,'{"handled":"false","reply":""}'),(200,'{"handled":true,"reply":""}')]:
            result=module.main(body,code)
            self.assertEqual(result['handled'],'true'); self.assertTrue(result['reply'])
        self.assertEqual(module.main('{"handled":false,"reply":""}',200),{'handled':'false','reply':''})
        self.assertEqual(module.main('{"handled":true,"reply":"查到2张单据"}',200),{'handled':'true','reply':'查到2张单据'})

if __name__=='__main__':unittest.main()
