# Contract Test Kit 职责与 interface 收敛

- 状态：已确认
- 日期：2026-09-07
- 领域词汇：`../CONTEXT.md`
- 范围：Contract Test Kit、其全部当前调用者及相应用例

## 1. 职责

Contract Test Kit 通过真实 Catalog admission 和 runtime 执行代表性的 Module Package
用例，提供被测 Node 的实际输出和证据，检查共同的 extension、execution、data 与
provenance 契约。具体科学结果、应执行的 engine 及调用次数由 package-owned tests
明确断言。

runtime 与 Run Evidence Ledger 继续拥有通用因果闭合规则及其 owner tests。Kit 使用
现有 typed evidence，不复制 reducer、不建立第二套证据模型、不从实际事件推断本例
应发生的科学行为。

Operation Attempt 可以包含零、一个或多个 Engine Invocations。Kit 删除无条件要求
Engine Invocation 存在的规则，以及用整个 Run 的事件类型集合代替目标 Node 证据的
检查。上游 Node 的调用不能满足所属测试对被测 Node 的调用预期。

## 2. 两个聚焦的 interface

### Port conformance

独立检查所属 Port Type 的代表性合法值、非法值拒绝和 canonical codec roundtrip。
通过真实 Catalog admission 取得 Port Type，不要求调用者同时提供可执行 Workflow。
每个 Port case 的科学值与非法样例仍由其 owner 提供。

### 单 case 执行

一次调用执行一个 case。case 只描述执行输入，包括被测 Node、Execution Binding、
参数、Environment Configuration、Project Inputs 及必要的上游 Nodes、Edges 和
Workflow 科学配置。支持用上游 Nodes 构造真实输入，不限制 Workflow 只能有一个 Node。

Kit 拥有隔离存储、Workflow Commit、实际执行、等待终态、取值和资源清理的完整
生命周期。它专注一次独立的成功 conformance 执行；失败执行不能返回成功结果。
不增加 Cache replay、取消、重启或失败传播模式，这些行为继续由现有 owner tests 验证。

返回值提供已解码的目标输出、Artifact 内容及关联到目标 Node 的现有 typed evidence，
保留所属测试检查 exact Port、Result Identity、Candidate identity、lineage、Method、
Metric、Observation Context 和实际 engine 调用所需的信息。使用既有 evidence 的
Node Attempt、Operation Attempt 和 Invocation 关联键，不能仅按事件类型筛选。

所有供断言使用的内容在清理前取出；返回后不依赖仍存活的 runtime、打开的文件或
临时目录。输出解码使用实际 Port codec，不另建科学值转换规则。Artifact 内容按精确
`artifact_reference` 保留，通过既有 publication 元数据关联 Port 和 Candidate；同一
Port 的多个 Artifact 不得相互覆盖。

## 3. pytest 拥有用例组织与科学断言

删除 case 中的 `expected_scalar_outputs`、`expected_candidate_counts`、
`expected_observation_counts` 和 `expected_artifacts`。所属测试对实际结果使用普通
pytest 断言，数量只是其中一种预期，不代替身份、单位、数值和关联检查。

case-specific credential hygiene 检查同样留在所属测试中，保留对实际公开输出与
证据的检查；不能用新 Kit 结果摘要代替真实公开内容。凭据卫生不因删除预期字段而丢失。

多个 case 由 pytest 参数化组织。删除 Kit 的批量执行、批量汇总报告和仅服务这些
报告的序列化；不引入通用断言 DSL、callback registry 或兼容入口。普通 pytest 默认
行为使各 case 独立报告，用户显式选择的 fail-fast 等运行选项仍由 pytest 决定。

## 4. 原子迁移

同步迁移所有现有 Kit 调用者、fixture case 声明、Kit 自身测试和相关文档，再删除
被替代的 interface 与无调用辅助代码。现有科学断言须逐项保留到所属测试，不能把
批量成功报告机械替换为多次仅检查 succeeded 的测试。

生产 Module Package Registration 继续只描述生产契约，测试 case 与 fixtures 保持
独立。本次不扩展为全仓库 Run helper 重构，不合并其他历史回归文件，不改变科学
生产行为、public protocol 或 real-Provider Acceptance Campaign。

## 5. 验证

- 合法零调用 case 成功；一个和多个调用的实际证据可以由所属测试准确断言。
- 有上游调用时，目标 Node 的调用集合仍只包含其自身调用；移除目标调用会使明确
  要求该调用的所属测试失败，上游证据不能替代。
- 返回的目标输出与 Artifact 内容可在 Kit 完成清理后断言，并保持 exact identity。
- Port conformance 无需执行 case；非法 codec、非法输出与失败执行不能通过检查。
- 现有 fixture 的 credential hygiene 与各 package 的科学预期在迁移后保留。
- pytest 独立收集迁移后的每个 case；同步更新受影响的显式 selectors 和 markers。

运行受影响 Kit 与 package 的 focused tests，然后运行：

```bash
.venv/bin/python -m verification.backend routine
.venv/bin/python -m verification.backend deterministic-acceptance
```

mock 不能替代必需的 real-Provider acceptance。默认门禁通过也不宣称完成全部
Provider 验收；迁移中若触及真实 Provider 验收用例，仍须按其现行契约验证。
