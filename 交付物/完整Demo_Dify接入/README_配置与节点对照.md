# 完整 Demo Dify 接入包

本包把已有 MVP1.2 的数据来源与创建过程接入本地模拟 API。保持应用名「差旅申请助手-MVP1.2-测试」、模型 `deepseek-v4-flash`、唯一会话变量 `cv_session` 与 `mvp1.2` 状态结构。固定普通员工，无 M5、权限场景切换、外部历史冲突校验或住宿模块。

## 文件与来源

- `差旅申请助手-完整Demo-可导入.yml`：脱敏工作流，39 个节点、69 条线，两个环境变量均为空。
- `build_demo_dsl.py`：读取今日实际导出和 `nodes/`，可重复生成 DSL 与哈希清单，不运行旧配置包构建脚本。
- `nodes/`：全部 Python Code 节点的独立源码；每个节点可单独复制到 Dify，不依赖本机目录、不在 Code 内联网。
- `tests/`：真实执行 Code 节点与生成 DSL 路由的离线测试；HTTP 信封与模型输出由夹具提供。
- `build_manifest.json`：来源、节点 ID、节点数、连线数与文件 SHA-256。
- `baseline/2026-09-10_已保存版本.yml`：最初采用的历史基线。
- `基线/2026-09-12_180819_Dify当前已保存版本.yml`：主代理在本次工作中实际导出的备份，最终构建以此为容器。与历史导出的 27 个节点 data（含代码、提示与模型）一致；保留今日依赖版本、文件上传配置等差异。

## 构建与验证

在项目根目录运行：

```sh
交付物/完整Demo_Dify接入/.venv/bin/python 交付物/完整Demo_Dify接入/build_demo_dsl.py
交付物/完整Demo_Dify接入/.venv/bin/python -m unittest discover -s 交付物/完整Demo_Dify接入/tests -v
```

独立 `.venv` 仅安装 `PyYAML`，未修改项目或系统 Python。若重新准备环境：在本目录执行 `python3 -m venv .venv`，再执行 `.venv/bin/pip install -r requirements.txt`。

截至本包交付，44 项离线测试通过。测试包含 50 个城市逐项检查、21 项交通逐项检查、站点别名、昆山映射、桐庐编码、多匹配/无匹配、交通推荐及复检、JSON 引号换行、确认版本与指纹、重复确认、明确失败重试、未知同号恢复、422 错误说明、N03/R01 后续真实 Code 路由、全部选择器与边句柄。它们不代表真实模型、Dify 导入或浏览器验收通过。

## 运行配置

Dify 服务端环境变量：

| 名称 | 类型 | 配置 |
|---|---|---|
| `DEMO_API_BASE_URL` | String | 主代理提供的工作流网关 HTTPS 地址，不含末尾 `/` |
| `DEMO_API_TOKEN` | Secret | 网关 Bearer 凭证，填入私密运行版本或服务端控制台 |

所有 HTTP 节点带 `Authorization: Bearer {{#env.DEMO_API_TOKEN#}}` 与 `X-Workflow-Run-Id: {{#sys.workflow_run_id#}}`。HTTP 超时为连接 10 秒、读写 30 秒；自动重试关闭。环境变量不传入模型提示或用户回复。前台输入只保留可选 `demo_reference_date`，默认使用员工上下文返回的业务日期；原 `demo_case` 输入已删除。

公开 DSL 不填写真实地址或令牌；主代理另行生成私密运行版。不要在此包 README、测试记录或报告中粘贴凭证。

## 节点对照

| 节点 | 改造职责 |
|---|---|
| N01 → H01 → N02 | GET `/workflow/v1/context`；员工、组织 ID、业务日期与 21 项交通来自接口；城市名称只向模型说明范围 |
| N03 / R01 | 保留原语义提取与唯一一次解析修复提示、结构化输出 schema 和模型配置 |
| N04 / R02 | 保留原证据、字段、增量与恢复校验，仅把城市/交通事实信号和修复上下文改为接口范围 |
| N05P / R03 / N05G / N05U | 原首次计划、恢复计划、统一聚合与拆包机制 |
| N06 | 原草稿增量合并与整轮回滚机制 |
| C01 → H02 → N07 | 前置 `json.dumps` 打包原地点和默认起点；POST `/workflow/v1/cities/resolve`；只根据 HTTP 的唯一匹配产生城市编码 |
| N07I / N07T / N07A / N07P / N07G | 原交通推荐与互斥汇合机制；N07A 接 N07 输出的新 `context_json`，保留 API 映射 |
| N08 / N09 | 原提交分流、草稿核对与状态打包；去掉模拟权限/历史检查旧提示 |
| N10 → S00 | 单独“确认提交”、版本/指纹/缺失/恢复门控；JSON 创建体和确定性请求号打包 |
| S02 | 仅接 S00 非 HTTP 分支，传递拒绝或已成功同版本回放结果，避免空结果进入聚合 |
| H03 → Q01 → Q00 | GET `/workflow/v1/submissions/{requestId}`；解析原回执，确认找不到才允许同号创建 |
| Q02 | 仅传递 Q00 已有回执或未知结果分支，保持结果聚合互斥 |
| H04 → S01 | POST `/mock/v1/travel/applications`；普通与失败出口均进入 S01，读取真实返回与错误说明 |
| S99 | HTTP 网络异常、回执解析失败或 S01 缺输出时，保留 UNKNOWN、草稿和同一请求号 |
| N11 / N12 / N13 / N14 | 唯一结果聚合、状态一致性检查、唯一状态写回与回复；N12 增强指纹与新回执字段检查 |
| E01 / E99 | 保留解析/系统异常保护；明确提交调用可能已到达本地模拟接口，不虚称从未创建 |

## 城市与交通规则

每轮查询默认出发地及所有非空 `from_city` / `to_city` 原值，因此站点别名、实际首段起点、链路补全来源、返程终点均有 HTTP 查询依据。完全相同查询去重；不在 Code 中请求网络。

一个查询只有一条匹配才可产生编码；多条要求用户明确，零条继续追问。查询原文加入该条结果的 aliases，避免一个查询的歧义被另一查询的规范名称旁路。昆山使用苏州编码，保留昆山原始地点和映射说明；桐庐显示为桐庐，编码仍为 `330122`；深圳北站由接口取得 `DEMO_SHENZHEN`。`cityNames` 不充当校验通过结果。

交通 `code` 直接采用接口 `value`（如 `火车-一等座`），支持规范全名、选项简称及高铁/动车等有依据的火车别名。不把飞机商务舱或头等舱替换为经济舱。未指定交通仍由原推荐节点建议并展示来源。

## 提交、回执与幂等

创建 JSON 根对象为 `remark/dqydbg/trips/applicantId/departmentId/payerCompanyId`。普通差旅 `dqydbg=null`，短期异地办公为 `Y`；行程为 `dateFrom/dateTo/cityFrom/cityTo/tool`。组织 ID 来自上下文接口。所有 POST 正文由前置 Code `json.dumps` 生成，HTTP 整体引用，事由含引号或换行也保持合法 JSON。

H04 同时传 `X-Client-Request-Id`、`X-Draft-Id`、`X-Draft-Version`。请求号由草稿 ID、版本、完整指纹和已保存的明确失败重试计数确定。回复或状态写回丢失时，下一次相同版本确认仍得到同一请求号；只有上一次明确 FAILED 且已写入会话时，下一次主动确认才增加重试计数。

每次真正允许提交时先查回执。为兼容 Dify 在非 2xx 时进入失败出口的行为，H03 调用工作流专用只读适配：

```json
{"code":"SUCCESS","data":{"httpStatus":404,"result":{"code":"SUBMISSION_NOT_FOUND","message":{},"data":{}}}}
```

外层 HTTP 200 不意味着创建成功；Q01 读取 `data.httpStatus` 与 `data.result`，原 404 只说明暂时没回执，可以继续用原请求号创建。适配层实际复用原 GET `/mock/v1/submissions/{requestId}`，原接口仍保持 404 语义。

成功必须满足原创建 `code=SUCCESS`、`action=AI_CREATE`、`demoOnly=true`、请求号一致且有实际 `applicationId/applicationNo/createdAt`。`MOCK_SUBMIT_FAILED` 为明确 FAILED，保留草稿与确认版本并显示 `message.text`。网络中断、不一致返回、409/422 等需要查证的状态标 UNKNOWN，不宣称创建成功或业务失败。409/422 尽可能显示接口实际说明；若网络故障未提供 body/status，S01 失败后由 S99 保留 UNKNOWN。

`last_submission` 保留 `demo_only=Y/draft_id/revision/fingerprint/application_no/reply_text/date_start/date_end`，新增 `application_id/request_id/status/message/created_at/retry_count`。状态仅在真实成功后变为 `SUBMITTED`；已成功同版本确认回放保存结果。创建记录不会用于历史行程冲突校验。

## 主代理后续验收

需要确认当前 Dify 版本能导入 HTTP 原始文本 JSON body、环境 Secret、失败分支和聚合节点；再配置私密地址与令牌，发布应用，以新增城市＋站点别名跑通页面 → Dify → 网关 → 模拟系统链路。核对成功单号一致、重复确认不增单、失败说明一致、恢复成功后新请求号，以及网络异常后同号恢复。老会话若保留旧编码，提交会因指纹变化要求重新查看确认单；不自动放行旧确认。
