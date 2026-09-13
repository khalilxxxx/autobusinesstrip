# 智能差旅提单完整 Demo 设计

日期：2026-09-12。目标：用户打开本地页面即可连续对话、核对申请、修改、确认提交，并在模拟系统中看到成功单据或失败回执。

## 范围与依据

用户已要求以目标方式自主搭建完整 Demo，并提供现有「小智 AI 助理」截图。沿用浅紫背景、左侧新建／历史会话、右侧消息区的布局。补齐截图未展示的底部输入、发送状态、申请核对操作与错误恢复。另设模拟差旅控制台，避免在助手日常操作中显示接线或调试细节。

业务沿用已确认范围：固定普通员工、21 项交通、50 条国内城市，默认都有提单权限；无 M5 切换、住宿城市字段或住宿接口。创建结果由本地成功／失败开关决定，不执行员工权限、历史行程冲突等实际提单业务校验。保留现有助手的字段完整性、城市／交通选项、日期和路线整理，以及确认版本保护。

本地到 Dify API 已真实验证通过；Dify 会话变量查询 API 也已确认可读取 `cv_session`，可据此取得草稿与确认状态，无须从回复文字推测能否提交。

## 部署选择

推荐延续 Dify Cloud，页面与模拟系统在本机运行，Dify 经专用 HTTPS 通道访问带鉴权的模拟接口。这能复用已配置的模型和现有 Chatflow。将整个后端部署到云端会增加账号与运行维护成本；改成本地 Dify 则需要重新搭建 Dify 与模型配置，当前机器尚无 Docker。

用户已确认仅在本机演示，允许按需求新建或修改工作流。当前选择备份并修改已有测试应用，沿用已验证密钥；Dify 仅通过带鉴权的专用接口通道访问模拟数据。公开通道不暴露聊天代理、管理页、Swagger、场景开关或密钥配置。

## 架构与职责

1. 助手页面：管理新会话与历史会话，显示真实 Dify 回复、草稿核对、提交与重试状态。采用 React + TypeScript + Vite，构建产物由现有 FastAPI 提供。
2. 本地助手后端：持有 Dify 应用密钥，保存本地会话与消息，维持 Dify `user`／`conversation_id`，调用聊天及会话变量接口，管理同一会话串行请求和请求回放。
3. Dify Chatflow：继续使用 MVP1.2 的语义提取、增量合并、修复／恢复、交通建议与状态写回机制。将写死的员工、交通、城市和模拟创建改接 HTTP 接口。
4. 模拟差旅 API：复用现有 FastAPI／SQLite 与公司截图对应的请求响应格式。扩展工作流适配接口和调用记录，既有创建与城市接口保持兼容。
5. 专用接口网关：单独监听 `127.0.0.1:8767`，要求服务端 Bearer 凭证，只接受工作流所需的固定路径。需要云端联调时由临时 HTTPS 通道转发到该网关。主服务继续监听 `127.0.0.1:8766`。

## 页面与状态

助手入口 `/assistant`。左侧显示「小智 AI 助理」、新会话、按时间排列的历史会话和模拟差旅系统入口。右侧有会话标题、服务状态、浅色聊天背景、消息气泡、表格与底部输入。空白会话提供 3 条差旅示例。用户可 Enter 发送、Shift+Enter 换行，中文输入法选词不会误发。

助手消息支持安全 Markdown；原始 HTML 不执行。草稿可继续通过自然语言修改；仅当前已核对版本显示「确认提交」，发送时带当前草稿 ID、版本和指纹。过期确认按钮、重复点击与刷新不能重复创建申请。已成功单据显示模拟单号与查看详情入口。

模拟控制台入口 `/simulator`，包含成功／失败切换、失败说明、申请列表、申请详情、回执查询和最近接口调用记录。当前数据均为模拟数据。切换场景不重放旧请求；明确失败后再次主动提交使用新请求号。

## 本地助手 API 契约

所有时间字段为 ISO 8601 字符串。助手 API 使用 JSON，无业务信封；错误为 `{"error":{"code":"...","message":"中文说明"}}`。模拟 API 继续使用既有 `uuid/code/message/data` 信封。

- `GET /assistant/api/status` → `{ready, appName, employeeName, bridgeConfigured}`，不返回任何密钥。
- `GET /assistant/api/conversations` → `{items:[{id,title,createdAt,updatedAt,phase}]}`。
- `POST /assistant/api/conversations`，请求 `{}` → 新会话详情。
- `GET /assistant/api/conversations/{id}` → `{id,title,createdAt,updatedAt,messages:[{id,role,content,createdAt,status}],state,activeTurnId}`。
- `POST /assistant/api/conversations/{id}/messages`，请求 `{text,clientRequestId,confirmation?}` → HTTP 202 `{turnId,status}`。`confirmation` 为 `{draftId,revision,fingerprint}`；仅确认提交按钮传入。
- `GET /assistant/api/turns/{id}` → `{id,conversationId,status,answer,error}`，状态为 `running/succeeded/failed/uncertain`。前端轮询正在执行的任务，展示逐步收到的答案；完成后刷新会话。

`state` 为 `{phase,canSubmit,draftId,revision,fingerprint,lastSubmission,pending}`。`phase` 对应 `IDLE/COLLECTING/READY_TO_CONFIRM/SUBMITTED`，未成功同步时 `canSubmit=false`。`lastSubmission` 如有结果，包含 `status,applicationId,applicationNo,requestId,message`。原始 `cv_session` 只存服务端，页面不展示实现字段。

同一会话同一 `clientRequestId` 重传返回同一个任务；换内容返回冲突。另一请求在当前请求运行中返回忙碌。应用重启将未完成任务标为中断，提示核对已保存消息及提交回执；不自动重发可能创建单据的请求。

## 工作流接口接入

- 员工与交通通过现有 `GET /mock/v1/employee-context`、`GET /mock/v1/transport-options` 取得。
- 城市仍调用 `POST /mock/v1/cities/query`，表单只有 `filter`；工作流适配层可批量整理本轮所需地点，逐个查询并保留明确映射。
- 创建仍调用 `POST /mock/v1/travel/applications`，直接发送 `remark/dqydbg/trips` 及固定演示组织扩展。普通差旅 `dqydbg=null`，短期异地办公为 `Y`。
- 提交请求同时携带 `X-Client-Request-Id`、`X-Draft-Id`、`X-Draft-Version`。工作流只在用户明确确认、版本与指纹一致时进入创建。成功读取真实模拟单号，失败读取 `message.text`，不在节点内编造单号。
- 不确定结果先查 `/mock/v1/submissions/{requestId}`。查不到不等同于业务失败；保留草稿和请求标识，避免把不确定结果当作新申请重发。
- 对接成功后同步清理原 Demo 的模拟权限／历史冲突分支与旧提示。测试时间可保持可选，前台不显示无关调试输入。

## 验收标准

1. 浏览器进入页面，新会话可完成缺信息追问、补充、生成往返草稿及修改，刷新与历史切换后内容保留。
2. 至少使用一个新增城市与一个站点别名，真实工作流调用城市接口并正确使用编码；交通候选来自 21 项接口。
3. 确认提交成功后，助手与模拟系统显示同一模拟单号；重复点击／重复确认不会创建第二张相同草稿版本的单据。
4. 切换失败场景，确认提交显示实际失败说明，无成功单据；恢复成功后主动重试成单，原失败回执仍可查询。
5. 接口调用记录证明本地页面 → Dify → 网关 → 模拟 API 的链路运行；网络异常时保留草稿、提示可恢复操作。
6. 浏览器代码与响应不包含 Dify 或网关密钥；无鉴权、错误鉴权及未开放路径无法通过公网网关。
7. 适当的自动测试、构建检查与真实浏览器端到端流程通过；提供一键启动、停止通道、重启注意事项和中文演示步骤。

## 最新验证范围

用户于 2026-09-12 明确本次不做批量测试，后续将自行使用 Luna 执行。保留已经完成的自动验证；剩余仅做必要修复检查与少量真实端到端验收，不开展批量用户模拟测试。
