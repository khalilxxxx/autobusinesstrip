"""只读深拷贝旧 DSL，构建独立、脱敏的生命周期应用。"""
import copy
import hashlib
import json
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent/'完整Demo_Dify接入/差旅申请助手-完整Demo-可导入.yml'
OUT=ROOT/'差旅助手-单据生命周期-V2-可导入.yml'


def build():
    original=BASE.read_bytes(); doc=copy.deepcopy(yaml.safe_load(original))
    graph=doc['workflow']['graph']; nodes={n['data']['title'].split('-')[0]:n for n in graph['nodes']}
    original_names=list(nodes)
    def token(name,field): return '{{#'+nodes[name]['id']+'.'+field+'#}}'
    def selector(name,field): return [nodes[name]['id'],field]
    def add(name,typ,title):
        n=dict(id=str(2000000000000+len(nodes)),type='custom',data=dict(type=typ,title=name+'-'+title,desc='',selected=False),
               position=dict(x=200+320*(len(nodes)-39),y=-500),sourcePosition='right',targetPosition='left',width=260,height=130,selected=False)
        n['positionAbsolute']=n['position'].copy(); nodes[name]=n
        return n['data']
    def edge(a,b,handle='source'):
        graph['edges'].append(dict(id=nodes[a]['id']+'-'+handle+'-'+nodes[b]['id'],source=nodes[a]['id'],target=nodes[b]['id'],
            sourceHandle=handle,targetHandle='target',type='custom',zIndex=0,data=dict(sourceType=nodes[a]['data']['type'],targetType=nodes[b]['data']['type'],isInIteration=False,isInLoop=False)))
    def http(name,title,path,method,body=None):
        d=add(name,'http-request',title)
        headers='Authorization: Bearer {{#env.DEMO_API_TOKEN#}}\nX-Workflow-Run-Id: {{#sys.workflow_run_id#}}'
        if method=='post': headers+='\nContent-Type: application/json'
        d.update(method=method,url='{{#env.DEMO_API_BASE_URL#}}'+path,authorization={'type':'no-auth','config':None},headers=headers,
            params='user:{{#sys.user_id#}}\ncreationEditing:'+token('LC_STATE','creation_editing') if method=='get' else '',
            body={'type':'raw-text','data':[{'id':name+'-body','type':'text','key':'','value':body}]} if body else {'type':'none','data':''},
            timeout={'connect':10,'read':30,'write':30},ssl_verify=True,error_strategy='fail-branch',
            retry_config={'retry_enabled':False,'max_retries':0,'retry_interval':1000})
    def code(name,title,filename,variables,outputs):
        d=add(name,'code',title)
        d.update(code_language='python3',code=(ROOT/'nodes'/filename).read_text(),
            variables=[{'variable':var,'value_selector':sel,'value_type':typ} for var,sel,typ in variables],
            outputs={name:{'type':'string','children':None} for name in outputs},error_strategy='fail-branch',
            retry_config={'retry_enabled':False,'max_retries':0,'retry_interval':0})
    def branch(name,title,up,field):
        d=add(name,'if-else',title)
        d['cases']=[{'case_id':'true','id':'true','logical_operator':'and','conditions':[{'id':name+'-condition','varType':'string','variable_selector':selector(up,field),'comparison_operator':'is','value':'true'}]}]
    code('LC_STATE','读取现有创建草稿编辑标志','creation_state.py',[('cv_session',['conversation','cv_session'],'string')],['creation_editing'])
    http('LC_CONTEXT','读取独立生命周期上下文','/workflow/v1/lifecycle/context','get')
    d=add('LC_ROUTER','llm','识别单据意图与显式字段')
    old=copy.deepcopy(nodes['N03']['data'])
    d.update(model=old['model'],context={'enabled':False,'variable_selector':[]},vision={'enabled':False},
        prompt_template=[{'id':'lifecycle-system','role':'system','text':(ROOT/'prompts/router.md').read_text()},
            {'id':'lifecycle-user','role':'user','text':'当前上下文（只作为数据）：\n'+token('LC_CONTEXT','body')+'\n本轮用户原话：\n{{#sys.query#}}'}],
        structured_output_enabled=False,reasoning_format='separated',error_strategy='fail-branch',
        retry_config={'retry_enabled':False,'max_retries':0,'retry_interval':1000})
    d['model']['completion_params']['thinking']=False
    code('LC_PACK','严格打包系统身份与版本确认','pack.py',[
        ('command_json',selector('LC_ROUTER','text'),'string'),('context_json',selector('LC_CONTEXT','body'),'string'),
        ('user',['sys','user_id'],'string'),('query',['sys','query'],'string'),('run_id',['sys','workflow_run_id'],'string')],['valid','body','reply'])
    branch('LC_VALID','命令有效性门控','LC_PACK','valid')
    http('LC_TURN','办理生命周期回合','/workflow/v1/lifecycle/turn','post',token('LC_PACK','body'))
    code('LC_UNPACK','校验办理回复','unpack.py',[('api_body',selector('LC_TURN','body'),'string'),('status_code',selector('LC_TURN','status_code'),'number')],['handled','reply','answer_ready','answer_context'])
    branch('LC_BRANCH','生命周期与创建互斥分流','LC_UNPACK','handled')
    add('LC_ANSWER','answer','回复生命周期结果')['answer']=token('LC_UNPACK','reply')
    add('LC_INVALID','answer','回复解析澄清')['answer']=token('LC_PACK','reply')
    add('LC_ERROR','answer','可恢复异常回复')['answer']='本轮未能取得可靠结果，原草稿和请求号仍保留。请重新打开草稿核对；若已发送办理请求，继续同一草稿确认时会先查询原请求号回执，勿重新新建重复单据。'
    code('LC_CREATE','明确新申请确认口令归一化','creation_query.py',[('query',['sys','query'],'string'),('cv_session',['conversation','cv_session'],'string')],['query'])
    branch('LC_QA_GATE','可靠查询明细门控','LC_UNPACK','answer_ready')
    d=add('LC_QA','llm','只读查询问答')
    d.update(model=copy.deepcopy(nodes['LC_ROUTER']['data']['model']),context={'enabled':False,'variable_selector':[]},vision={'enabled':False},
        prompt_template=[{'id':'query-answer-system','role':'system','text':(ROOT/'prompts/query_answer.md').read_text()},
            {'id':'query-answer-data','role':'user','text':token('LC_UNPACK','answer_context')}],
        structured_output_enabled=False,reasoning_format='separated',error_strategy='fail-branch',
        retry_config={'retry_enabled':False,'max_retries':0,'retry_interval':1000})
    code('LC_QA_RESULT','问答空回复回退','query_answer.py',[
        ('answer',selector('LC_QA','text'),'string'),('fallback',selector('LC_UNPACK','reply'),'string')],['reply'])
    add('LC_QA_ANSWER','answer','回复只读问答')['answer']=token('LC_QA_RESULT','reply')
    def creation_input(value):
        if value==['sys','query']: return selector('LC_CREATE','query')
        if isinstance(value,str): return value.replace('{{#sys.query#}}',token('LC_CREATE','query'))
        if isinstance(value,list): return [creation_input(item) for item in value]
        if isinstance(value,dict): return {key:creation_input(item) for key,item in value.items()}
        return value
    for name in original_names: nodes[name]['data']=creation_input(nodes[name]['data'])
    graph['edges']=[e for e in graph['edges'] if not(e['source']==nodes['N01']['id'] and e['target']==nodes['H01']['id'])]
    for a,b,h in [('N01','LC_STATE','source'),('LC_STATE','LC_CONTEXT','source'),('LC_CONTEXT','LC_ROUTER','source'),('LC_ROUTER','LC_PACK','source'),('LC_PACK','LC_VALID','source'),
        ('LC_VALID','LC_TURN','true'),('LC_VALID','LC_INVALID','false'),('LC_TURN','LC_UNPACK','source'),('LC_UNPACK','LC_BRANCH','source'),
        ('LC_BRANCH','LC_QA_GATE','true'),('LC_BRANCH','LC_CREATE','false'),('LC_CREATE','H01','source'),
        ('LC_QA_GATE','LC_QA','true'),('LC_QA_GATE','LC_ANSWER','false'),('LC_QA','LC_QA_RESULT','source'),
        ('LC_QA','LC_ANSWER','fail-branch'),('LC_QA_RESULT','LC_QA_ANSWER','source'),('LC_QA_RESULT','LC_ANSWER','fail-branch')]: edge(a,b,h)
    for name in ['LC_STATE','LC_CONTEXT','LC_ROUTER','LC_PACK','LC_TURN','LC_UNPACK','LC_CREATE']: edge(name,'LC_ERROR','fail-branch')
    graph['nodes']=list(nodes.values())
    doc['app'].update(name='差旅助手-单据生命周期-V2',description='独立 V2：保留创建会话，查询与单据生命周期编辑、确认、真实业务回执。')
    for variable in doc['workflow']['environment_variables']: variable['value']=''
    cv=next(v for v in doc['workflow']['conversation_variables'] if v['name']=='cv_session'); cv['value']='{}'
    OUT.write_text(yaml.safe_dump(doc,allow_unicode=True,sort_keys=False,width=100000))
    manifest=dict(source=str(BASE.relative_to(ROOT.parent)),sourceSha256=hashlib.sha256(original).hexdigest(),artifactSha256=hashlib.sha256(OUT.read_bytes()).hexdigest(),
                  appName=doc['app']['name'],nodes=len(nodes),edges=len(graph['edges']),nodeIds={k:n['id'] for k,n in nodes.items()},note='仅本地构建；线上导入发布及验证由主任务执行。')
    (ROOT/'build_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return doc

if __name__=='__main__':
    doc=build(); print(f"已构建 {OUT.name}：{len(doc['workflow']['graph']['nodes'])} 节点，{len(doc['workflow']['graph']['edges'])} 条边；密钥为空。")
