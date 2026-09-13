import json


def main(result_json: str) -> dict:
    result=json.loads(result_json)
    if not isinstance(result,dict) or set(result)!={'state','reply_text'}:
        raise ValueError('互斥分支结果为空或损坏。')
    return {'result_json':result_json}
