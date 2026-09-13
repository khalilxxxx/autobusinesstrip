# 单据生命周期独立 Dify 应用

应用名：`差旅助手-单据生命周期-V2`。可导入文件：`差旅助手-单据生命周期-V2-可导入.yml`。

构建只读深拷贝原 `完整Demo_Dify接入/差旅申请助手-完整Demo-可导入.yml`，不调用原构建脚本、不修改原 DSL。新应用 ID 与旧应用独立；构建不进行线上导入或发布。环境变量 `DEMO_API_BASE_URL`、`DEMO_API_TOKEN` 均为空，实际新网关地址和凭证由私密运行配置注入。

```bash
模拟差旅系统/.venv/bin/python 交付物/单据生命周期_Dify/build_dsl.py
模拟差旅系统/.venv/bin/python -m unittest discover -s 交付物/单据生命周期_Dify/tests -v
```

新版共 55 节点、93 条边。新增链路为：原开始节点 → LC_STATE（只读创建编辑标志）→ LC_CONTEXT → LC_ROUTER → LC_PACK → LC_VALID → LC_TURN → LC_UNPACK → LC_BRANCH。仅有效 `handled=false` 经 LC_CREATE 明确新申请确认口令归一化后进入原 H01；`handled=true` 进入只读查询问答门控或直接回复，不经过 N13，不写 `cv_session`。所有 Code 节点不联网。

## 只读查询问答

查询成功可附加 `answerContext={question,businessDate,filters,total,shown,documents,cityNames}`。`documents` 为本轮展示的最多三张单据，保留单号、状态、效力及 `request.trips` 原始日期／城市编码／交通；`cityNames` 为编码到名称的映射。LC_UNPACK 校验计数、日期和明细结构，剔除 `locations/stay` 等预推理字段后，才输出 `answer_ready=true`。

可靠上下文走 LC_QA_GATE → LC_QA（只读 LLM）→ LC_QA_RESULT → LC_QA_ANSWER。模型只根据本轮事实回答：普通查询一句总数和卡片提示；具体问题结合原始交通段区分停留日、移动日、已批准／未批准／作废。超过展示范围时明确总数及目前展示数量，不声称分析全部，也不把申报行程当作实际定位。

没有可靠上下文时直接显示 LC_UNPACK.reply。问答 LLM 或结果 Code 失败、模型输出为空时也沿用这条已取得的回复；不重执行业务 HTTP，不进入创建链，不写会话变量。该分支与创建节点没有下游连线，模型重试关闭。

## 上下文和命令

`GET /workflow/v1/lifecycle/context?user=<sys.user_id>&creationEditing=true|false` 返回直接 JSON。`creationEditing` 为可选参数，由 LC_STATE 从现有 `conversation.cv_session` 计算，后端保存到独立生命周期上下文，并与本地创建编辑状态取逻辑或。它用于直接 Dify 预览的双草稿确认保护，不接收或覆盖创建草稿内容。初次纯查询的原 `cv_session` 是有效 JSON 字符串 `{}`。

`POST /workflow/v1/lifecycle/turn` 请求结构：

```json
{
  "user": "demo-local-本地会话ID",
  "query": "确认提交变更",
  "command": {
    "intent": "CONFIRM",
    "confirmation": {
      "draftId": "上下文中的草稿ID",
      "revision": 2,
      "fingerprint": "上下文中的指纹"
    }
  },
  "clientRequestId": "lifecycle-Dify工作流运行ID"
}
```

`user` 与请求号只由 `sys.user_id`、`sys.workflow_run_id` 打包。LLM 只输出允许的 `intent/reference/resultIndex/filter/patch`。唯一附加系统字段 `command.confirmation` 由 Code 从已读取 context 的 draft 原样注入，LLM 不得输出。服务端严格校验并核对当前草稿版本。用户同轮既编辑又确认时只保存新版，需再次确认。

路由会从 CHANGE／RESUBMIT 首句提取明确 patch。已选或唯一单据的原明细为简单两段闭合往返时，“改成去北京”只修改去程目的城市和返程出发城市；其余字段保持。复杂行程或目标含糊时不猜修改范围，需澄清后编辑。核对以最新草稿内容及卡片为准。

本地 cid 按 `assistant_conversations.dify_user` 映射；直接预览用独立 Dify 用户标识自动建立演示会话，仍仅固定演示员工 `DEMO_EMP_001`。command 无法切换员工或审批身份。不存在的 `demo-local-...`、已删除会话不能借此重新创建。

## 前端接口

以下助手接口直接返回 `{documents,selectedDocument,draft,lastReceipt,querySummary,cardGroups,pendingAction}`，不包 `data`；表内 `/mock/v1/` 接口仍使用业务 `data` 包装。生命周期业务 DTO 来自已有 `LifecycleService`。

| 接口 | 用途 |
| --- | --- |
| `GET /assistant/api/conversations/{cid}/lifecycle` | 恢复结果、选中单据、草稿及最新办理回执 |
| `POST .../lifecycle/query` | 请求为生命周期 filters；不覆盖任何编辑草稿 |
| `POST .../lifecycle/prepare` | `{reference,mode:"change"或"resubmit"}` |
| `PUT .../lifecycle/draft` | `{draftId,revision,payload}`；完整 payload 校验后增加 revision 和 fingerprint |
| `POST .../lifecycle/submit` | `{draftId,revision,fingerprint,clientRequestId}` |
| `POST .../lifecycle/action` | `{reference,action:"withdraw"或"void",expectedVersion,clientRequestId,reason?}` |
| `DELETE .../lifecycle/draft` | 只放弃本地编辑，不作废单据 |
| `GET /mock/v1/lifecycle/options` | 现有部门、公司、类型、城市、交通主数据 |
| `GET /mock/v1/lifecycle/receipts/{clientRequestId}` | 按原号查真实业务回执，现有本地业务 API，响应包 `data` |

错误为原助手 `{error:{code,message,details?}}` 形状。`draft` 含 `id,revision,mode,targetId,targetVersion,payload,original,differences,fingerprint`；请求发出后未确认结果增加 `requestId` 并锁定编辑。`lastReceipt` 使用业务服务 `{clientRequestId,status,result,...}`；未知时 `status=UNKNOWN`。界面应保留原请求号并用同一提交体重试。纯查回执后需重新请求生命周期 state 或重试原提交以同步本地草稿完成状态。

查询结果只保存结果 ID，读取时总是投影当前可见内容；选中对象不因业务旧编号读取重定向而静默执行当前新单的撤回或作废。变更/重提只通过有版本确认的 draft 提交；不提供绕过草稿的直接变更 action。

`cardGroups` 的 `kind` 区分 `query|document|draft|receipt`。`turnId` 指定消息展示位置，`interactionTurnId` 记录办理所属轮次；用户发起新一轮时旧组办理按钮立即禁用，刷新后继续保持只读，查看入口可用。草稿组携带当轮 `draft` 快照；原目标已替代或版本变化时不再展示失效快照。QUERY 缓存重放只读重查当前可见内容，不修改当前结果指代、选中对象或卡片组。

## 办理约束

- 查询和详情不修改创建草稿或生命周期编辑草稿；新结果清除旧的列表指代，仍保留编辑目标。
- 多张结果不猜对象。变更准备不能覆盖另一份本地草稿。
- S003 需模拟控制台正常退回；S002 在途变更应先撤回，取得回执后再单独作废，绝不合并承诺整趟已经作废。
- 原号重提继承未显式修改字段，增加提交轮次，沿用单号。变更由业务服务管理链和有效版本。
- `tripUpdates` 用一基 index。单字段改日期仅在原交通段明确同日时保持同日；跨日段需同时明确出发和到达日。新增段必须完整；城市、交通、闭环等统一由业务服务校验。
- “不要撤回”“能作废吗”不办理；“撤销刚才的修改”只放弃本地编辑。助手没有审批接口。
- 未知结果先恢复持久化的原请求和原业务内容，不随下一次 Dify run 更换业务请求号。成功回执如已对应后续版本，明确说明“原操作结果已查到；以下为当前单据”。

网关只新增上述 context/turn 两条固定路由；不开放本地生命周期管理、审批、种子、会话列表或任意转发。日志只记录方法、固定路径和状态码，不记录凭证、请求体或查询参数。

本轮已完成本地自动验证及真实 Dify、浏览器验收，独立新应用 `5a6513c5-507f-4525-ace6-d3e4e6d67964` 已发布第 4 版。普通查询只回复统计；停留日／移动日回答、当句城市变更、语义作废、历史按钮置灰及抽屉直接提交均已通过真实链路核对。原 Dify 应用保持不变。测试范围和实际单据状态见 [聚焦卡片与简洁对话验收](../../docs/superpowers/verification/2026-09-13-focused-travel-cards.md)。
