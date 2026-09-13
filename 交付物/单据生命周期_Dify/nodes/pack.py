"""Dify Code 纯函数：只打包允许字段，身份、请求号、确认来自系统与 context。"""
import json
import re

INTENTS={'CREATE_FLOW','QUERY','DETAIL','WITHDRAW','VOID','CHANGE','EDIT','RESUBMIT','CONFIRM','CANCEL','HELP'}
ALLOWED={'intent','reference','resultIndex','filter','patch'}

def main(command_json,context_json,user,query,run_id):
    error={'valid':'false','body':'','reply':'本轮意图或上下文未能可靠读取，已有草稿仍保留。请重新描述操作；若上轮已提交，请先按原请求号核对回执。'}
    try:
        command=json.loads(command_json); context=json.loads(context_json)
        if not isinstance(context,dict) or 'draft' not in context: return error
        if not isinstance(command,dict) or set(command)-ALLOWED or command.get('intent') not in INTENTS: return error
        if 'reference' in command and (not isinstance(command['reference'],str) or not command['reference'].strip()): return error
        if 'resultIndex' in command and (type(command['resultIndex']) is not int or not 1<=command['resultIndex']<=100): return error
        for key in ('filter','patch'):
            if key in command and not isinstance(command[key],dict): return error
        if not isinstance(user,str) or not 1<=len(user)<=128 or not isinstance(run_id,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,118}',run_id): return error
        draft=context.get('draft')
        if command['intent']=='CONFIRM' and draft:
            command['confirmation']={'draftId':draft['id'],'revision':draft['revision'],'fingerprint':draft['fingerprint']}
        body=dict(user=user,query=query,command=command,clientRequestId='lifecycle-'+run_id)
        return dict(valid='true',body=json.dumps(body,ensure_ascii=False,separators=(',',':')),reply='')
    except (ValueError,TypeError,KeyError): return error
