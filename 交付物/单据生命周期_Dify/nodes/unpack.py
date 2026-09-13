"""只有有效 handled=false 才允许进入原创建流程。"""
import json
from datetime import date


def answer_context(value):
    """只放行结构可靠的本页原始事实，剔除预推理和非问答字段。"""
    if not isinstance(value, dict): return None
    required = {'question', 'businessDate', 'filters', 'total', 'shown', 'documents', 'cityNames'}
    if not required <= set(value): return None
    if not isinstance(value['question'], str) or not value['question'].strip(): return None
    if not isinstance(value['businessDate'], str) or date.fromisoformat(value['businessDate']).isoformat() != value['businessDate']: return None
    if not isinstance(value['filters'], dict) or not isinstance(value['cityNames'], dict): return None
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in value['cityNames'].items()): return None
    total, shown, documents = value['total'], value['shown'], value['documents']
    if type(total) is not int or type(shown) is not int or not 0 <= shown <= min(total, 3): return None
    if not isinstance(documents, list) or len(documents) != shown: return None
    clean = []
    for doc in documents:
        if not isinstance(doc, dict): return None
        if any(not isinstance(doc.get(k), str) or not doc[k] for k in ('applicationId', 'applicationNo', 'status', 'documentType')): return None
        if type(doc.get('isEffective')) is not bool or not isinstance(doc.get('request'), dict): return None
        request = doc['request']; trips = request.get('trips')
        if not isinstance(trips, list): return None
        raw_trips = []
        for trip in trips:
            fields = ('dateFrom', 'dateTo', 'cityFrom', 'cityTo', 'tool')
            if not isinstance(trip, dict) or any(not isinstance(trip.get(k), str) or not trip[k] for k in fields): return None
            for key in ('dateFrom', 'dateTo'):
                if date.fromisoformat(trip[key]).isoformat() != trip[key]: return None
            raw_trips.append({k: trip[k] for k in fields})
        item = {k: doc[k] for k in ('applicationId', 'applicationNo', 'status', 'isEffective', 'documentType')}
        item['request'] = {k: request[k] for k in ('remark', 'dqydbg', 'departmentId', 'payerCompanyId') if k in request}
        item['request']['trips'] = raw_trips
        clean.append(item)
    return {**{k: value[k] for k in required - {'documents'}}, 'documents': clean}

def main(api_body,status_code):
    no_answer = dict(answer_ready='false', answer_context='')
    error={'handled':'true','reply':'本轮生命周期服务未返回可确认的结果。已有草稿和原请求号保留；请重新打开草稿并按原请求号核对，暂勿新建重复办理请求。', **no_answer}
    try:
        if int(status_code)!=200: return error
        result=json.loads(api_body)
        if not isinstance(result,dict) or type(result.get('handled')) is not bool or not isinstance(result.get('reply'),str): return error
        if result['handled'] and not result['reply'].strip(): return error
        output = dict(handled='true' if result['handled'] else 'false', reply=result['reply'], **no_answer)
        if result['handled']:
            try:
                context = answer_context(result.get('answerContext'))
            except (ValueError, TypeError):
                context = None
            if context is not None:
                output.update(answer_ready='true', answer_context=json.dumps(context, ensure_ascii=False, separators=(',', ':')))
        return output
    except (ValueError,TypeError): return error
