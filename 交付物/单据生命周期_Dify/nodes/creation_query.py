"""只在创建分支归一化已明确选择的新申请口令，后续原确认门控完整保留。"""
import json

def main(query,cv_session):
    command=query.strip().rstrip('。.!！').strip()
    if command!='确认提交新申请': return {'query':query}
    state=json.loads(cv_session) if isinstance(cv_session,str) else cv_session
    if not isinstance(state,dict) or not state.get('draft'):
        raise ValueError('当前没有新申请草稿，不能确认提交新申请。')
    if state.get('flow_state') not in ('READY_TO_CONFIRM','SUBMITTED'):
        raise ValueError('新申请尚未准备好确认，请先核对完整的新申请草稿。')
    # 不改变任何草稿/确认字段；N05P、N10 等仍验证同一版本与 fingerprint。
    return {'query':'确认提交'}
