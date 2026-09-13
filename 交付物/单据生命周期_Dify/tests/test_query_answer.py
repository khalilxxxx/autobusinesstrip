"""查询答案只消费本轮可靠明细，问答失败不能重新办理或进入创建链。"""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QueryAnswerTests(unittest.TestCase):
    def load(self, name):
        path = ROOT / name
        self.assertTrue(path.exists(), f'尚未实现 {name}')
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def context(self):
        return dict(question='9月13日我在哪里？', businessDate='2026-09-13', filters={}, total=5, shown=1,
                    cityNames={'HZ': '杭州', 'BJ': '北京'}, documents=[dict(
                        applicationId='a1', applicationNo='NO-1', status='S004', isEffective=True,
                        documentType='APPLICATION', request=dict(remark='客户拜访', trips=[
                            dict(dateFrom='2026-09-12', dateTo='2026-09-12', cityFrom='HZ', cityTo='BJ', tool='飞机'),
                            dict(dateFrom='2026-09-15', dateTo='2026-09-15', cityFrom='BJ', cityTo='HZ', tool='飞机')]))])

    def unpack(self, context, **overrides):
        body = dict(handled=True, reply='共5张，目前展示1张，详见卡片。', answerContext=context)
        body.update(overrides)
        return self.load('nodes/unpack.py').main(json.dumps(body, ensure_ascii=False), 200)

    def test_reliable_query_context_keeps_raw_trip_facts_and_page_scope(self):
        context = self.context()
        context['documents'][0]['locations'] = [{'explanation': '不应传递的预推理'}]
        context['documents'][0]['request']['stay'] = '不应传递的预推理'
        result = self.unpack(context)
        self.assertEqual(result.get('answer_ready'), 'true')
        actual = json.loads(result['answer_context'])
        self.assertEqual((actual['total'], actual['shown']), (5, 1))
        self.assertEqual(actual['documents'][0]['request']['trips'][1]['cityFrom'], 'BJ')
        self.assertEqual(actual['cityNames']['BJ'], '北京')
        self.assertNotIn('locations', actual['documents'][0])
        self.assertNotIn('stay', actual['documents'][0]['request'])

    def test_unreliable_context_falls_back_without_entering_qa(self):
        bad_contexts = [None, {}, {**self.context(), 'shown': 2}, {**self.context(), 'total': False},
                        {**self.context(), 'total': 0}, {**self.context(), 'businessDate': 'not-date'},
                        {**self.context(), 'documents': self.context()['documents'] * 4, 'shown': 4}]
        malformed = self.context(); malformed['documents'][0]['request']['trips'][0]['dateTo'] = 'tomorrow'
        bad_contexts.append(malformed)
        for index, context in enumerate(bad_contexts):
            with self.subTest(case=index):
                result = self.unpack(context)
                self.assertEqual(result.get('answer_ready'), 'false')
                self.assertEqual(result['reply'], '共5张，目前展示1张，详见卡片。')
                self.assertEqual(result['handled'], 'true')
        result = self.unpack(self.context(), handled=False, reply='')
        self.assertEqual(result.get('answer_ready'), 'false')
        self.assertEqual(result['handled'], 'false')

    def test_empty_result_is_valid_and_model_empty_output_uses_original_reply(self):
        context = self.context(); context.update(documents=[], total=0, shown=0)
        self.assertEqual(self.unpack(context).get('answer_ready'), 'true')
        module = self.load('nodes/query_answer.py')
        for value in ['', '   ', None, 12]:
            self.assertEqual(module.main(value, '共0张，详见卡片。'), {'reply': '共0张，详见卡片。'})
        self.assertEqual(module.main('按已批准行程，9月13日在北京。', 'fallback'),
                         {'reply': '按已批准行程，9月13日在北京。'})

    def test_qa_graph_has_no_path_to_business_http_or_state_assignment(self):
        doc = self.load('build_dsl.py').build()
        nodes = {n['data']['title'].split('-')[0]: n for n in doc['workflow']['graph']['nodes']}
        self.assertIn('LC_QA', list(nodes))
        edges = doc['workflow']['graph']['edges']
        by_id = {n['id']: n for n in nodes.values()}
        def target(name, handle):
            return [e['target'] for e in edges if e['source'] == nodes[name]['id'] and e['sourceHandle'] == handle]
        self.assertEqual(target('LC_BRANCH', 'true'), [nodes['LC_QA_GATE']['id']])
        self.assertEqual(target('LC_QA_GATE', 'true'), [nodes['LC_QA']['id']])
        self.assertEqual(target('LC_QA_GATE', 'false'), [nodes['LC_ANSWER']['id']])
        self.assertEqual(target('LC_QA', 'fail-branch'), [nodes['LC_ANSWER']['id']])
        self.assertEqual(target('LC_QA_RESULT', 'fail-branch'), [nodes['LC_ANSWER']['id']])
        pending = [nodes['LC_QA']['id']]; visited = set()
        while pending:
            current = pending.pop()
            if current in visited: continue
            visited.add(current)
            self.assertNotIn(by_id[current]['data']['type'], ['http-request', 'assigner'])
            pending.extend(e['target'] for e in edges if e['source'] == current)
        qa = nodes['LC_QA']['data']
        self.assertFalse(qa['retry_config']['retry_enabled'])
        self.assertEqual(qa['model']['name'], 'deepseek-v4-flash')
        self.assertIs(qa['model']['completion_params']['thinking'], False)


if __name__ == '__main__':
    unittest.main()
