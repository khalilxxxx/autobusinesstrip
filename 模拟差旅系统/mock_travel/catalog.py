"""模拟主数据；截图样例与本地生成编码明确区分。"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

BUSINESS_TIMEZONE = timezone(timedelta(hours=8))

TRANSPORT_GROUPS = {
    "火车": ["二等座", "一等座", "硬座", "软座", "特等座", "硬卧", "软卧", "高铁动卧", "高级软卧", "无座"],
    "飞机": ["经济舱", "自订机票"],
    "汽车": ["客车", "自驾车", "公司派车", "出租车"],
    "轮船": ["二等舱", "一等舱"],
    "其他": ["城际地铁", "免费搭车", "客户代订"],
}


def business_time():
    now = datetime.now(BUSINESS_TIMEZONE)
    return {"date": now.date().isoformat(), "datetime": now.isoformat(timespec="seconds"),
            "timezone": "Asia/Shanghai", "source": "SYSTEM_CLOCK"}


def employee_context():
    department = {"id": "DEMO_DEPT_001", "name": "演示业务部"}
    company = {"id": "DEMO_COMPANY_001", "name": "演示科技公司"}
    return {
        "employee": {"employeeId": "DEMO_EMP_001", "employeeName": "演示员工",
                     "baseCity": {"cityId": "330100", "cityName": "杭州"}},
        "defaultDepartment": department, "departments": [department],
        "defaultPayerCompany": company, "payerCompanies": [company],
        "businessTime": business_time(), "canSubmit": True,
        "modules": {"activity": "NONE", "companions": False}, "demoOnly": True,
    }


def transport_options():
    return [{"category": category, "option": option, "value": category + "-" + option}
            for category, options in TRANSPORT_GROUPS.items() for option in options]


# data 只使用截图可见字段。aliases / source 是本地数据说明。
CITIES = [
    {"data": {"cityId": "330100", "upCityId": "", "countryId": "CN", "provinceId": "33",
              "provinceName": "浙江", "cityName": "杭州", "upCityName": ""},
     "aliases": ["杭州", "杭州市", "杭州站", "杭州东", "杭州东站", "萧山机场", "杭州萧山机场"], "source": "SCREENSHOT_SAMPLE"},
    {"data": {"cityId": "330122", "upCityId": "330100", "countryId": "CN", "provinceId": "33",
              "provinceName": "浙江", "cityName": "桐庐县（桐庐基地除外）", "upCityName": "杭州"},
     "aliases": ["桐庐", "桐庐县", "桐庐站"], "source": "SCREENSHOT_SAMPLE"},
    {"data": {"cityId": "DEMO_SHANGHAI", "upCityId": "", "countryId": "CN", "provinceId": "DEMO_SHANGHAI",
              "provinceName": "上海", "cityName": "上海", "upCityName": ""},
     "aliases": ["上海", "上海市", "沪", "上海站", "上海虹桥", "上海虹桥站", "虹桥站", "虹桥机场",
                 "上海虹桥机场", "浦东机场", "上海浦东机场"], "source": "MOCK"},
    {"data": {"cityId": "DEMO_BEIJING", "upCityId": "", "countryId": "CN", "provinceId": "DEMO_BEIJING",
              "provinceName": "北京", "cityName": "北京", "upCityName": ""},
     "aliases": ["北京", "北京市", "北京站", "北京南", "北京南站", "北京西站", "首都机场", "大兴机场",
                 "北京首都机场", "北京大兴机场"], "source": "MOCK"},
    {"data": {"cityId": "DEMO_SUZHOU", "upCityId": "", "countryId": "CN", "provinceId": "DEMO_JIANGSU",
              "provinceName": "江苏", "cityName": "苏州", "upCityName": ""},
     "aliases": ["苏州", "苏州市", "苏州站", "苏州北", "苏州北站", "苏州园区站"], "source": "MOCK"},
]


# 按省份维护新增样本；DEMO_ 编码只用于本地演示，与公司城市编码无关。
MOCK_CITY_GROUPS = [
    ("DEMO_TIANJIN", "天津", [
        ("TIANJIN", "天津", ["天津站", "天津西站", "天津南站", "天津滨海机场"]),
    ]),
    ("DEMO_HEBEI", "河北", [
        ("SHIJIAZHUANG", "石家庄", ["石家庄站", "石家庄正定机场"]),
    ]),
    ("DEMO_SHANXI", "山西", [
        ("TAIYUAN", "太原", ["太原站", "太原南站", "太原武宿机场"]),
    ]),
    ("DEMO_NEIMENGGU", "内蒙古", [
        ("HOHHOT", "呼和浩特", ["呼和浩特站", "呼和浩特东站"]),
    ]),
    ("DEMO_LIAONING", "辽宁", [
        ("SHENYANG", "沈阳", ["沈阳站", "沈阳北站", "沈阳桃仙机场"]),
        ("DALIAN", "大连", ["大连站", "大连北站", "大连周水子机场"]),
    ]),
    ("DEMO_JILIN", "吉林", [
        ("CHANGCHUN", "长春", ["长春站", "长春西站", "长春龙嘉机场"]),
    ]),
    ("DEMO_HEILONGJIANG", "黑龙江", [
        ("HARBIN", "哈尔滨", ["哈尔滨站", "哈尔滨西站", "哈尔滨太平机场"]),
    ]),
    ("DEMO_JIANGSU", "江苏", [
        ("NANJING", "南京", ["南京站", "南京南站", "南京禄口机场"]),
        ("WUXI", "无锡", ["无锡站", "无锡东站", "无锡苏南硕放机场"]),
        ("CHANGZHOU", "常州", ["常州站", "常州北站", "常州奔牛机场"]),
        ("NANTONG", "南通", ["南通站", "南通西站", "南通兴东机场"]),
        ("XUZHOU", "徐州", ["徐州站", "徐州东站", "徐州观音机场"]),
    ]),
    ("33", "浙江", [
        ("NINGBO", "宁波", ["宁波站", "宁波栎社机场"]),
        ("WENZHOU", "温州", ["温州站", "温州南站", "温州龙湾机场"]),
        ("SHAOXING", "绍兴", ["绍兴站", "绍兴北站"]),
        ("JIAXING", "嘉兴", ["嘉兴站", "嘉兴南站"]),
        ("HUZHOU", "湖州", ["湖州站", "湖州东站"]),
    ]),
    ("DEMO_ANHUI", "安徽", [
        ("HEFEI", "合肥", ["合肥站", "合肥南站", "合肥新桥机场"]),
    ]),
    ("DEMO_FUJIAN", "福建", [
        ("FUZHOU", "福州", ["福州站", "福州南站", "福州长乐机场"]),
        ("XIAMEN", "厦门", ["厦门站", "厦门北站", "厦门高崎机场"]),
    ]),
    ("DEMO_JIANGXI", "江西", [
        ("NANCHANG", "南昌", ["南昌站", "南昌西站", "南昌昌北机场"]),
    ]),
    ("DEMO_SHANDONG", "山东", [
        ("JINAN", "济南", ["济南站", "济南西站", "济南东站", "济南遥墙机场"]),
        ("QINGDAO", "青岛", ["青岛站", "青岛北站", "青岛胶东机场"]),
    ]),
    ("DEMO_HENAN", "河南", [
        ("ZHENGZHOU", "郑州", ["郑州站", "郑州东站", "郑州新郑机场"]),
    ]),
    ("DEMO_HUBEI", "湖北", [
        ("WUHAN", "武汉", ["武汉站", "汉口站", "武昌站", "武汉天河机场"]),
    ]),
    ("DEMO_HUNAN", "湖南", [
        ("CHANGSHA", "长沙", ["长沙站", "长沙南站", "长沙黄花机场"]),
    ]),
    ("DEMO_GUANGDONG", "广东", [
        ("GUANGZHOU", "广州", ["广州站", "广州南站", "广州东站", "广州白云机场"]),
        ("SHENZHEN", "深圳", ["深圳站", "深圳北站", "福田站", "深圳宝安机场"]),
        ("ZHUHAI", "珠海", ["珠海站", "珠海金湾机场"]),
        ("DONGGUAN", "东莞", ["东莞站", "东莞东站", "虎门站"]),
        ("FOSHAN", "佛山", ["佛山站", "佛山西站"]),
    ]),
    ("DEMO_GUANGXI", "广西", [
        ("NANNING", "南宁", ["南宁站", "南宁东站", "南宁吴圩机场"]),
    ]),
    ("DEMO_HAINAN", "海南", [
        ("HAIKOU", "海口", ["海口站", "海口东站", "海口美兰机场"]),
        ("SANYA", "三亚", ["三亚站", "三亚凤凰机场"]),
    ]),
    ("DEMO_CHONGQING", "重庆", [
        ("CHONGQING", "重庆", ["重庆北站", "重庆西站", "重庆东站", "重庆江北机场"]),
    ]),
    ("DEMO_SICHUAN", "四川", [
        ("CHENGDU", "成都", ["成都东站", "成都南站", "成都天府机场", "成都双流机场"]),
    ]),
    ("DEMO_GUIZHOU", "贵州", [
        ("GUIYANG", "贵阳", ["贵阳站", "贵阳北站", "贵阳东站", "贵阳龙洞堡机场"]),
    ]),
    ("DEMO_YUNNAN", "云南", [
        ("KUNMING", "昆明", ["昆明站", "昆明南站", "昆明长水机场"]),
    ]),
    ("DEMO_XIZANG", "西藏", [
        ("LHASA", "拉萨", ["拉萨站", "拉萨贡嘎机场"]),
    ]),
    ("DEMO_SHAANXI", "陕西", [
        ("XIAN", "西安", ["西安站", "西安北站", "西安咸阳机场"]),
    ]),
    ("DEMO_GANSU", "甘肃", [
        ("LANZHOU", "兰州", ["兰州站", "兰州西站", "兰州中川机场"]),
    ]),
    ("DEMO_QINGHAI", "青海", [
        ("XINING", "西宁", ["西宁站", "西宁曹家堡机场"]),
    ]),
    ("DEMO_NINGXIA", "宁夏", [
        ("YINCHUAN", "银川", ["银川站", "银川河东机场"]),
    ]),
    ("DEMO_XINJIANG", "新疆", [
        ("URUMQI", "乌鲁木齐", ["乌鲁木齐站", "乌鲁木齐南站"]),
    ]),
]
CITIES.extend(
    {"data": {"cityId": "DEMO_" + city_code, "upCityId": "", "countryId": "CN",
              "provinceId": province_id, "provinceName": province_name, "cityName": city_name, "upCityName": ""},
     "aliases": [city_name, city_name + "市", *aliases], "source": "MOCK"}
    for province_id, province_name, cities in MOCK_CITY_GROUPS
    for city_code, city_name, aliases in cities
)


def query_cities(keyword):
    query = "".join(keyword.split())
    mapped = query in {"昆山", "昆山市", "昆山南", "昆山南站"}
    results = []
    for entry in CITIES:
        data = entry["data"]
        aliases = entry["aliases"]
        matched = (mapped and data["cityId"] == "DEMO_SUZHOU") or (not mapped and (
            query == data["cityId"] or query in data["cityName"] or any(query in alias for alias in aliases)))
        if not matched:
            continue
        item = deepcopy(data)
        item["mockMetadata"] = {
            "dataSource": entry["source"], "originalQuery": keyword,
            "matchType": "BUSINESS_MAPPING" if mapped else "ALIAS" if query in aliases else "SEARCH",
            "explanation": "昆山按本项目业务规则使用苏州作为提单城市。" if mapped else "本地模拟城市样本。",
        }
        results.append(item)
    return results
