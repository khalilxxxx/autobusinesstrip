"""只有有效 handled=false 才允许进入原创建流程。"""
import json

def main(api_body,status_code):
    error={'handled':'true','reply':'本轮生命周期服务未返回可确认的结果。已有草稿和原请求号保留；请重新打开草稿并按原请求号核对，暂勿新建重复办理请求。'}
    try:
        if int(status_code)!=200: return error
        result=json.loads(api_body)
        if not isinstance(result,dict) or type(result.get('handled')) is not bool or not isinstance(result.get('reply'),str): return error
        if result['handled'] and not result['reply'].strip(): return error
        return dict(handled='true' if result['handled'] else 'false',reply=result['reply'])
    except (ValueError,TypeError): return error
