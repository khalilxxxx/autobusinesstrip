"""读取现有 cv_session 的编辑标志，不创建或修改任何会话变量。"""
import json

def main(cv_session):
    state=json.loads(cv_session) if isinstance(cv_session,str) else cv_session
    if not isinstance(state,dict): raise ValueError('创建会话状态无效，请重新打开会话核对。')
    editing=bool(state.get('draft') and state.get('flow_state') not in ('SUBMITTED','IDLE'))
    return {'creation_editing':'true' if editing else 'false'}
