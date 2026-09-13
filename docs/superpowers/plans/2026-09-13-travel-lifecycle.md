# 差旅单据生命周期扩展实施计划

> **执行方式：** 使用 superpowers:subagent-driven-development 按任务实施并审查；用户已于 2026-09-13 明确授权开始实现，无须再次确认执行方式。

**目标：** 在保留原版 Demo 和 Dify 应用的前提下，实现查询、撤回、作废、连续行程变更及 S005 原号编辑重提。

**架构：** 本地 SQLite 业务服务统一计算状态、有效版本和操作资格，所有写操作在事务中重验并保留请求回执。新 Dify Chatflow 增加生命周期意图分支，通过受限网关调用本地业务；原有申请草稿流程继续使用独立 cv_session。前端新增单据卡片和变更编辑器，与创建草稿分别保存。

**技术栈：** Python/FastAPI/SQLite、React/TypeScript/Vite/Vitest、Dify Chatflow YAML。

**需求依据：** `docs/superpowers/specs/2026-09-13-travel-document-lifecycle-requirements.md` V0.5。

## 全局约束

- 工作目录仅使用 `/Users/khalil/Documents/智能提单项目/.worktrees/travel-lifecycle`，分支 `feature/travel-lifecycle`。原目录代码与运行配置不改。
- 已完成原版 Git 基线 `936c625b6627cc17916895cd62998063ea586e1e`，标签 `demo-baseline-20260913`。数据库一致性快照、私密配置在原目录 `.baseline-backups/20260913-153710`；凭证不入 Git。
- 新 Dify 应用名 `差旅助手-单据生命周期-V2`；旧应用 `差旅申请助手-MVP1.2-测试`，ID `9f14a8eb-d849-41cb-8dbd-b66829b17edb`，禁止修改旧应用的节点、环境变量、配置和发布内容。
- 新本地服务用 8876，网关用 8877；数据库、`.local`、前端 dist 位于新 worktree。旧 8766/8767 链路保留。
- S002 可撤回至 S005，按本次提交轮次判断；S003 不可员工撤回。S005 编辑重提沿用原单号、保留连续审批历史，回 S002。
- 变更串行不限次数。变更提交/撤回/编辑重提/审批完成始终前序 YBG、新单 D。审批完成之前前序有效，完成之后新单有效。
- S005 变更作废为 S100/D，直接前序恢复 D 且仍有效；允许之后另建变更。S005 普通申请不能作废。
- S004 仅当前有效、未转报销、无在途变更可作废或再变更；作废即 S100，不恢复被替代旧版。S002/S003/S005 变更都占用在途名额。
- 已被替代旧版不能出现在员工列表/详情/历史还原中；旧单号只解析当前单号。历史差旅按行程日期仍可查询。
- 查询先过滤有效/可见版本再匹配日期城市，区间交集包含跨月跨年；某日停留由相邻交通段推导，移动日不声称全天在一个城市。
- 查询不覆盖创建草稿或生命周期编辑草稿。原因本期均非必填；变更允许修改事由、类型、部门、公司、日期城市交通及增删行程段。
- 不实现报销流程、报销锁或员工审批动作。YBX 的基本资格限制保留；模拟审批只在本地模拟控制台开放。
- 所有对用户的说明和错误信息使用中文。每个实现任务先运行实际业务失败测试，再实现、验证、提交；审查只读，不重复跑已有同代码测试。

## 文件职责与接口边界

- `mock_travel/lifecycle.py`：业务状态、事务操作、版本链、请求回执与操作资格。
- `mock_travel/lifecycle_query.py`：查询过滤、城市和停留日期推导。
- `mock_travel/lifecycle_api.py`：模拟业务/审批 HTTP 适配；`lifecycle_seed.py`：可重复、非破坏性演示样例。
- `mock_travel/lifecycle_assistant.py`：独立会话的查询结果、目标选择、变更/重提草稿、差异和确认快照。
- `mock_travel/lifecycle_workflow.py`：LLM 指令契约与 Dify HTTP 适配；不相信模型给出的状态、资格、用户身份或审批结果。
- `交付物/单据生命周期_Dify/build_dsl.py` 和 `prompts/router.md`：从原版脱敏 DSL 构建新 Chatflow，只向新文件写出。
- `frontend/src/components/DocumentPanel.tsx`、`LifecycleEditor.tsx`：查询结果、详情/可执行动作及独立编辑器。
- `lifecycle_control.py`、`run-lifecycle.sh`、`stop-lifecycle.sh`：独立运行链路，明确拒绝旧应用 ID/旧端口配置。

### Task 1: 持久化业务状态、版本链、查询和模拟接口

**文件：** 新建上述 lifecycle.py、lifecycle_query.py、lifecycle_api.py、lifecycle_seed.py；修改 store.py、app.py、catalog.py；测试 tests/test_lifecycle.py、tests/test_lifecycle_query.py、tests/test_lifecycle_api.py。

**接口：**
- `LifecycleService(store)`，挂到 `app.state.lifecycle`。
- `document(reference, applicant_id="DEMO_EMP_001") -> dict`：按 ID/单号员工查询；旧引用返回当前可见单据并有 `resolvedFrom`，绝不返回旧内容。
- `list_documents(filters: dict, applicant_id="DEMO_EMP_001") -> {items,total,limit,offset}`。
- `operate(reference, action, request_id, expected_version, payload=None, reason=None, applicant_id="DEMO_EMP_001") -> dict`：员工动作 `withdraw|void|change|resubmit`；写入绝不自动改指向替代版本。结果有 `clientRequestId,action,document,demoOnly`。
- `approve(reference, action, request_id, expected_version, reason=None) -> dict`：仅模拟控制台 `start|complete|return`。
- `receipt(request_id, applicant_id="DEMO_EMP_001") -> dict`：持久化成功/业务失败回执，同号同内容重试回原结果，同号异内容 409。
- 单据 DTO 兼容原 `applicationId,applicationNo,createdAt,request,demoOnly`，扩展 `status,tflag,documentType("APPLICATION"|"CHANGE"),version,submissionRound,rootId,rootNo,predecessorId,currentEffectiveId,isEffective,isSuperseded,pendingChangeId,history,actions,tripStart,tripEnd`。`actions` 为 `{withdraw:{allowed,reason},void:{allowed,reason},change:{allowed,reason},resubmit:{allowed,reason}}`。
- `request` 继续使用 ApplicationRequest 字段及城市编码。历史记录含动作、前后状态、轮次、时间、执行角色、可选原因；后台持久化每次提交内容快照，员工不开放旧版本内容。
- HTTP：GET `/mock/v1/lifecycle/documents`，GET `/mock/v1/lifecycle/documents/{reference}`，POST `/mock/v1/lifecycle/documents/{reference}/actions`，GET `/mock/v1/lifecycle/receipts/{request_id}`，POST `/mock/v1/lifecycle/documents/{reference}/approval`，GET `/mock/v1/lifecycle/options`，POST `/mock/v1/lifecycle/seed`。
- actions JSON 为 `{action,clientRequestId,expectedVersion,payload?,reason?}`；approval 同形但无 payload；HTTP 使用原 envelope，错误用 ServiceError。
- 查询 filters：`keyword,city,dateFrom,dateTo,temporal("past"|"current"|"future"),dateBasis("trip"|"submitted"),status,effectiveOnly,limit,offset`；全为可选，默认 trip、可见单据、20/0。
- options 提供 departments、payerCompanies、travelTypes、transports、cities；新增 DEMO_DEPT_002 演示研发部、DEMO_COMPANY_002 演示服务公司，保留原默认项。

- [ ] 先写并运行事务业务失败测试，覆盖以下完整路径：
```python
a = create_valid_application(store)  # 原 create 成功进入 S002/D，非 S004
a = approve_to_complete(service, a)
a1 = service.operate(a["applicationId"], "change", "change-1", a["version"], changed_payload)["document"]
assert service.document(a["applicationId"])["tflag"] == "YBG"
assert service.document(a["applicationId"])["isEffective"]
a1 = service.operate(a1["applicationId"], "withdraw", "withdraw-1", a1["version"])["document"]
assert a1["status"] == "S005"
service.operate(a1["applicationId"], "void", "void-change-1", a1["version"])
assert service.document(a["applicationId"])["tflag"] == "D"
```
- [ ] 使用 SQLite BEGIN IMMEDIATE 将资格重验、写入状态、直接前序 tflag、有效指针和回执放在一次事务中；增加在途唯一约束。原 store.create 成功同事务初始化 S002/D，不把既有无状态老数据批量视作 S004（迁移按待核对/未生效处理，新 DB 样例明确状态）。
- [ ] 写操作禁止操作已替代/他人/过期版本。重复 change、void 与 resubmit 竞态只有一个成功；失败回执可查询；回执重放前仍核对请求身份与内容。S002 重提轮次归零审批事实，但不清历史。
- [ ] 复用城市和交通主数据并进行真实日期、闭环、衔接、日期顺序、字段完整性、部门公司范围校验；允许历史日期，不增加行程冲突政策。继承动作由上层准备完整 payload，业务层仍拒绝漏字段/未知值。返回字段级问题。
- [ ] 查询按可见版本筛选，再做日期/城市交集；某日返回 `locations`（移动区间/停留区间及说明）；无时间移动日保留起止城市。S100 不用于 effectiveOnly 行程结果，S004 不能作为时间分类。旧单号即使关键词明确也不泄露旧 request 或历史提交快照。
- [ ] seed 可重复且不删除用户数据，生成历史、当前停留、未来、S002、S003、S005 普通/变更、YBX 样例；所有是 DEMO_EMP_001。模拟审批与业务端点分开。
- [ ] 测试包括 A→A1→A2、S005 普通作废拒绝、S005 变更取消后另建、作废有效 A2 不恢复、当前轮撤回、双线程并发变更/重提与作废、幂等冲突、重启回执、旧号重定向与隐藏、先选择版本再过滤、跨年交集、停留日和移动日。运行新测试以及原后端 tests，提交。
```bash
/Users/khalil/Documents/智能提单项目/模拟差旅系统/.venv/bin/python -m pytest tests/test_lifecycle.py tests/test_lifecycle_query.py tests/test_lifecycle_api.py -q
/Users/khalil/Documents/智能提单项目/模拟差旅系统/.venv/bin/python -m pytest tests -q
```

### Task 2: 助手生命周期会话、自然语言办理和新 Dify 构建

**文件：** 新建 mock_travel/lifecycle_assistant.py、lifecycle_workflow.py；修改 assistant_api.py、assistant_store.py（只做接入）、gateway.py；新建交付物/单据生命周期_Dify/build_dsl.py、prompts/router.md、nodes/、tests/、README.md；新增 tests/test_lifecycle_assistant.py、tests/test_lifecycle_workflow.py。

**消费：** Task 1 的 app.state.lifecycle、document/list_documents/operate/receipt/options 和 DTO；不得复制业务状态逻辑。
**产出：**
- `LifecycleAssistant(db_path, service)` 独立保存每会话的结果 IDs、选中引用、变更/重提草稿、revision、完整 payload、原始快照、目标版本、确认 fingerprint、办理回执；与创建 cv_session 独立。
- `GET /assistant/api/conversations/{cid}/lifecycle` 返回 `{documents,selectedDocument,draft,lastReceipt,querySummary}`。draft 形如 `{id,revision,mode("change"|"resubmit"),targetId,targetVersion,payload,original,differences,fingerprint}`。
- `POST .../{cid}/lifecycle/query` 接受 Task 1 filters；`POST .../{cid}/lifecycle/prepare` 接受 `{reference,mode}`；`PUT .../{cid}/lifecycle/draft` 接受 `{draftId,revision,payload}`（保存校验后更新 revision/fingerprint）。
- `POST .../{cid}/lifecycle/submit` 接受 `{draftId,revision,fingerprint,clientRequestId}`；`POST .../{cid}/lifecycle/action` 接受 Task1动作体加 `reference`；`DELETE .../{cid}/lifecycle/draft` 仅放弃本地编辑，不作废单据。相同客户端请求重试不能重复操作。
- `GET /workflow/v1/lifecycle/context?user=...` 返回当前创建草稿是否在编辑、生命周期草稿及选中/结果对象的最小必要信息、业务日期、可选字段。
- `POST /workflow/v1/lifecycle/turn` 接受 `{user,query,command,clientRequestId}`。返回 `{handled,reply}`；handled=false 才进入原创建流程。每次成功办理必须来自真实业务回执，未知结果明确保留原请求号。
- Dify command 采用严格允许列表，含 `intent`、可选 reference/resultIndex/filter/patch；intent 支持 CREATE_FLOW、QUERY、DETAIL、WITHDRAW、VOID、CHANGE、EDIT、RESUBMIT、CONFIRM、CANCEL、HELP。LLM 仅解析意图和用户明确字段，不决定状态/资格/身份/审批结果，不执行员工审批。
- 自然语言编辑 patch 支持 remark/dqydbg/departmentId/payerCompanyId，tripUpdates（一基 index + 变更字段）、addTrips、removeTripIndices；校验 index、字段类型和城市交通候选。没有改动字段沿用服务器原快照，不以默认员工数据覆盖。缺信息返回澄清且不丢草稿。
- Dify `sys.user_id` 与本地会话 dify_user 对应；直接 Dify 预览也可有独立 demo 员工会话，但不能通过 command 冒用另一用户。

- [ ] 编写失败测试：创建草稿在查询/详情/撤回后字节级保持；保存变更时继承未改公司部门；S005 原号重提；结果第二张定位、缺唯一对象提示；旧确认拒绝；同号重试回执；重启继续草稿；S003 助手不能审批/撤回。
```python
before = assistant_store.private_conversation(cid)["state_json"]
lifecycle.query(cid, {"temporal": "future"})
assert assistant_store.private_conversation(cid)["state_json"] == before
```
- [ ] 将明确对象的撤回/作废动作作为授权表达，执行前以服务当前版本和资格验证；多候选必须选择。变更先准备草稿展示差异，再根据该 revision/fingerprint 确认提交；查询插入不能让“确认提交”误交另一份草稿。
- [ ] 对 S002 在途变更说明先撤回再作废，对 S003 明确需模拟控制台正常退回，不能自动代替审批；每步独立回执，不能把部分成功说成作废整趟。
- [ ] 新 DSL 从原 `交付物/完整Demo_Dify接入/差旅申请助手-完整Demo-可导入.yml` 深拷贝，增加上下文 HTTP→LLM 路由→严格 JSON 打包→生命周期 HTTP→handled 分支；handled=false 连原 H01，handled=true 直接回复、不写 cv_session。全部错误有可恢复中文回复，Code 禁止联网。复用旧模型配置 deepseek-v4-flash、thinking=false，原 DSL 文件不写回。
- [ ] 正确构造初次纯查询会话 cv_session 默认有效空状态，避免 variables() 因生命周期分支从未跑创建初始化而失败；已有 cv_session 保持。新应用独立 env、DSL 发布文件为空密钥，私密运行文件由 Task3 生成。
- [ ] 网关 allowlist 只增 context/turn 必需路由，不暴露模拟审批、种子、所有会话或任意本地接口。记录请求但不记录凭证。
- [ ] 运行后端新增测试与全套，DSL 图连线/变量选择器/路径互斥/不写旧版/空密钥/Code 纯函数测试，提交。输出接口契约 JSON 示例供 Task3 使用。
```bash
/Users/khalil/Documents/智能提单项目/模拟差旅系统/.venv/bin/python -m pytest tests -q
/Users/khalil/Documents/智能提单项目/交付物/完整Demo_Dify接入/.venv/bin/python -m unittest discover -s 交付物/单据生命周期_Dify/tests -v
```

### Task 3: 前端办理体验与独立运行链路

**文件：** 新建 frontend/src/components/DocumentPanel.tsx、LifecycleEditor.tsx 及对应测试；修改 AssistantPage.tsx、SimulatorPage.tsx、api.ts、types.ts、styles.css；新建 lifecycle_control.py、run-lifecycle.sh、stop-lifecycle.sh；修改 dify_probe.py、assistant_api.py 的新配置路径加载；新增 tests/test_lifecycle_runtime.py、使用说明.md。

**消费：** Task2 的 lifecycle API 与 draft/DTO；Task1 模拟审批和种子接口。延续创建 DraftCard/DraftDrawer 与会话删除体验。
**产出：** 新 worktree 8876 助手和模拟控制台、8877 网关，独立 SQLite、Dify 配置、网关 token/隧道、构建 dist；原版 8766/8767 不受影响。

- [ ] 编写失败交互测试：列表打开详情→撤回按钮→S005；变更编辑包含部门公司、增删段、改日期→差异→确认；过期状态刷新；旧版不可打开；查询不关闭创建草稿；模拟审批按钮仅出现在模拟控制台。
```tsx
expect(screen.getByRole('button', {name: '查询单据'})).toBeEnabled()
expect(screen.queryByRole('button', {name: '审批通过'})).not.toBeInTheDocument()
```
- [ ] 在助手添加“查询单据”入口和持久结果面板，支持行程/提交日期、城市、状态和历史当前未来，展示绝对日期、状态/版本效力、当前有效和在途变更。详情展示路线和办理历史，不展示后台提交快照或旧版入口。自然语言回复后自动刷新相应面板。
- [ ] 详情的动作按后端 actions 显示/禁用并说明原因。撤回/作废在目标详情中可直接触发，不新增必填原因。作废要清晰区分“作废本次未生效变更”与“作废当前有效单据”；无旧版恢复入口。
- [ ] LifecycleEditor 独立于创建抽屉；编辑基本信息、城市、交通与日期、增删行程段；保存后展示前后差异及完整新安排，提交用当前 revision/fingerprint。网络断开保留填写/原请求号，并先查回执；查询插入不丢正在编辑内容；旧 revision 不能提交。表单校验问题以中文定位字段。
- [ ] 模拟控制台增加生命周期状态/有效标签、模拟开始审批/完成/退回按钮，按钮使用 expectedVersion；提供非破坏性“添加演示样例”。解释 S004 是审批完成、S005 保留连续流程。
- [ ] 独立启动脚本管理 PID+identity，只操作 worktree 自身进程。默认 server 8876/gateway 8877，启动时校验文件路径/端口；构建只写本工作树 dist。使用新 `.local/lifecycle-dify.json`、`.local/lifecycle-bridge.json`、`.local/lifecycle-processes.json`、`data/lifecycle.sqlite3`；配置保存新 app_id 并拒绝等于旧 ID。
- [ ] 新运行 DSL 生成到 `.local/差旅助手-单据生命周期-V2-本机运行.yml`，填新网关地址和独立 token，仅私密配置有 key。新网关用已有 cloudflared 官方二进制路径或同版拷贝，不重启原隧道。Dify UI 的新建/导入/发布由主代理在脚本就绪后操作。
- [ ] 更新中文启动与验收说明：baseline hash/tag、worktree 分支、端口、seed、两种作废、串行变更、报销不在范围、临时隧道地址变化仅更新新 App。
- [ ] 运行 frontend test/build 与后端全套，完成源码提交。不要把未执行线上测试写成通过。
```bash
npm test
npm run build
/Users/khalil/Documents/智能提单项目/模拟差旅系统/.venv/bin/python -m pytest tests -q
```

## 主代理联调与交付

- [x] 初始化旧版 Git、私密快照、基线 tag、新 worktree。
- [ ] 基线后端/前端/DSL 回归，记录实际结果。
- [ ] 每任务按 brief→实现→独立审查→必要修复审查执行；只有一个实现子代理同时写代码。主代理期间完成独立的 Dify UI 读取、旧版导出记录及运行准备。
- [ ] 用新运行 DSL 在 Dify 新建应用，确认新 App ID 与旧 ID 不同，再发布和配置本地新 Key；不覆盖旧应用。
- [ ] 新链路实际验证创建、查当前/未来/停留、撤回、S005 编辑重提、变更审批前后、S005 变更作废、串行第二代变更和最新作废不恢复。可通过 API 推进模拟审批，再在助手核对。
- [ ] 核对旧源码基线哈希与旧配置哈希未变，旧本地服务健康、旧 Dify 工作流仍原节点与发布版本。
- [ ] 最终全分支审查，针对结论完成修复与限定范围复查。把 43 场景映射到实际自动测试/线上证据，记录未覆盖或环境限制。
- [ ] 提交新分支成果，保留隔离 worktree 供用户运行；交付新旧入口、新 Dify URL、基线与新版 commit、验证证据文件。

