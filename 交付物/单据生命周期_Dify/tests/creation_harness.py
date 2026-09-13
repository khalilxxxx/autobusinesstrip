"""离线解释生成DSL的路由/选择器；HTTP与模型返回人工夹具，绝非线上验收。"""
import json
import re
import yaml
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]/'完整Demo_Dify接入/tests'))
from test_demo import CAT,dump,envelope
ROOT=Path(__file__).resolve().parents[1]


def event(basic=None,trips=None,intent='UPDATE'):
    return {'intent':intent,'submit_requested':'Y' if intent=='SUBMIT' else 'N','basic_updates':basic or [],'trip_operations':trips or [],'clarification':'','consultation':'','clarification_resolutions':[]}
def change(f,v,q):return {'field':f,'op':'SET','value':v,'evidence':q}
def add(tid,city,day,q,kind='MOVE'):
    return {'op':'ADD','trip_id':tid,'after_id':'END','kind':kind,'evidence':q,'updates':[change(f,v,q) for f,v in [('to_city',city),('depart_date',day)] if v]}

class Harness:
    def __init__(self,client,user):
        self.client=client;self.user=user;self.receipts={};self.creates=[];self.mode='SUCCESS';self.trace=[]
    def execute(self,query,parsed,state=None,repair=None):
        doc=yaml.safe_load((ROOT/'差旅助手-单据生命周期-V2-可导入.yml').read_text());nodes={n['id']:n['data'] for n in doc['workflow']['graph']['nodes']};edges=doc['workflow']['graph']['edges']
        values={'sys':{'query':query,'workflow_run_id':'creation-contract-run','user_id':self.user},'conversation':{'cv_session':dump(state or {})},'env':{'DEMO_API_BASE_URL':'https://offline.invalid','DEMO_API_TOKEN':'offline-fixture'}}
        def get(s):return values[s[0]][s[1]]
        def render(s):return re.sub(r'\{\{#([^.]+)\.([^#]+)#\}\}',lambda m:str(get([m[1],m[2]])),s)
        pending=[i for i,n in nodes.items() if n['type']=='start'];self.trace=[];answer=None
        while pending:
            id=pending.pop(0)
            if id in values:continue
            n=nodes[id];name=n['title'].split('-')[0];typ=n['type'];handle='source';self.trace.append(name)
            if typ=='start':out={'demo_reference_date':'2026-09-12'}
            elif typ=='code':
                ns={};exec(n['code'],ns);out=ns['main'](**{v['variable']:get(v['value_selector']) for v in n['variables']})
            elif typ=='llm':
                if name=='LC_ROUTER':out={'text':dump({'intent':'CONFIRM'})}
                elif name=='N03':out={'structured_output':parsed}
                elif name=='R01':
                    if repair is None:out={};handle='fail-branch'
                    else:out={'structured_output':repair}
                else:
                    data=json.loads(render(n['prompt_template'][-1]['text']).split('\n\n')[-1]);out={'text':dump({'recommendations':[{'trip_id':t['trip_id'],'transport':'火车-二等座','reason':'人工预设近程建议'} for t in data['trips']]})}
            elif typ=='if-else':
                out={};handle='false'
                for case in n['cases']:
                    if all(get(c['variable_selector'])==c['value'] for c in case['conditions']):handle=case['case_id'];break
            elif typ=='variable-aggregator':
                present=[get(s) for s in n['variables'] if s[0] in values]
                assert len(present)==1,(name,'聚合非互斥',present)
                out={'output':present[0]}
            elif typ=='assigner':
                for item in n['items']:values[item['variable_selector'][0]][item['variable_selector'][1]]=get(item['value'])
                out={}
            elif typ=='answer':answer=render(n['answer']);out={}
            elif typ=='http-request':
                url=render(n['url']);body=json.loads(render(n['body']['data'][0]['value'])) if n['method']=='post' else None
                if name=='LC_CONTEXT':
                    params=dict(line.split(':',1) for line in render(n['params']).splitlines())
                    response=self.client.get('/workflow/v1/lifecycle/context',params=params)
                    out={'body':response.text,'status_code':response.status_code}
                elif name=='LC_TURN':
                    response=self.client.post('/workflow/v1/lifecycle/turn',json=body)
                    out={'body':response.text,'status_code':response.status_code}
                elif name=='H01':out={'body':envelope({'employeeContext':CAT['employee_context'](),'transportOptions':CAT['transport_options'](),'cityNames':[c['data']['cityName'] for c in CAT['CITIES']]+['昆山']}),'status_code':200}
                elif name=='H02':out={'body':envelope({'items':[{'query':q,'matches':CAT['query_cities'](q)} for q in body['queries']]}),'status_code':200}
                elif name=='H03':
                    rid=url.rsplit('/',1)[1]
                    inner={'code':'SUCCESS','data':self.receipts[rid],'message':{}} if rid in self.receipts else {'code':'SUBMISSION_NOT_FOUND','data':{},'message':{}}
                    out={'body':envelope({'httpStatus':200 if rid in self.receipts else 404,'result':inner}),'status_code':200}
                else:
                    headers=dict(line.split(': ',1) for line in render(n['headers']).splitlines());rid=headers['X-Client-Request-Id'];self.creates.append((rid,body))
                    if rid not in self.receipts:
                        result={'code':self.mode,'message':{'text':'控制台实际失败说明'},'data':{'clientRequestId':rid,'action':'AI_CREATE','demoOnly':True}}
                        success=self.mode=='SUCCESS'
                        if success:result['data'].update(applicationId='A-'+str(len(self.creates)),applicationNo='API-'+str(len(self.creates)),createdAt='2026-09-12T12:00:00+08:00')
                        self.receipts[rid]={'clientRequestId':rid,'status':'SUCCEEDED' if success else 'FAILED','result':result}
                    out={'body':dump(self.receipts[rid]['result']),'status_code':200}
                    if self.mode=='HTTP_422':
                        out={'body':dump({'code':'VALIDATION_ERROR','message':{'text':'城市字段格式错误'},'data':{}}),'status_code':422};handle='fail-branch'
            else:raise AssertionError(typ)
            values[id]=out
            pending.extend(e['target'] for e in edges if e['source']==id and e['sourceHandle']==handle)
        return json.loads(values['conversation']['cv_session']),answer
