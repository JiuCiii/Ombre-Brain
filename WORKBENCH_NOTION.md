# Ombre Brain 工作台

> 此文件是 Notion 工作台的同步草稿。Notion 连接器加载后，以 Notion 页面为主要协作记录。

## 当前结论

- 不部署或复刻 kiwi-mem，只吸收适合 Ombre Brain 的设计。
- 当前最高原则：记忆操作必须可追踪、可纠错、可撤销。
- Markdown 继续作为人类可读的主要记忆存储；SQLite 作为旁路审计账本。
- 自唤醒日志是系统事实，不是 Ombre 记忆。只有 Claude 主动决定时才写入 Ombre。

## 已完成：安全底座

- 新增 `.ombre/audit.db` 追加式审计账本。
- 创建、修改、自动合并、归档、删除、恢复、回滚均保存前后快照。
- 删除改为移动到 `.ombre/trash/`，不再物理删除。
- `trace(restore=True)` 恢复软删除。
- `trace(history=True)` 查看审计事件。
- `trace(revision=事件ID)` 回滚历史版本。
- 新记忆记录 `source_type`、`source_ref`、`memory_kind`。
- Feel 记忆标记为模型推断，并链接源记忆。

## 已完成：召回与作用域

- 新增严格 `scope`，与语义分类 `domain` 分离。
- 指定 `scope` 后不会回退全局记忆。
- 严格作用域覆盖搜索、主动浮现、重要度拉取、随机漂浮、Feel、Dream、自动合并与会话 Hook。
- 普通检索只增加 `matched_count` 和 `recalled_count`。
- 普通检索不再刷新 `last_active`，也不再增加热度。
- `trace(confirm=True)` 才增加 `confirmed_count`、`activation_count` 并触发时间涟漪。

## 与自唤醒的边界

- `xiaoke-wake` 的 `logs/*.jsonl` 和 `state/wake-journal.jsonl` 保持独立。
- 自唤醒不自动写 Ombre Brain。
- Ombre 不读取或迁移自唤醒日志。
- 将来 Hook 接入自唤醒时必须传明确 `scope`。

## 测试状态

- 五阶段完整回归：52 passed，7 skipped。
- `xiaoke-wake` 未产生代码或数据修改。

## 下一阶段候选

### 高优先级

- 面板增加历史时间线、Diff、恢复、回滚与来源展示。

## 已完成：安全合并与 Dream 提案

- 默认 `merge_mode: proposal`，相似记忆不再自动覆盖目标。
- 新内容先保存为独立源桶，再生成合并提案。
- 批准合并后才更新目标并软删除源桶；失败时恢复源桶。
- 拒绝提案不会修改任何记忆。
- Dream 洞察只生成待审核提案，不直接修改、resolve 或删除事实。
- 批准的 Dream 洞察保存为 `memory_kind: inference`，默认有效期 30 天。
- 审核前可以展示源记忆、目标记忆和拟合并内容。
- 新增 MCP 工具 `review_proposals` 和 Dashboard 审核 API。

### 中优先级

- 补充来源：对话 ID、原始消息引用、人工确认状态、可信度。
- 记忆关系：`derived_from`、`supersedes`、`contradicts`、有效期。
- 审计账本保留周期与压缩策略。

### 仅讨论，暂不实施

- 审计事件哈希链与篡改检测。
- 日、周、月、季、年日历压缩。
- 自动清理或自动永久删除。
- 自唤醒自动写入 Ombre。

## 已知风险

- 历史旧记忆没有来源字段，读取时会兼容为 `unknown` / `global`。
- Dashboard 尚未提供提案审核界面，目前先通过 MCP 工具和审核 API 操作。
- Dashboard 尚未提供审计历史和回滚界面。
- Hook 目前无独立作用域密钥；若未来暴露给更多调用方，需要补认证设计。

## 部署与迁移

- `python migrate_safety_metadata.py`：只检查旧记忆，不写入。
- `python migrate_safety_metadata.py --apply`：补齐 legacy 来源、作用域和召回计数字段，并记录审计事件。
- Docker 会复制新增模块；`.ombre/` 位于记忆持久卷内。
- Render 配置的持久磁盘会保存审计账本、提案数据库和回收区。
- 本地开发阶段全部完成；剩余外部发布动作是确认部署仓库后提交、推送并触发 Render 发布。
