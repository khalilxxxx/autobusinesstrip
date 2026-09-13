import copy
import json


def finish(gate_json, api_body, status_code):
    gate=json.loads(gate_json)
    state=copy.deepcopy(gate['state'])
    status='UNKNOWN'
    message='暂时无法确认模拟创建结果。草稿与请求号已保留；请稍后再次确认，系统会先查询同一请求号的回执。'
    data={}
    try:
        http=int(status_code)
        response=json.loads(api_body)
        data=response.get('data') or {}
        correlated=data.get('clientRequestId')==gate['request_id']
        valid=correlated and data.get('action')=='AI_CREATE' and data.get('demoOnly') is True
        if http==200 and response.get('code')=='SUCCESS' and valid and all(isinstance(data.get(k),str) and data[k] for k in ('applicationId','applicationNo','createdAt')):
            status='SUCCEEDED'
            message='本地模拟系统已创建申请。'
        elif http==200 and response.get('code')=='MOCK_SUBMIT_FAILED' and valid:
            status='FAILED'
            message=(response.get('message') or {}).get('text') or '模拟系统明确返回创建失败。'
        elif 400<=http<500 and http!=404:
            # 请求拒绝/冲突不是成功，也不是本请求的确定业务回执；先保留UNKNOWN以便查证。
            detail=(response.get('message') or {}).get('text') if isinstance(response.get('message'),dict) else ''
            message='模拟接口拒绝请求，当前创建结果仍需核对。'+(detail or str(response.get('detail') or response.get('code') or ''))+'。请保留草稿并重试查询回执。'
    except (ValueError,TypeError,AttributeError):
        pass
    number=data.get('applicationNo','') if status=='SUCCEEDED' else ''
    application_id=data.get('applicationId','') if status=='SUCCEEDED' else ''
    if status=='SUCCEEDED':
        reply='### 模拟提交成功\n\n模拟单号：**'+number+'**\n\n差旅日期：'+gate['date_start']+' 至 '+gate['date_end']+'\n\n已创建本地模拟单据，可在模拟系统中查看。'
    elif status=='FAILED':reply='### 模拟提交失败\n\n'+str(message)+'\n\n草稿与当前确认版本已保留；修复失败原因后可再次单独回复“确认提交”。'
    else:reply=message
    record={'demo_only':'Y',**gate['identity'],'application_no':number,'application_id':application_id,
            'request_id':gate['request_id'],'status':status,'message':str(message),'reply_text':reply,
            'date_start':gate['date_start'],'date_end':gate['date_end'],'created_at':data.get('createdAt','') if status=='SUCCEEDED' else '',
            'retry_count':gate['retry_count'],'demo_request':gate['payload']}
    state.update(draft=gate['draft'],last_submission=record,flow_state='SUBMITTED' if status=='SUCCEEDED' else 'READY_TO_CONFIRM',pending=[],last_question='')
    if status=='SUCCEEDED' and not any(x.get('application_no')==number for x in state['history']):
        state['history'].append({'applicant_id':gate['draft']['applicant_id'],'application_no':number,'date_start':gate['date_start'],'date_end':gate['date_end'],'blocking':False})
    return {'result_json':json.dumps({'state':state,'reply_text':reply},ensure_ascii=False,separators=(',', ':'))}



def main(gate_json: str) -> dict:
    return finish(gate_json, '', 0)
