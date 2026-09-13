"""确定性的恢复范围和未确认节假日规则，内联到 Dify 节点。"""
import re


def explicit_route_restatement(query):
    if any(mark in query for mark in ('“', '”', '「', '」', '『', '』', '"', "'", '`')):
        return False
    if re.search(r'如果|假如|假设|要是|是否|请问|能否|可以吗|[？?]', query):
        return False
    scope = re.search(r'(?:这张|这次|本张|本次|当前|这份).{0,8}只(?:保留|从|去)', query)
    dates = re.findall(r'\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}[日号]', query)
    return bool(scope and len(dates) >= 2 and re.search(r'去|到', query) and re.search(r'回|返', query))


def recovery_fact_context(recovery, query, draft):
    if not recovery:
        return {}
    view = {k: recovery.get(k, '') for k in ('id', 'targets', 'scope', 'question')}
    if (explicit_route_restatement(query) and recovery.get('failure_count') == 1
            and recovery.get('base_draft_id') == draft.get('draft_id', '')
            and recovery.get('base_revision') == draft.get('revision', 0)):
        view.update(failed_query=recovery['failed_query'], reference_date=recovery['reference_date'])
    return view


def holiday_needs_date(query):
    holiday = re.search(r'(?:国庆|春节|中秋|端午|劳动节|五一|清明|元旦)(?:假期|节)?(?:结束|过)?后|节后', query)
    explicit = re.search(r'\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}[日号]|\d{1,2}/\d{1,2}', query)
    return bool(holiday and not explicit)


def return_day_offset(query):
    # 捕获完整数字，避免“十二”或“102”从尾部匹配成“二”或“02”。
    match = re.search(r'([零〇一二两三四五六七八九十百千万\d]+)天后(?:再)?(?:回|返)', query)
    if not match:
        return None
    word = match[1]
    digits = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    if word.isdigit():
        days = int(word)
    elif word in digits:
        days = digits[word]
    elif re.fullmatch(r'[一二三四五六七八九]?十[一二三四五六七八九]?', word):
        tens, units = word.split('十')
        days = digits.get(tens, 1) * 10 + digits.get(units, 0)
    else:
        return None
    return days if 1 <= days <= 30 else None
