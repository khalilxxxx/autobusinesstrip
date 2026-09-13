import copy
import hashlib
import json
from datetime import datetime


def main(state_json: str, plan_json: str, checked_json: str, context_json: str) -> dict:
    state, plan, checked, ctx = (json.loads(x) for x in (state_json, plan_json, checked_json, context_json))
    next_state = copy.deepcopy(state)
    def encode(value): return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    def output(reply):
        return {'route':'RESULT', 'result_json':encode({'state':next_state,'reply_text':reply}),
                'gate_json':'{}', 'request_id':'', 'draft_id':'', 'revision':'', 'body':'{}'}
    def reject(message):return output('本轮未发起新的模拟创建，草稿已保留。' + message)
    command=plan['query'].strip().rstrip('。.!！').strip()
    if plan['action'] != 'SUBMIT' or command != '确认提交' or plan['event']['basic_updates'] or plan['event']['trip_operations']:
        return reject('请核对当前确认单，再单独回复“确认提交”。')
    draft=checked['draft']
    if state['dialogue']['recovery'] or checked['dialogue']['recovery']:
        return reject('还有未处理的恢复事项，请先处理并核对确认单。')
    if not draft:return reject('当前没有完整草稿。')
    fp=hashlib.sha256(json.dumps(draft,ensure_ascii=False,sort_keys=True,separators=(',', ':')).encode()).hexdigest()
    last=state['last_submission']
    identity={'draft_id':draft['draft_id'],'revision':draft['revision'],'fingerprint':fp}
    same=all(last.get(k)==v for k,v in identity.items())
    if state['flow_state']=='SUBMITTED':
        if same and last.get('status')=='SUCCEEDED' and last.get('application_no'):
            return output('这张申请已模拟提交，本轮没有重复创建。\n\n'+last['reply_text'])
        return reject('已保存提交记录与当前草稿或新接口回执不一致，请检查原记录。')
    if state['flow_state']!='READY_TO_CONFIRM' or checked['issues'] or checked['merge_error'] or state['pending']:
        return reject('申请还有缺失或规则问题，请补充或查看确认单。')
    if not all(state['confirmation'].get(k)==v for k,v in identity.items()):
        q='请回复“查看确认单”，核对当前版本后再提交。'
        next_state.update(flow_state='COLLECTING',confirmation={},pending=[{'id':'CONFIRMATION_STALE','code':'CONFIRMATION_STALE','target':'','field':'confirmation','question':q,'priority':0}],last_question=q)
        return reject(q)
    if not checked['date_start'] or not checked['date_end'] or checked['date_end']<checked['date_start']:
        return reject('整单日期尚未有效确定。')
    retry=int(last.get('retry_count',0)) if same else 0
    if same and last.get('status')=='FAILED':retry+=1
    request_id='DEMO-REQ-'+hashlib.sha256((draft['draft_id']+':'+str(draft['revision'])+':'+fp+':'+str(retry)).encode()).hexdigest()[:40]
    if same and last.get('status')=='UNKNOWN':
        request_id=last['request_id']
    employee=ctx['employee']
    payload={'remark':draft['reason'],'dqydbg':'Y' if draft['travel_type']=='SHORT_TERM' else None,
             'applicantId':employee['id'],'departmentId':employee['department_id'],'payerCompanyId':employee['payer_company_id'],
             'trips':[{'dateFrom':t['depart_date']['value'],'dateTo':t['arrive_date']['value'],'cityFrom':t['resolved_from']['code'],
                       'cityTo':t['resolved_to']['code'],'tool':t['resolved_transport']['code']} for t in draft['trips']]}
    gate={'state':next_state,'draft':draft,'identity':identity,'request_id':request_id,'retry_count':retry,
          'date_start':checked['date_start'],'date_end':checked['date_end'],'payload':payload}
    return {'route':'HTTP','result_json':'','gate_json':encode(gate),'request_id':request_id,
            'draft_id':draft['draft_id'],'revision':str(draft['revision']),'body':encode(payload)}
