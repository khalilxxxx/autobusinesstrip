# 旧版保护与实施验证记录

日期：2026-09-13。此文件随实际执行更新；需求中的验收场景不是测试通过的证据。

交付结论：生命周期扩展已完成，最终功能代码为 `4f0ecec3a0aad75c2e11491d3bba00e9b375b825`。最终全分支审查发现的两项 Important 已修复，限定复查逐项确认 ADDRESSED，未发现修复引入的新 Critical/Important；没有遗留问题或需裁决的延期项。新版保留在 `feature/travel-lifecycle` 及其独立工作树运行，原目录 `main` 和旧 Dify 工作流保持原版。

- 新助手：<http://127.0.0.1:8876/assistant>；新模拟控制台：<http://127.0.0.1:8876/simulator>。
- 新 Dify：<https://udify.app/chat/R8lohnltNjSNQ4hI>，已发布 #2（51 节点、87 连线）。
- 原助手：<http://127.0.0.1:8766/assistant>；原模拟控制台：<http://127.0.0.1:8766/simulator>。
- 当前新 Dify 通过本机临时隧道连接模拟接口；本机服务和隧道需保持运行。重启后如地址变化，按 `模拟差旅系统/使用说明.md` 仅更新新应用。

## 原版保存

- 原版提交：936c625b6627cc17916895cd62998063ea586e1e；标签：demo-baseline-20260913。
- 纳入 Git：119 个文件，含 AI 助手前端/后端、模拟接口、依赖锁、启动脚本、原工作流 DSL/节点/构建来源及需求文档。
- 私密快照：原目录 .baseline-backups/20260913-153710，26 份数据库一致性备份/配置文件；manifest.json 关联 baseline hash 和源码文件哈希。运行凭证不进入 Git。
- 独立工作树：.worktrees/travel-lifecycle；分支：feature/travel-lifecycle。
- 旧服务：127.0.0.1:8766（PID 38279）、8767（PID 38283）；新版独立服务使用 8876、8877。

## 原版实际回归

在新工作树的原版源码上执行，功能实现前：

| 检查 | 实际结果 |
|---|---|
| Python 后端：python -m pytest tests -q | 76 passed，3.86 秒 |
| 原工作流：python -m unittest discover -s tests -q | 55 tests，OK |
| 前端：npm test | 6 files / 41 tests passed |
| 前端：npm run build | TypeScript 校验及 Vite build 成功 |

依赖安装输出含上游 whatwg-encoding 弃用提示和 pip 自身版本提示；上述测试与构建均无失败。新工作树使用独立 .venv 和 node_modules，构建只写新工作树 dist。

## 旧 Dify 只读核验

- 名称：差旅申请助手-MVP1.2-测试。
- 应用 ID：9f14a8eb-d849-41cb-8dbd-b66829b17edb。
- 从 Dify UI 导出当前已保存版本，未勾选 Secret 值；下载时间 2026-09-13 15:45:23。
- 39 节点、69 连线；逐节点对比业务数据与本地 baseline DSL 一致。
- 导出保存在私密基线目录 dify-online-export.yml，用于联调后复核。
- 仅读取/导出，未修改节点、环境变量或发布旧应用。
- 收尾再次脱敏导出（下载文件“差旅申请助手-MVP1.2-测试 (8).yml”）：仍为 39 节点、69 连线，节点业务数据、连线和环境配置与开始时导出完全一致。当前界面显示旧发布 #6、约 10 小时前发布；本次未发布旧应用。
- 本地收尾核对：119 个 sourceHashes 全部一致；25 份非数据库文件与私密备份逐字节一致；原 server/gateway PID 38279/38283 均存在，旧助手 `/health` 为 HTTP 200。

## 新版验证

- 新 Dify 应用已新建：差旅助手-单据生命周期-V2。
- 新应用 ID：5a6513c5-507f-4525-ace6-d3e4e6d67964；与旧 ID 不同。16:32 导入新工作流并发布 #1，50 节点、85 条边；Dify 检查清单显示所有问题均已解决。
- 独立 API Key 写入新版 .local/lifecycle-dify.json，权限 0600；实际 GET /info 返回 HTTP 200，应用名称匹配。
- 新网关配置 .local/lifecycle-bridge.json 使用独立 token，upstream 为 127.0.0.1:8876；独立隧道 batch-formula-instant-fix.trycloudflare.com 已启动。
- Task 1 提交 2db2d57，日期极值修复 b323f9b；独立审查及修复复查通过。
- Task 2 初版 cb4b2d0：后端总计 149 项通过，新 DSL 4 项通过。独立审查发现 5 项问题，已进入集中修复；不以测试通过代替审查通过。
- 首轮真实助手查询未来成功，经本地助手→Dify→新网关→新版业务接口返回 6 张样例；sys.user_id 映射、GET params、空 cv_session 同步成功。
- 真实创建草稿→查询今日→继续“确认提交”成功，创建草稿及 fingerprint 查询前后相同；新建 DEMO-CL-20260913-CAC6B0B29935 为 S002/D。其后真实自然语言撤回成功 S005，编辑重提准备保留原号和未改字段。
- 今日位置回复仅显示去返段而未明确当天停留，已记录为联调发现，随 Task2 修复后复测。
- 新版运行中的真实 HTTP 链路完成 17 个断言：首次 S002、串行变更、S003 拒撤回、S005 占在途、原号重提、当前轮撤回、S005 变更作废恢复前序、旧状态不可复活、新变更重建、两代有效切换、旧号当前解析、乱序审批拒绝、最新作废无恢复、空查询与非法查询区分。证据位于新版私密 .local/qa/live-api-evidence.json，脚本为同目录 live_api_matrix.py。
- 真实重提后仍为原单号、轮次为 2，审批历史含 create/withdraw/resubmit/start/complete；随后真实自然语言同时修改返程、事由、类型、部门和付款公司并确认变更，服务端实值一致。批准前原单 S004/YBG 有效、新变更 S002/D 未生效，批准后新单有效，重复原完成请求不重复增加版本或历史。
- 真实旧单号查询返回新变更当前内容；旧内容未返回。旧号关联提示及草稿误标有效的文案问题已交 Task2 同批修复。
- 公网携带正确新网关凭证访问 seed、approval、会话列表三条非白名单路径均为 HTTP 404，不能访问本地管理能力。证据 .local/qa/live-gateway-evidence.json。
- 新 App 已于 18:26 发布 #2（51 节点、87 边），检查清单仍为全部通过。真实“今天在哪里”返回上海停留区间；2026-09-11 移动日明确杭州、上海并说明无法判断全天单城；旧号详情明确已关联当前单据。
- 真实双草稿会话中，“确认提交”只请求明确目标、两份草稿保持；“确认提交新申请”成功创建 DEMO-CL-20260913-638E2DCE94F0，变更草稿原 ID 和内容保持。证据 .local/qa/dualdraft-transcript.jsonl。
- 同一真实双草稿会话随后插入历史查询、修改原变更草稿、输入“不要撤销刚才的修改”、确认提交变更，均保持正确目标。第二代变更完成后，重复前代审批完成请求未回退当前指针；最新单作废为 S100，根单／前代／最新单三个引用均指向已作废最新单，旧版未恢复。
- Task2 两轮独立复查最终通过，head fb00095。第二轮修复陈旧确认拒绝的同 run 重放，并兼容五种常用单据名称；`test_lifecycle_workflow.py` 定向 52 passed，原 UNKNOWN 恢复回归通过。新 DSL 本轮未变。

前端办理界面与正式运行脚本已在 2a83ab9 提交，首轮审查修复 da21643；全部任务独立审查与限定复查通过。最终全分支审查及最后两项修复复查也已完成，详见下方最终验证记录。

## Task 3 自动验证与浏览器预检

代码提交：2a83ab9a1b0f954aa5f5edca1417c9d49a474a9e。实现任务实际执行：

| 检查 | 实际结果 |
|---|---|
| 前端 npm test -- --reporter=dot | 7 files / 50 tests passed |
| 前端 npm run build | 1934 modules，933 ms，成功 |
| 后端 .venv/bin/python -m pytest tests -q | 182 passed，11.19 秒 |
| 新工作流 unittest discover | 5 tests，1.589 秒，OK |
| git diff --cached --check | 通过 |

原草稿字段校验的焦点测试曾真实失败，已把基于定时器的聚焦改为错误 DOM 提交后聚焦，保留原断言；完整前端套件通过。Chrome 预检发现 fixed 单据面板被页头裁切，修复为 React portal，并先运行两个失败断言再验证修复。主代理在 Chrome 实际复测：完整标题、筛选、11 张记录和详情区域可见，裁切消失。后续真实办理验收见下节。

## 正式运行与浏览器办理验收

- 正式入口已加载最终功能代码 `4f0ecec`：server PID 54874、gateway PID 54880，沿用新 tunnel PID 47506。8876 `/health` HTTP 200，`lifecycle_control.py status` 确认三个进程均运行；服务切换均按 PID、完整命令与启动身份核对后，仅替换新版 server/gateway。旧服务未操作。
- Chrome 中完整打开查询面板、单据详情和独立编辑器。实际办理测试单 `DEMO-CL-20260913-8443A2DCC949`：S002 撤回后为 S005；事由编辑、差异保存、同号重提回 S002；模拟控制台开始审批／完成后为 S004。原号、轮次 2 和 create/withdraw/resubmit/start/complete 连续历史经真实 API 核对。
- 旧页面仍显示 S002 时点击撤回，服务端拒绝过期请求；界面提示“单据已变化”，刷新为审批完成，没有回退业务状态。
- Chrome 变更表单实际修改部门、付款公司、差旅类型、事由和返程日期，并添加／删除第三段；保存后完整差异列出四字段及返程变化。提交后生成 `DEMO-BG-20260913-4916C291F347`，真实 DTO 确认前序 S004/YBG 有效、新单 S002/D 尚未生效。
- 页面撤回该变更至 S005，出现“作废本次未生效变更”；作废后变更 S100/D，前序恢复 D、继续有效且无在途，随后重新发起变更成功。证据 `.local/qa/ui-runtime-evidence.json`。
- 正式入口实际 Dify 对话“请作废差旅变更单 DEMO-BG-20260913-A7F1F3C6F653”成功，返回 S100 和前序仍有效说明。此项补验了 fb00095 常见单据名称兼容修复，证据 `.local/qa/commonphrase-transcript.jsonl`。
- 真实“收起编辑器→插入查询→继续编辑”发现未保存输入丢失，已在 da21643 修复并经 Chrome 完整复测通过。独立复查确认刷新 loading、会话残留、UNKNOWN 编辑锁／按会话请求持久化、端口前置校验、基础选项错误与重试六项 Important 及 gateway 路径提示均已处理，无新增 Critical/Important。

- 实际通过另一窗口保存同一会话草稿使 revision 从 1 变为 2，再在 Chrome 旧页面点击保存：返回“草稿已变化”，本地输入完整保留，“保存并查看差异”和“放弃本次编辑”恢复可用，界面没有永久忙碌。随后放弃验收草稿、作废当前有效申请成功，真实 DTO 为 S100、currentEffectiveId=null。

## 最终修复、复查与整合验证

最终全分支审查范围为 `936c625..a299e58`，由独立审查者完成，共发现 Critical 0、Important 2、Minor 0。两项问题集中修复为 `4f0ecec`；另一位独立审查者仅复查 `a299e58..4f0ecec`，逐项确认已解决，修复差异没有新增 Critical/Important，也无范围外观察。没有裁决保留或延期的问题。

| 最终发现 | 修复结果与验证 |
|---|---|
| HTTP 200 UNKNOWN 或 FAILED 恢复时过早清除本地请求 | UNKNOWN 保留原请求；浏览器无本地记录时从服务端重建恢复入口；成功／失败先通过新会话内 recover 路由同步助手终态与草稿锁，只在同一请求终态且解锁后清除。自动测试覆盖 UNKNOWN、FAILED、无 localStorage 和其他请求终态隔离。网关白名单未扩展。 |
| 同一草稿自然语言更新后，旧表单可能覆盖新 revision | 未编辑表单自动同步新版本；有未保存内容则保留输入并提示冲突、禁用保存和提交；用户可显式采用最新内容。自动测试与真实 Chrome/Dify 复测均通过。 |

代码版本 `4f0ecec` 的完整测试与构建由实现任务执行并记录；主代理核对提交范围、限定复查结果，并完成同版本真实浏览器与服务验收。此后仅修改交付文档，没有再次变更功能代码：

| 命令 | 实际结果 |
|---|---|
| 前端 npm test -- --run --reporter=dot | 7 files / 62 tests passed |
| 后端 .venv/bin/python -m pytest tests -q | 187 passed，12.07 秒 |
| 前端 npm run build | 1934 modules，974 ms，成功 |
| 新 Dify DSL（最终修复未变更） | 5 tests OK，沿用已执行结果，无需重新导入或发布 |

Task3 首轮六项修复的定向测试先实际得到前端 6 failed / 后端 4 failed，再得到前端 10 passed、runtime+gateway 12 passed。最终两项修复的新增回归在旧实现上实际得到前端 5 failed，后端恢复路由 HTTP 404；修复后上表完整验证通过。

最后一轮 Chrome 验收使用真实 Dify 会话 `81505fb0d9bf41febbb581ccf375df44` 和同一草稿 `db9f8bb576a34287a85b8032c60dcbed`：

1. 打开编辑器但不修改，收起后自然语言将事由改为“客户项目驻场培训”；同一草稿更新到 revision 2，重开编辑器自动显示新事由，差异一致。
2. 表单输入“QA 本地未保存的事由”而不保存，收起后自然语言改为“客户现场专项验收”；草稿更新到 revision 3。重开后本地输入保留，显示版本冲突，保存／提交均禁用。
3. 点击“使用最新草稿内容”后，载入“客户现场专项验收”，冲突消失，保存／提交恢复可用。
4. 点击“放弃本次编辑”结束验收，真实 API 确认草稿为空、原单 `DEMO-SEED-未来差旅` 仍为 S004/D、有效且无在途变更，没有提交新变更。

真实观察和前后服务数据保存在 `.local/qa/syncqa-ui-evidence.json`。收尾再次读取新版运行状态，新旧 8876／8766 `/health` 均为 HTTP 200。

## 真实链路执行范围

1. 新版助手自然语言创建申请草稿，中途查询未来单据后继续提交；验证草稿内容不变，新单为 S002。
2. 助手撤回新单，再编辑重提；核对单号不变、轮次递增、连续历史保留。
3. 查询演示当天的停留城市及移动日，答案说明为申报或批准安排。
4. 基于已完成有效单据，用自然语言同时修改返程、事由、类型、部门、公司，核对差异后提交；检查双方 tflag 与有效指针。
5. 仅在模拟审批接口推进至完成，再用旧单号查询当前有效版本；发起第二代变更并审批，作废最新版本后不恢复前代。
6. 变更撤回至 S005 后作废，检查变更 S100/D、直接前序恢复 D，允许重新发起。
7. 验证 S003 撤回拒绝、否定和咨询不执行、外网网关不开放模拟审批和样例端点。
8. 浏览器核对新助手单据面板、独立编辑器、状态按钮和模拟控制台；最后核对旧版源码、配置与线上导出未变。

上方第 1–7 项的主业务路径已执行，证据见前文；第 8 项的浏览器前端验收也已按上节执行。网络丢响应和并发通过自动化故障注入及 SQLite 多连接测试验证，不声称真实 Dify 网络故障已被人工制造。

## 43 项场景证据索引（随最终联调更新）

下表按需求编号定位已执行的自动测试或真实服务证据。单元／接口测试与真实模型对话分开记录，浏览器实际办理验收见前文。

自动测试简称：Core=`tests/test_lifecycle.py`；Query=`tests/test_lifecycle_query.py`；API=`tests/test_lifecycle_api.py`；Assistant=`tests/test_lifecycle_assistant.py`；Workflow=`tests/test_lifecycle_workflow.py`。测试路径均在新版 `模拟差旅系统` 下。

| 场景 | 业务与自动测试证据 | 真实链路补充 |
|---|---|---|
| Q01 | Query：日期交集、temporal、跨年及日期上下界 | 首轮未来查询及今日查询成功 |
| Q02 | Query：cross_year_stay_and_moving_day_city_intersection | fixqa 真实今日回复明确上海停留 |
| Q03 | Query：移动日保留起止城市及说明 | fixqa 真实 2026-09-11 回复明确杭州、上海及日期数据边界 |
| Q04 | Query：effective_pending_status_temporal_and_pagination | nl-change-approved.json 保存审批前两单效力 |
| Q05 | Core：multigeneration_references；Query：version_is_selected | 旧号只返回新内容，关联提示真实复测通过 |
| Q06 | API：seed_is_repeatable；Core：ybx_and_foreign_document | 首轮未来列表含 S005/S003/S002/S004 |
| Q07 | Workflow：ambiguous_withdraw_requires_unique_object | Chrome 列表选择详情后办理通过；自然语言多候选澄清由自动测试覆盖 |
| Q08 | Query：invalid_filters；Core：ybx_and_foreign_document | live-api-evidence 区分空结果和 422 |
| Q09 | Query：version_is_selected_before_city_and_date_filters | HTTP 旧号解析当前内容 |
| W01 | Core：change_withdraw_void；Assistant：query_detail_withdraw | creation 对话实际撤回 S002→S005 |
| W02 | Assistant：employee_cannot_approve_or_withdraw_s003 | 运行接口 S003 撤回 409 |
| W03 | Core：withdraw_racing_first_approval_has_one_winner | HTTP expectedVersion 拒绝陈旧请求 |
| W04 | Core：resubmit_keeps_number_history | 实际历史 create/withdraw/resubmit/start/complete |
| W05 | Core：change_withdraw_void_restores_direct_predecessor | creation 对话第二代变更撤回 S005 |
| W06 | Core：resubmit_keeps_number_history；receipt_never_reveals_superseded_submission_contents | 原号重提后轮次 2，连续历史保存；S001 仍区分本地草稿 |
| W07 | Core：resubmit_keeps_number_history | live-api-evidence：新轮未审批可再次撤回 |
| W08 | Core：idempotency_failure_receipts_restart_identity_and_content | 真实原号重提成功 |
| V01 | Core：multigeneration_references_hide_old_content_and_void_never_restores | live-api-evidence 最新有效单作废 S100 |
| V02 | Core：普通 S005、YBX、已替代版本操作拒绝 | 真实 S005 变更作废为允许的特殊路径 |
| V03 | Core：two_connections_only_one_racing_operation_succeeds | live-api-evidence：S002 在途阻止前序作废 |
| V04 | Core：change_withdraw_void_restores_direct_predecessor | nl-change-void-evidence：作废变更后前序 D/有效/无在途 |
| V05 | Core：multigeneration_references_hide_old_content_and_void_never_restores | live-api-evidence：最新作废后 currentEffectiveId=null |
| V06 | Workflow：unknown_action_recovers_original_id_on_new_dify_run | 故障注入测试验证，未注入线上网络故障 |
| C01 | Core：change_withdraw_void_restores_direct_predecessor | nl-change-approved：前序 YBG/新单 D，审批完成切换效力 |
| C02 | Core：multigeneration_references | 实际基于已批准变更再生成第二代 |
| C03 | Core：two_connections_only_one_racing_operation_succeeds | live-api-evidence：S002/S005 在途均拒绝另建 |
| C04 | Core：change-change 并发测试 | SQLite 多连接验证 |
| C05 | Core：cancel_second_generation_only_restores_direct_predecessor | 实际变更撤回与 S005 作废分为独立操作 |
| C06 | Core：full_payload_validation；Workflow：patch_inherits_fields | 真实仅延返程，未改去程保留 |
| C07 | Core：ybx_and_foreign_document；旧版写入拒绝 | 服务端统一资格验证 |
| C08 | Core：resubmit-void 并发；业务状态约束 | live-api-evidence：作废后的旧重提/审批均被拒 |
| C09 | Core：cancel_second_generation_only_restores_direct_predecessor | live-api-evidence 覆盖提交/退回/重提/撤回/作废及获批 |
| C10 | Core：change_records_reason_and_all_editable_nontrip_fields | 真实模型同轮修改四个非行程字段＋返程，实值核对通过 |
| C11 | Core：multigeneration_references | live-api-evidence 第二代前后效力正确 |
| C12 | Core：change_withdraw_void_restores_direct_predecessor | live-api-evidence：取消旧尝试后另建并批准 |
| X01 | Assistant：query_detail_withdraw_preserve_create_state_bytes；LifecycleExperience：pristine/dirty revision | 创建草稿和 fingerprint 查询前后相同；生命周期查询后编辑保持原目标；真实 Chrome 验证新 revision 自动同步及未保存输入冲突保护 |
| X02 | Workflow：negative_inquiry_and_cancel_never_write | 否定取消与咨询误判回归及独立复查通过；实际“不要撤销刚才的修改”保留草稿 |
| X03 | Assistant/Workflow：UNKNOWN 恢复、原请求号重放；LifecycleExperience：UNKNOWN/FAILED 同步、无本地记录恢复、请求终态隔离 | 故障注入和恢复 run 投影回归通过；陈旧确认拒绝稳定回放；最后修复补齐 UI 与助手终态同步，未人工制造线上网络故障 |
| X04 | Core：状态机幂等和版本检查 | 实际重复完成请求回原结果；乱序前代审批不回退 |
| X05 | Core：success_receipt_of_replaced_document_resolves_current_content | 真实旧号仅返回最新变更内容 |
| X06 | Core：resubmit-void 并发 | 两连接最多一个成功，陈旧请求被拒 |
| X07 | Core/Assistant：操作无 reason 的成功路径 | 实际撤回/作废/重提/变更均未要求填写操作原因 |
| X08 | Core：持久失败回执；Workflow：未知请求先恢复再停止本轮 | 成功回执与后续失败分别持久化，无自动回滚已作废变更 |
