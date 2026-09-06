# Workflow Commit admission 的共同科学规则

- 状态：已确认
- 日期：2026-09-06
- 领域合同：`CONTEXT.md` 的 Workflow Commit、Execution Plan 定义

## 范围与所有权

在现有 Workflow authoring module 内集中既有 Commit 的科学 admission，覆盖普通
重新加载、canonical seed 复用和 WebUI example 复用。各入口继续拥有原有的 Project
安装、Workflow 一致性检查和发布政策。

私有 interface `_admit_existing_commit(commit, plan)` 接收保存的 WorkflowCommit
以及当前 FrozenCatalog 编译的 ExecutionPlan。调用方须编译该 Commit 的 Workflow，
或先确认 shipped Workflow 与保存的 Workflow 相等。共同入口比较科学定义快照，
成功后才构造、缓存并返回 VerifiedWorkflowCommit。

比较对象仍为 compiler 收集的最小、与结果有关的科学定义快照。未被 Workflow 使用的
Catalog 科学定义变化不阻止复用。Snapshot 内容与顺序、Commit identity 和 Run evidence
合同均保持不变。

## 失败与生命周期

科学定义不一致时抛出 `workflow_commit_identity_mismatch`，details 包含旧
`workflow_commit_id`；不缓存不一致的 Commit／Plan，不替换或重写旧 Commit。
WebUI example 复用遵守与普通加载和 canonical seed 相同的拒绝政策。
若示例复用在启动期间失败，错误继续向上传播并终止应用启动。

编译仍在原位置发生。示例安装先编译，再创建 Project 或安装输入；编译失败仍为
`compile_rejected`，不会因编译失败安装一个新 Project。Shipped Workflow 本身变化
继续被安装入口拒绝，不自动发布新 revision。

新 Commit 直接从同一个 Execution Plan 生成科学定义快照，经持久化成功后缓存。
该发布流程不增加重复 admission。普通 warm lookup 继续信任当前 owner、当前
FrozenCatalog 下已 admitted 的缓存；重启后重新编译和 admission。
既有示例安装调用仍先编译，不新增绕过原有流程的缓存捷径。

本次不改变 Draft 编辑、持久化机制、Derived Run 的 Plan retention 或公共协议。

## 验证

通过现有 authoring interface 验证三条路径成功复用和科学定义不一致；拒绝之后旧
Commit 与 Draft 保留，后续执行查找仍拒绝该不一致的 Commit。覆盖 Workflow 不一致
的拒绝和编译失败早于 Project 安装。保留既有持久化失败、旧 active Commit 保留测试。

通过生产启动入口验证仅 WebUI example 使用的 Method 科学定义变化导致启动拒绝，
未被两个示例使用的 Method 变化允许启动，恢复原 Catalog 后继续复用原 Commit。
使用真实 declarations、Catalog compiler、admission 和临时持久化，不执行 Provider。
运行 focused tests、backend routine 与 deterministic-acceptance。
