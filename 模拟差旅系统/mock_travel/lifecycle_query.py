"""先选可见版本，再按申报行程区间与城市交集筛选。"""
from datetime import date, timedelta
from .catalog import business_time, query_cities
from .store import ServiceError


def intervals(document):
    trips=document['request'].get('trips',[]); result=[]
    for i,trip in enumerate(trips):
        result.append(dict(kind='movement',dateFrom=trip['dateFrom'],dateTo=trip['dateTo'],
                           cityIds=list(dict.fromkeys([trip['cityFrom'],trip['cityTo']])),
                           explanation='这是申报的移动区间；未提供具体时刻，不能判断全天处于某一城市。'))
        if i+1<len(trips):
            try:
                start=date.fromisoformat(trip['dateTo'])+timedelta(days=1)
                end=date.fromisoformat(trips[i+1]['dateFrom'])-timedelta(days=1)
            except ValueError: continue  # 迁移老数据不推断无效日期的停留。
            if start<=end and trip['cityTo']==trips[i+1]['cityFrom']:
                result.append(dict(kind='stay',dateFrom=start.isoformat(),dateTo=end.isoformat(),
                                   cityIds=[trip['cityTo']],explanation='根据相邻交通段推导的申报停留区间，并非实际定位。'))
    return result


def query_documents(documents,filters,aliases=None):
    filters={key:value for key,value in filters.items() if value is not None}
    def invalid(text): raise ServiceError('INVALID_FILTER',text,422)
    basis=filters.get('dateBasis','trip'); temporal=filters.get('temporal')
    if basis not in {'trip','submitted'}: invalid('日期依据只能为 trip 或 submitted。')
    if temporal not in {None,'past','current','future'}: invalid('时间分类只能为 past、current 或 future。')
    status=filters.get('status')
    if status is not None and status not in {'UNKNOWN','S001','S002','S003','S004','S005','S100'}: invalid('单据状态不受支持。')
    try:
        limit=int(filters.get('limit',20)); offset=int(filters.get('offset',0))
        if str(limit)!=str(filters.get('limit',20)) or str(offset)!=str(filters.get('offset',0)): raise ValueError
        if not 1<=limit<=100 or offset<0: raise ValueError
    except (ValueError,TypeError): invalid('分页须使用 1 至 100 的条数和非负整数偏移。')
    effective=filters.get('effectiveOnly',False)
    if isinstance(effective,str):
        if effective.lower() not in {'true','false','1','0'}: invalid('effectiveOnly 须为布尔值。')
        effective=effective.lower() in {'true','1'}
    elif type(effective) is not bool: invalid('effectiveOnly 须为布尔值。')
    start=filters.get('dateFrom'); end=filters.get('dateTo')
    for value in (start,end):
        if value:
            try:
                if date.fromisoformat(value).isoformat()!=value: raise ValueError
            except (ValueError,TypeError): invalid('请输入真实日期，格式为 YYYY-MM-DD。')
    if start and end and start>end: invalid('查询开始日期不能晚于结束日期。')
    today=business_time()['date']; keyword=str(filters.get('keyword','')).strip().lower()
    city=str(filters.get('city','')).strip()
    city_ids={x['cityId'] for x in query_cities(city)} if city else None
    lower=start or '0001-01-01'; upper=end or '9999-12-31'; found=[]
    for doc in documents:
        if effective and (not doc['isEffective'] or doc['status']=='S100'): continue
        if status and doc['status']!=status: continue
        searchable=[doc['applicationId'],doc['applicationNo'],doc['request'].get('remark','')]+(aliases or {}).get(doc['applicationId'],[])
        if keyword and not any(keyword in text.lower() for text in searchable): continue
        trip_start,trip_end=doc['tripStart'],doc['tripEnd']
        if temporal and (not trip_start or not trip_end): continue
        if temporal=='past' and not trip_end<today: continue
        if temporal=='current' and not trip_start<=today<=trip_end: continue
        if temporal=='future' and not trip_start>today: continue
        segments=intervals(doc)
        if basis=='submitted':
            submitted=doc['submittedAt'][:10]
            if not lower<=submitted<=upper: continue
            matching=segments
        else:
            if not trip_start or not trip_end or trip_start>upper or trip_end<lower: continue
            matching=[segment for segment in segments if segment['dateFrom']<=upper and segment['dateTo']>=lower]
        if city_ids is not None and not any(city_ids.intersection(segment['cityIds']) for segment in matching): continue
        if basis=='trip' and start and start==end: doc={**doc,'locations':matching}
        found.append(doc)
    return dict(items=found[offset:offset+limit],total=len(found),limit=limit,offset=offset)
