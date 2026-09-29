# Workflow Commit admission 的共同科学规则

- 状态：已确认
- 日期：2026-09-06
- 产品约束更新：2026-09-22
- 领域合同：`CONTEXT.md` 的 Workflow Commit、Execution Plan 定义

## 范围与所有权

Workflow authoring module 拥有可执行 Commit 的科学 admission，覆盖普通 Commit
重新加载、canonical seed 复用，以及显式关闭预置结果加载
（`load_example_results=False`）时的 WebUI example 编译安装。
各入口拥有相应的 Project 安装、Workflow 一致性检查和发布政策。

canonical Workflow 是面向用户的教程示例，其 Project 随应用正常启动安装是产品要求。
后续结构优化须保留正常启动中的安装和用户可见的教程示例；验证任务对该 Workflow
的复用不改变其教学身份。

默认启动通过 `install_bundled_example_results` 安装随包提供的 WebUI 结果，信任随包
owner records，不为展示旧结果重新编译 Workflow 或比较当前 Catalog 科学定义。
这不改变 canonical seed 的编译安装，也不免除后续执行查找所需的 Commit admission。
预置结果合同见[示例结果规格](2026-09-19-webui-example-results-spec.md)。

私有 interface `_admit_existing_commit(commit, plan)` 接收保存的 WorkflowCommit
以及当前 FrozenCatalog 编译的 ExecutionPlan。调用方须编译该 Commit 的 Workflow，
或先确认 shipped Workflow 与保存的 Workflow 相等。共同入口比较科学定义快照，
成功后才构造、缓存并返回 VerifiedWorkflowCommit。

比较对象为 compiler 收集的最小、与结果有关的科学定义快照。未被 Workflow 使用的
Catalog 科学定义变化不阻止复用。

## 失败与生命周期

科学定义不一致时抛出 `workflow_commit_identity_mismatch`，details 包含旧
`workflow_commit_id`；不缓存不一致的 Commit／Plan，不替换或重写旧 Commit。

canonical seed 和显式 WebUI example 编译安装先编译，再创建 Project 或安装输入；
编译失败为 `compile_rejected`，不会因编译失败安装一个新 Project。
这两条安装路径拒绝 shipped Workflow 变化，不自动发布新 revision；
启动期间发生的安装失败向上传播并终止启动。

新 Commit 直接从同一个 Execution Plan 生成科学定义快照，经持久化成功后缓存。
该发布流程不增加重复 admission。普通 warm lookup 信任当前 owner、当前
FrozenCatalog 下已 admitted 的缓存；重启后的执行查找重新编译和 admission。

## 验证边界

authoring 测试覆盖可执行 Commit 的成功复用、科学定义不一致、Workflow 不一致、
编译失败早于 Project 安装，以及持久化失败时旧 active Commit 与 Draft 的保留。
使用真实 declarations、Catalog compiler、admission 和临时持久化，不执行 Provider。

默认启动的预置结果加载与显式编译安装分别按各自合同覆盖，不能把后者的拒绝政策
套用到旧结果展示。当前验收记录见[集成交付与验收记录](2026-09-19-webui-integration-progress.md)。
