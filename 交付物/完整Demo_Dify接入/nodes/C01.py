import json


def main(candidate_json: str, context_json: str) -> dict:
    candidate, ctx = json.loads(candidate_json), json.loads(context_json)
    queries = [ctx['employee']['base_city']]
    for trip in candidate.get('draft', {}).get('trips', []):
        for field in ('from_city', 'to_city'):
            value = trip[field]['value']
            if value:
                queries.append(value)
    # 默认链路及返程仅复用上述原始字段，保留空白以符合实际接口契约。
    queries = list(dict.fromkeys(queries))
    if len(queries) > 81 or any(not 1 <= len(q) <= 100 for q in queries):
        raise ValueError('城市查询超过接口长度限制，请缩短地点名称。')
    return {'body': json.dumps({'queries': queries}, ensure_ascii=False, separators=(',', ':'))}
