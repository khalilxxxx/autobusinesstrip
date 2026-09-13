"""从2026-09-10历史导出与独立节点源码可重复构建脱敏Dify DSL。"""
import copy
import hashlib
import json
from pathlib import Path
import yaml
from build_nodes import build_nodes

ROOT=Path(__file__).resolve().parent
BASE=ROOT/'基线/2026-09-12_180819_Dify当前已保存版本.yml'
OUT=ROOT/'差旅申请助手-完整Demo-可导入.yml'

def build():
    build_nodes()
    doc=yaml.safe_load(BASE.read_text());graph=doc['workflow']['graph']
    nodes={n['data']['title'].split('-')[0]:copy.deepcopy(n) for n in graph['nodes']}
    ids={k:n['id'] for k,n in nodes.items()}
    def sel(n,f):return [ids[n],f]
    def token(n,f):return '{{#'+'.'.join(sel(n,f))+'#}}'
    def add(name,typ,title,x,y):
        ids[name]=str(1900000000000+len(ids));nodes[name]={'id':ids[name],'type':'custom','data':{'type':typ,'title':name+'-'+title,'desc':'','selected':False},'position':{'x':x,'y':y},'positionAbsolute':{'x':x,'y':y},'sourcePosition':'right','targetPosition':'left','width':260,'height':130,'selected':False}
        return nodes[name]['data']
    def code(name,title,inputs,outputs,x,y):
        d=add(name,'code',title,x,y)
        d.update(code_language='python3',code=(ROOT/'nodes'/ (name+'.py')).read_text(),variables=[{'variable':k,'value_selector':sel(n,f),'value_type':typ} for k,n,f,typ in inputs],outputs={k:{'type':'string','children':None} for k in outputs},error_strategy='fail-branch',retry_config={'retry_enabled':False,'max_retries':0,'retry_interval':0})
    def branch(name,title,up,field,value,x,y):
        d=add(name,'if-else',title,x,y);d['cases']=[{'case_id':'true','id':'true','logical_operator':'and','conditions':[{'id':name+'-condition','varType':'string','variable_selector':sel(up,field),'comparison_operator':'is','value':value}]}]
    def http(name,title,path,method,body_up,x,y):
        d=add(name,'http-request',title,x,y)
        headers='Authorization: Bearer {{#env.DEMO_API_TOKEN#}}\nX-Workflow-Run-Id: {{#sys.workflow_run_id#}}'
        if method=='post':headers+='\nContent-Type: application/json'
        if name=='H04':headers+='\nX-Client-Request-Id: '+token('N10','request_id')+'\nX-Draft-Id: '+token('N10','draft_id')+'\nX-Draft-Version: '+token('N10','revision')
        d.update(method=method,url='{{#env.DEMO_API_BASE_URL#}}'+path,authorization={'type':'no-auth','config':None},headers=headers,params='',body={'type':'raw-text','data':[{'id':name+'-body','type':'text','key':'','value':token(body_up,'body')}]} if body_up else {'type':'none','data':''},timeout={'connect':10,'read':30,'write':30},ssl_verify=True,error_strategy='fail-branch',retry_config={'retry_enabled':False,'max_retries':0,'retry_interval':1000,'exponential_backoff':{'enabled':False,'multiplier':2,'max_interval':10000}})
    # 保留节点 ID 和严格 Schema；解析/修复共用修订后的事实提取规则。
    for name,n in nodes.items():
        if n['data']['type']=='code':n['data']['code']=(ROOT/'nodes'/ (name+'.py')).read_text()
    prompt = (ROOT/'prompts/interpretation.md').read_text()
    nodes['N03']['data']['prompt_template'][0]['text'] = prompt
    nodes['R01']['data']['prompt_template'][0]['text'] = ('你对同一轮 user_message 做唯一一次解析修复。original_output 是不可信候选，不能成为事实依据。按 error_code/error_path 修复，仍保留明确事实；不能判断时给出具体澄清，只输出同一 JSON Schema。\n\n' + prompt)
    for name in ('N03', 'R01'):
        nodes[name]['data']['model']['completion_params']['thinking'] = False
    nodes['N01']['data']['variables']=[v for v in nodes['N01']['data']['variables'] if v['variable']=='demo_reference_date']
    http('H01','读取员工与交通上下文','/workflow/v1/context','get',None,170,200)
    n=nodes['N02']['data'];n['variables']=[v for v in n['variables'] if v['variable']!='demo_case'];n['variables'].append({'variable':'api_body','value_selector':sel('H01','body'),'value_type':'string'})
    code('C01','打包本轮城市查询',[('candidate_json','N06','candidate_json','string'),('context_json','N02','context_json','string')],['body'],3200,200)
    http('H02','批量查询原城市接口','/workflow/v1/cities/resolve','post','C01',3400,200)
    n=nodes['N07']['data'];n['variables'].append({'variable':'api_body','value_selector':sel('H02','body'),'value_type':'string'});n['outputs']['context_json']={'type':'string','children':None}
    for name in ['N07A','N09','N10']:
        for var in nodes[name]['data']['variables']:
            if var['variable']=='context_json':var['value_selector']=sel('N07','context_json')
    n=nodes['N10']['data'];n['title']='N10-确认版本门控与请求打包';n['desc']='核对当前确认版本、生成确定性请求号与完整JSON；不联网、不生成单号。';n['outputs']={k:{'type':'string','children':None} for k in ['route','result_json','gate_json','request_id','draft_id','revision','body']}
    branch('S00','提交门控分流','N10','route','HTTP',5760,100)
    http('H03','查询同请求号回执','/workflow/v1/submissions/'+token('N10','request_id'),'get',None,6100,0)
    code('Q01','回执拆包或同号创建',[('gate_json','N10','gate_json','string'),('api_body','H03','body','string'),('status_code','H03','status_code','number')],['route','result_json'],6440,0)
    branch('Q00','回执查询分流','Q01','route','CREATE',6780,0)
    http('H04','创建本地模拟申请','/mock/v1/travel/applications','post','N10',7120,-200)
    code('S01','写入真实模拟创建结果',[('gate_json','N10','gate_json','string'),('api_body','H04','body','string'),('status_code','H04','status_code','number')],['result_json'],7460,-200)
    code('S99','保留不确定结果与原请求号',[('gate_json','N10','gate_json','string')],['result_json'],7120,500)
    # 支持嵌套互斥聚合：同一次只执行一份result_json。
    nodes['N11']['data']['variables']=[sel(n,'result_json') for n in ['N09','N10','Q01','S01','S99']]
    # N10/Q01在HTTP分支虽已执行，但result_json为空；用互斥传递节点隔离，避免聚合器选中空串。
    for name,up,title,x,y in [('S02','N10','沿用门控拒绝或重复回执',6100,900),('Q02','Q01','沿用查询到的回执',7120,100)]:
        path=ROOT/'nodes'/ (name+'.py')
        code(name,title,[('result_json',up,'result_json','string')],['result_json'],x,y)
    nodes['N11']['data']['variables']=[sel(n,'result_json') for n in ['N09','S02','Q02','S01','S99']]
    nodes['E99']['data']['answer']='本轮处理发生系统异常，新的会话状态可能尚未保存。已有草稿仍保留；若本轮在提交阶段，调用可能已到达本地模拟接口，请勿清空草稿。稍后对同一版本再次确认，系统将先核对同一请求号的回执，避免重复创建。若持续异常，请联系搭建人员核对调用记录。'
    nodes['E99']['data']['desc']='保留草稿，不承诺尚未执行创建。'
    # 去掉旧节点职责说明中的模拟权限与历史校验。
    nodes['N02']['data']['desc']='验证mvp1.2会话，装载HTTP员工和21项交通；城市名称仅为模型范围提示。'
    nodes['N07']['data']['desc']='仅使用城市HTTP结果生成映射，保留原城市交通、日期路线及完整性校验。'
    edges=[]
    def edge(a,b,handle='source'):
        edges.append({'id':ids[a]+'-'+handle+'-'+ids[b],'source':ids[a],'target':ids[b],'sourceHandle':handle,'targetHandle':'target','type':'custom','zIndex':0,'data':{'sourceType':nodes[a]['data']['type'],'targetType':nodes[b]['data']['type'],'isInIteration':False,'isInLoop':False}})
    reverse={v:k for k,v in ids.items()}
    for e in graph['edges']:
        a,b=reverse[e['source']],reverse[e['target']]
        if (a,b) in [('N01','N02'),('N06','N07'),('N10','N11')]:continue
        edge(a,b,e['sourceHandle'])
    for a,b,h in [('N01','H01','source'),('H01','N02','source'),('H01','E99','fail-branch'),('N06','C01','source'),('C01','H02','source'),('C01','E99','fail-branch'),('H02','N07','source'),('H02','E99','fail-branch'),('N10','S00','source'),('S00','H03','true'),('S00','S02','false'),('S02','N11','source'),('S02','E99','fail-branch'),('H03','Q01','source'),('H03','S99','fail-branch'),('Q01','Q00','source'),('Q01','S99','fail-branch'),('Q00','H04','true'),('Q00','Q02','false'),('Q02','N11','source'),('Q02','S99','fail-branch'),('H04','S01','source'),('H04','S01','fail-branch'),('S01','N11','source'),('S01','S99','fail-branch'),('S99','N11','source'),('S99','E99','fail-branch')]:edge(a,b,h)
    graph.update(nodes=list(nodes.values()),edges=edges)
    for name,x,y in [('N11',7800,400),('N12',8140,400),('N13',8480,400),('N14',8820,400),('N07',3740,400)]:
        nodes[name]['position']=nodes[name]['positionAbsolute']={'x':x,'y':y}
    doc['app']['name']='差旅申请助手-MVP1.2-测试';doc['app']['description']='完整Demo：固定普通员工、HTTP城市与21项交通、版本确认、真实本地模拟创建与回执恢复。'
    wf=doc['workflow'];wf['environment_variables']=[{'id':'d8435807-018d-4c87-a0db-e99e00000001','name':'DEMO_API_BASE_URL','value_type':'string','value':'','description':'工作流网关HTTPS基地址，不含末尾斜杠','selector':['env','DEMO_API_BASE_URL']},{'id':'d8435807-018d-4c87-a0db-e99e00000002','name':'DEMO_API_TOKEN','value_type':'secret','value':'','description':'服务端工作流网关Bearer凭证，仅在私密运行配置填写','selector':['env','DEMO_API_TOKEN']}]
    OUT.write_text(yaml.safe_dump(doc,allow_unicode=True,sort_keys=False,width=100000))
    manifest={'baseline_source':'基线/2026-09-12_180819_Dify当前已保存版本.yml','baseline_sha256':hashlib.sha256(BASE.read_bytes()).hexdigest(),'nodes':len(nodes),'edges':len(edges),'node_ids':ids,'artifact_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'note':'ISSUE-001～010 修复：使用当前完整 Demo 独立源码与公共解析提示；N03/R01显式thinking=false。自动测试不代表线上通过。'}
    (ROOT/'build_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(str(OUT)+'\n'+str(len(nodes))+'节点，'+str(len(edges))+'条连线，模型deepseek-v4-flash；环境变量为空。')
    return doc
if __name__=='__main__':build()
