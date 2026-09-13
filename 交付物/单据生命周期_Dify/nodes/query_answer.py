"""问答输出为空时沿用已取得的回复，不触发业务重试。"""


def main(answer, fallback):
    return {'reply': answer.strip() if isinstance(answer, str) and answer.strip() else fallback}
