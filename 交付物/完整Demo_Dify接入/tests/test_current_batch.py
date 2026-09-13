"""本批失败的确定性回归；模型事件为夹具，真实通道证据另存。"""
import copy
import json
import unittest
import yaml
from test_demo import ROOT, CAT, dump, run, envelope, context
from graph_harness import event, change, add


def load(query, state=None):
    data = {'employeeContext': CAT['employee_context'](), 'transportOptions': CAT['transport_options'](),
            'cityNames': [x['data']['cityName'] for x in CAT['CITIES']] + ['昆山']}
    return run('N02', query=query, cv_session=dump(state or {}), demo_reference_date='2026-09-13',
               run_id='batch-' + query, api_body=envelope(data))


def turn(query, parsed, state=None):
    ctx = load(query, state)
    plan = run('N04', parsed=parsed, query=query, state_json=ctx['state_json'], context_json=ctx['context_json'])
    if plan['status'] != 'OK':
        plan = run('R03', query=query, state_json=ctx['state_json'], context_json=ctx['context_json'],
                   repair_input_json=plan['repair_input_json'])
    run('N05U', plan_json=plan['plan_json'])
    candidate = run('N06', state_json=ctx['state_json'], plan_json=plan['plan_json'], context_json=ctx['context_json'])
    queries = json.loads(run('C01', **candidate, context_json=ctx['context_json'])['body'])['queries']
    checked = run('N07', **candidate, context_json=ctx['context_json'],
                  api_body=envelope({'items': [{'query': q, 'matches': CAT['query_cities'](q)} for q in queries]}))
    result = run('N09', state_json=ctx['state_json'], plan_json=plan['plan_json'], checked_json=checked['checked_json'], context_json=checked['context_json'])
    run('N12', result_json=result['result_json'])
    return json.loads(result['result_json'])


class CurrentBatchTests(unittest.TestCase):
    def test_complete_chinese_day_offset_and_large_values(self):
        import runpy
        offset = runpy.run_path(str(ROOT / 'common/input_rules.py'))['return_day_offset']
        for text, days in [('十二天后回来', 12), ('二十一天后回来', 21), ('两天后回来', 2),
                           ('一百零二天后回来', None), ('102天后回来', None)]:
            with self.subTest(text=text):
                self.assertEqual(offset(text), days)

    def test_start_with_facts_still_guards_unconfirmed_holiday(self):
        q = '国庆假期结束后去上海拜访客户，两天后回来'
        e = event([change('reason', '拜访客户', q), change('all_transport', '火车-二等座', q)],
                  [add('NEW1', '上海', '2026-10-08', q), add('NEW2', '杭州', '2026-10-10', q, 'RETURN')], intent='START')
        state = turn(q, e)['state']
        self.assertEqual([t['depart_date']['value'] for t in state['draft']['trips']], ['', ''])
        self.assertFalse(state['confirmation'])

    def test_holiday_word_in_reason_is_not_a_date_edit(self):
        q = '2026-09-20杭州去上海拜访客户，2026-09-22回杭州，高铁二等座'
        e = event([change('reason', '拜访客户', q), change('all_transport', '火车-二等座', q)],
                  [add('NEW1', '上海', '2026-09-20', q), add('NEW2', '杭州', '2026-09-22', q, 'RETURN')])
        state = turn(q, e)['state']
        q2 = '事由改成节后客户回访'
        final = turn(q2, event([change('reason', '节后客户回访', q2)]), state)['state']
        self.assertEqual(final['flow_state'], 'READY_TO_CONFIRM')
        self.assertEqual([t['depart_date']['value'] for t in final['draft']['trips']], ['2026-09-20', '2026-09-22'])

    def test_empty_structured_output_still_preserves_original(self):
        q = '周五杭州去上海拜访客户，当天回，高铁二等座'
        result = turn(q, {})
        self.assertEqual(result['state']['draft'], {})
        self.assertEqual(result['state']['dialogue']['recovery']['error_code'], 'TOP_LEVEL_KEYS')
        self.assertFalse(result['state']['confirmation'])

    def test_empty_consultation_does_not_claim_existing_draft(self):
        result = turn('你可以帮我做什么？', event(intent='ASK'))
        self.assertNotIn('已保留当前草稿', result['reply_text'])
        self.assertIn('日期', result['reply_text'])
        self.assertFalse(result['state']['draft'])

    def test_two_trips_kept_for_business_validation(self):
        q = '2026-09-20 杭州去上海，2026-09-21 上海回杭州，2026-09-22 杭州去北京，2026-09-23 北京回杭州，客户巡访，飞机经济舱'
        e = event([change('reason', '客户巡访', q), change('all_transport', '飞机-经济舱', q)],
                  [add('NEW1', '上海', '2026-09-20', q), add('NEW2', '杭州', '2026-09-21', q, 'RETURN'),
                   add('NEW3', '北京', '2026-09-22', q), add('NEW4', '杭州', '2026-09-23', q, 'RETURN')])
        result = turn(q, e)['state']
        self.assertEqual(result['draft'].get('reason'), '客户巡访')
        self.assertEqual(len(result['draft']['trips']), 4)
        self.assertIn('EARLY_RETURN', [x['code'] for x in result['pending']])
        self.assertFalse(result['confirmation'])

    def test_explicit_route_restatement_has_failed_fact_context(self):
        old = '2026-09-20 杭州去上海，2026-09-21 上海回杭州，2026-09-22 杭州去北京，2026-09-23 北京回杭州，客户巡访，飞机经济舱'
        state = turn(old, {})['state']
        q = '这张先只保留 2026-09-20 杭州去上海、2026-09-21 上海回杭州'
        model = json.loads(load(q, state)['llm_input_json'])
        self.assertEqual(model['recovery_context'].get('failed_query'), old)
        # 只有当前明确收窄路线，才能恢复上轮未记录的事由/交通。
        e = event([change('reason', '客户巡访', q), change('all_transport', '飞机-经济舱', q)],
                  [add('NEW1', '上海', '2026-09-20', q), add('NEW2', '杭州', '2026-09-21', q, 'RETURN')])
        e['clarification_resolutions'] = [{'question_id': state['dialogue']['recovery']['id'], 'evidence': q}]
        result = turn(q, e, state)['state']
        self.assertEqual(result['dialogue']['recovery'], {})
        self.assertEqual(result['draft']['reason'], '客户巡访')
        self.assertEqual(len(result['draft']['trips']), 2)
        self.assertEqual(result['flow_state'], 'READY_TO_CONFIRM')
        self.assertEqual(result['last_submission'], {})

    def test_unrelated_change_cannot_clear_failed_turn(self):
        state = turn('2026-09-20去上海，确认提交', {})['state']
        q = '事由改成培训'
        self.assertNotIn('failed_query', json.loads(load(q, state)['llm_input_json'])['recovery_context'])
        result = turn(q, event([change('reason', '培训', q)]), state)['state']
        self.assertTrue(result['dialogue']['recovery'])
        self.assertFalse(result['confirmation'])
        self.assertFalse(result['last_submission'])

    def test_holiday_guess_is_removed_and_offset_waits_for_anchor(self):
        q = '国庆假期结束后去上海拜访客户，两天后回来'
        # 即使模型猜了 10 月 8 日，也必须只保留明确事实。
        e = event([change('reason', '拜访客户', q), change('all_transport', '火车-二等座', q)],
                  [add('NEW1', '上海', '2026-10-08', q), add('NEW2', '杭州', '2026-10-10', q, 'RETURN')])
        state = turn(q, e)['state']
        self.assertEqual([t['depart_date']['value'] for t in state['draft']['trips']], ['', ''])
        self.assertIn('具体出发日期', state['last_question'])
        self.assertFalse(state['confirmation'])
        q2 = '2026-10-09出发'
        e2 = event(trips=[{'op': 'UPDATE', 'trip_id': 'T1', 'after_id': '', 'kind': '', 'evidence': q2,
                          'updates': [change('depart_date', '2026-10-09', q2)]}])
        e2['clarification_resolutions'] = [{'question_id': state['draft']['open_clarifications'][0]['id'], 'evidence': q2}]
        final = turn(q2, e2, state)['state']
        self.assertEqual([t['depart_date']['value'] for t in final['draft']['trips']], ['2026-10-09', '2026-10-11'])
        self.assertEqual(final['flow_state'], 'READY_TO_CONFIRM')

    def test_explicit_past_dates_are_unchanged(self):
        q = '2025-06-10杭州去上海拜访客户，2025-06-12回杭州，高铁二等座'
        e = event([change('reason', '拜访客户', q), change('all_transport', '火车-二等座', q)],
                  [add('NEW1', '上海', '2025-06-10', q), add('NEW2', '杭州', '2025-06-12', q, 'RETURN')])
        state = turn(q, e)['state']
        self.assertEqual([t['depart_date']['value'] for t in state['draft']['trips']], ['2025-06-10', '2025-06-12'])
        self.assertEqual(state['flow_state'], 'READY_TO_CONFIRM')

    def test_parser_models_explicitly_disable_thinking(self):
        doc = yaml.safe_load((ROOT / '差旅申请助手-完整Demo-可导入.yml').read_text())
        for n in doc['workflow']['graph']['nodes']:
            if n['data']['title'].split('-')[0] in ('N03', 'R01'):
                self.assertIs(n['data']['model']['completion_params'].get('thinking'), False)
