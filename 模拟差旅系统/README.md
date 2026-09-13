# 普通员工模拟差旅系统

2026-09-13 独立新版支持纯语义查询、最多三张结果卡片、简洁问答及撤回／作废／连续行程变更。运行入口为 8876，详见 [差旅助手 V2 使用说明](单据生命周期V2使用说明.md)。下文保留原版模拟接口说明。

当前已扩展完整 Demo 接入，2026-09-12。助手页面、模拟控制台和运行方式见 [完整 Demo 使用说明](/Users/khalil/Documents/智能提单项目/模拟差旅系统/完整Demo使用说明.md)。

原模拟 API 数据范围：依据用户要求，只按普通员工实现，不区分 M5，不提供角色切换。城市样本已扩充到 50 条，查询仅需 `filter`。

已实现员工上下文、21 项交通、城市查询、预设结果创建、单据与请求回执查询。申请、回执和成功／失败场景保存在 SQLite，停止服务不会清空。

## 启动与打开

在这个目录执行：

```sh
./run.sh
```

首次在新机器启动时脚本创建 `.venv` 并安装锁定依赖；当前工作区已安装。Python 3.9+ 可运行，本次使用 Python 3.9.6。

- [接口调试页](http://127.0.0.1:8766/docs)：展开接口，点击 **Try it out**，填写参数后 **Execute**。
- [OpenAPI 文档](http://127.0.0.1:8766/openapi.json)：当前可执行请求契约。
- [健康状态](http://127.0.0.1:8766/health)。

调试页的 Swagger JS/CSS 已保存在本地，打开页面不需要访问公共 CDN。服务默认仅监听 `127.0.0.1`；终端按 Ctrl+C 停止。

端口与数据库可通过环境变量指定：

```sh
MOCK_PORT=8776 ./run.sh
MOCK_TRAVEL_DB=/tmp/travel-demo.sqlite3 ./run.sh
```

默认数据库位于本目录 `data/mock_travel.sqlite3`。该文件包含持续保存的模拟数据；没有自动重置或删除接口。

## 先操作这四步

1. 调用 `GET /mock/v1/employee-context`，看到默认演示员工、部门和付款公司。
2. 调用 `POST /mock/v1/cities/query`，只填写 `filter`，例如“广州”“深圳北站”“桐庐”或“昆山”。
3. 调用 `POST /mock/v1/travel/applications`，使用调试页内的完整示例。可填 `X-Client-Request-Id=demo-submit-001`；首次示例返回模拟单号。
4. 调用 `GET /mock/v1/travel/applications` 查看已创建记录，再复制 `applicationId` 查询详情。

演示失败：先用 `PUT /mock/v1/scenario` 设置 `submissionResult=FAILURE` 和失败说明，再以**新的请求标识**创建；返回 `MOCK_SUBMIT_FAILED`，不会生成成功申请。完成后改回 SUCCESS。

重复原请求标识会重放原结果，即使场景开关已经改变。这是预期的防重复行为。一次明确失败后，用户主动重试可以使用新标识；网络重传继续沿用原标识。

## 接口清单

| 方法与路径 | 用途 | 请求方式 |
|---|---|---|
| GET `/health` | 服务状态 | 无参数 |
| GET `/mock/v1/employee-context` | 默认员工、组织、时间与模块 | 可选 employeeId，当前仅 DEMO_EMP_001 |
| GET `/mock/v1/transport-options` | 普通员工 21 项交通 | 无角色参数 |
| POST `/mock/v1/cities/query` | 城市搜索和明确映射 | 表单 filter 必填，为唯一业务参数 |
| GET／PUT `/mock/v1/scenario` | 查看／设置模拟提交结果 | PUT 使用 JSON，submissionResult 为 SUCCESS／FAILURE |
| POST `/mock/v1/travel/applications` | 模拟创建 | JSON；可选请求与草稿 Header |
| GET `/mock/v1/travel/applications` | 申请列表 | 可选 applicantId、limit（1～100）、offset |
| GET `/mock/v1/travel/applications/{applicationId}` | 申请详情 | 路径为创建响应中的 ID |
| GET `/mock/v1/submissions/{requestId}` | 找回成功／失败的原回执 | 路径为发送时的 X-Client-Request-Id |

这是本地拟定的地址和方法，截图未提供公司的正式 URL 或方法。

## 与截图的对应

- 创建 JSON 根对象直接包含 `remark`、`dqydbg`、`trips`；`trips` 是对象数组。`root` 和 `items` 暂按文档树节点理解，不添加同名包装。
- `dqydbg` 字段必须存在：普通差旅为 JSON `null`，短期异地办公为 `"Y"`。
- 行程字段为 `dateFrom`、`dateTo`、`cityFrom`、`cityTo`、`tool`。只检查结构和日期字符串格式，不检查日期先后、历史重叠、路线闭环或真实员工权限。
- `applicantId`、`departmentId`、`payerCompanyId` 是本地扩展，省略时使用固定演示默认值。
- 创建响应 `uuid` 为对象，暂取 `{ "value": "MOCK-REQ-..." }`；城市响应 `uuid` 为字符串。两者按截图分别处理。
- `message` 保留对象；失败文字位于 `message.text`；`code=SUCCESS` 表示业务成功，其他值表示失败。
- 创建 `data.action=AI_CREATE`；`applicationId`、`applicationNo`、`createdAt`、`clientRequestId`、`demoOnly` 为本地响应扩展。
- 城市使用表单 `filter`，`data` 为数组，保留截图中的 cityId、upCityId、countryId、provinceId、provinceName、cityName、upCityName。
- 城市条目中的 `data[].mockMetadata` 是本地扩展，用于标注数据来源、原始查询和业务映射说明。

创建请求和两种场景 JSON 已放在 [examples](/Users/khalil/Documents/智能提单项目/模拟差旅系统/examples/create-application.json)。原截图在 [接口资料目录](/Users/khalil/Documents/智能提单项目/交付物/接口对接梳理_V0.2/当前资料状态与后续补充.md) 中有链接。

## 普通员工与城市数据范围

交通固定 21 项：火车 10 项、飞机经济舱／自订机票 2 项、汽车 4 项、轮船 2 项、其他 3 项。无 M5 参数和代码分支。交通目录供后续工作流和页面限制选择使用；当前创建接口按要求不额外进行交通资格等业务校验，不把“模拟成功”当作业务规则通过。

城市样本共 50 条，覆盖以下国内城市。杭州 `330100`、桐庐 `330122` 引用截图样例；其他城市编码以 `DEMO_` 标明本地模拟。

| 区域 | 城市样本 |
|---|---|
| 华北 | 北京、天津、石家庄、太原、呼和浩特 |
| 东北 | 沈阳、大连、长春、哈尔滨 |
| 华东 | 上海、南京、苏州、无锡、常州、南通、徐州、杭州、桐庐、宁波、温州、绍兴、嘉兴、湖州、合肥、福州、厦门、南昌、济南、青岛 |
| 华中 | 郑州、武汉、长沙 |
| 华南 | 广州、深圳、珠海、东莞、佛山、南宁、海口、三亚 |
| 西南 | 重庆、成都、贵阳、昆明、拉萨 |
| 西北 | 西安、兰州、西宁、银川、乌鲁木齐 |

支持城市名称、关键词、城市编码及已配置的站点别名。例如“深圳北站”返回深圳，“成都天府机场”返回成都，“汉口站”返回武汉；没有匹配时返回 `data=[]`。具体编码和别名见 [城市样本数据](/Users/khalil/Documents/智能提单项目/模拟差旅系统/mock_travel/catalog.py)。

桐庐保留自身身份，不能因拥有上级城市就替换为杭州。“桐庐基地除外”保留为截图原名，未扩展基地规则。昆山查询明确返回苏州及映射说明，昆山不另占一条城市样本。

## 重复请求和回执

- 建议每次新的确认尝试生成 `X-Client-Request-Id`，支持英文字母、数字、`_ . : -`，长度不超过 128。
- 省略此 Header 时服务端生成标识并在 `data.clientRequestId` 返回；后续重试必须带回这个标识才有同请求去重效果。
- 同请求 ID、同内容与同确认版本：完整回放原响应。相同 ID 换内容或换确认版本：HTTP 409／REQUEST_CONFLICT。
- 可选同时提供 `X-Draft-Id` 与 `X-Draft-Version`（正整数）。相同申请人、草稿和已成功版本不会重复成单；相同版本换内容：409／DRAFT_CONFLICT。
- 只有 request ID 的两个不同请求可以创建内容相同的两张申请；系统不检查日期冲突，也不按内容相同擅自去重。
- 回执查询返回 SUCCEEDED／FAILED 与完整原始结果。查不到返回 404／SUBMISSION_NOT_FOUND，不能把“查不到”当作“已经失败”。

这里是本地请求一致性处理；没有实现生产系统的对账、审批或授权机制。模拟场景是单个本地环境共享的持久化设置。

## 测试和实际 HTTP 冒烟

2026-09-12 验证结果：23 项自动测试通过；运行中的服务已逐一验证 50 条城市名称查询，浏览器输入“深圳北站”正确返回深圳，查询表单只显示 `filter`。详见 [验证记录](/Users/khalil/Documents/智能提单项目/模拟差旅系统/验证记录.md)。

```sh
.venv/bin/python -m pytest -q
.venv/bin/python examples/smoke.py --base-url http://127.0.0.1:8766
```

pytest 使用临时数据库。smoke 针对已经启动的服务，会保留一张成功的模拟申请及相关请求记录，并在结束时恢复原先的成功／失败场景。

调试页已提供各接口的响应示例，创建接口可切换查看成功／失败样例。默认创建请求保留必填的 `dqydbg: null`，可直接执行；示例中的单号和请求号仅作说明，实际调用会返回新的值。

## 接 Dify 时从哪里开始

本地调用 Dify Service API 已验证通过。2026-09-12 使用用户提供的应用密钥，完成目标应用鉴权与两轮真实会话；第二轮在同一会话中正确修改事由并保留行程。已提供可重复执行的检查脚本，执行方式与实际记录见 [Dify API 验证说明](/Users/khalil/Documents/智能提单项目/模拟差旅系统/Dify_API验证说明.md)。

现已新增助手页面、确认快照同步、模拟控制台及受限接口网关，Dify 接入版使用 HTTP 节点获取上下文与城市、创建申请并查询回执。城市底层请求仍使用表单，创建请求使用 JSON；从业务 `code` 判断结果。运行及通道配置见 [完整 Demo 使用说明](/Users/khalil/Documents/智能提单项目/模拟差旅系统/完整Demo使用说明.md)，实际验收进度见完整 Demo 验证记录。

## 依赖与资源

Python 依赖版本见 requirements.lock.txt。Swagger UI 使用 swagger-ui-dist 5.17.14，静态 JS/CSS 和原 LICENSE／NOTICE 保存在 mock_travel/static/swagger，来源为该版本的 jsDelivr 分发文件。运行调试页不依赖 CDN。
