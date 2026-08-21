# 后端熵减与删除型重构调研

- 日期：2026-08-22
- 基线：`a739c1778b0ca1f7468f03e8aedefac4693be758`
- 审计范围：`core/`、`datatypes/`、`modules/`、`protein_workbench_public/`、后端测试、脚本、示例与仓库杂项
- LOC 口径：下文“产品代码”只指四个产品包与 `run_server.py`；`scripts/` 和 `examples/` 单列，不混入 52,800 行基线
- 排除：`frontend/`、`repositories/` 中的 pinned upstream，以及任何新功能设计
- 方法：静态代码与调用点盘点、AST 尺寸统计、运行时计数探针、规范/ADR 对照、测试职责审计

## 主要依据

本报告以仓库内的当前规范为准，不从现有实现形状反推科学含义：

- [`AGENTS.md`](../../AGENTS.md) 与 [`CONTEXT.md`](../../CONTEXT.md)：科学正确性、当前 vocabulary、trusted single-user trust model、无历史兼容义务；
- [`docs/codebase-redesign.md`](../codebase-redesign.md)：validate once、trust after admission、拒绝实现形状测试和兼容层；
- [`docs/protein_workbench_architecture.md`](../protein_workbench_architecture.md)：当前 owner、canonical operation、runtime/evidence 与 verification contract；
- [`ADR-0034`](../adr/0034-single-active-catalog-and-scientific-operation.md)：single active Catalog 与 canonical scientific operation；
- [`ADR-0025`](../adr/0025-execution-bindings-own-availability.md) 与 [`ADR-0029`](../adr/0029-readiness-follows-cache-miss-before-provider-entry.md)：Binding 对 Availability/Readiness 的现行声明职责；
- [`ADR-0039`](../adr/0039-node-outcomes-publish-atomically-through-immutable-value-objects.md)：immutable output value 与原子发布；
- [`ADR-0041`](../adr/0041-one-deep-module-owns-node-execution-attempt-lifecycle.md) 与 [`ADR-0042`](../adr/0042-run-evidence-ledger-owns-its-fact-grammar.md)：attempt deep module、Ledger fact grammar 与所有权；
- [`ADR-0043`](../adr/0043-acceptance-campaign-owns-one-canonical-plan.md)：唯一 15-tier acceptance plan；
- [`ADR-0044`](../adr/0044-one-folding-module-constructs-paired-prediction-outputs.md) 与 [`ADR-0045`](../adr/0045-one-simplefold-module-owns-provider-asset-closure.md)：folding output 与 SimpleFold provider asset closure。

## 结论

当前后端的主要问题不是“文件太长”本身，而是同一科学或协议事实被多个层级重复表达、重复校验、重复测试。单纯把巨型文件拆成更多文件，只会增加 seam 和导航成本，不会降低熵。

本次盘点得到三个核心结论：

1. 产品 Python 代码为 **52,800 行**；其中 `core/` 与 `modules/` 合计 **50,081 行，占 94.9%**。31 个超过 500 行的产品文件承载 **38,122 行，占 72.2%**。巨型文件确实高度集中，但其中既有应该缩小的混合模块，也有应该保留为 deep module 的 Ledger/attempt owner。
2. 后端测试为 **81,925 行，是产品代码的 1.55 倍**。问题不是测试多，而是相当一部分测试重复穿透私有实现、重复证明相同 Contract Test Kit 路径，或保留已结束的 cutover 形状。
3. 已证实的重复校验、私有死路径和无生产消费者 surface 形成约 **360–575 行**的高置信候选，但其中一部分是已导出的 Python Interface，不能全部视为“无行为变化的直接删除”。Port admission、Binding authoring 和 exact reference 进一步构成 **4,000–8,000 行产品代码、6,000–12,000 行测试**的设计 envelope；它们需要 ADR/Interface 决策，不是已承诺删减量。所有范围会互相重叠，不能逐项相加。

建议把任务定义为“**所有权驱动的删除型重构**”：每一波先指定唯一 contract-owning boundary，再删除下游重复表示、重复校验、兼容残留和实现形状测试。每个新抽象都必须通过删除测试：如果它不能删除更多旧接口、分支和测试，就不引入。

## 规范基线：什么可以删，什么不能删

本项目已经给出了非常明确的熵减方向：

- [`docs/codebase-redesign.md`](../codebase-redesign.md) 第 22–33 行规定，科学值和公开值只由拥有契约的 Interface 校验一次；进入内部后，storage、Evidence、cache 和 orchestration 应信任 admitted value。
- 同一文档第 62–72 行明确拒绝 admission 后重复校验、AST/私有调用顺序测试、兼容别名、旧 schema 和双实现。
- [`docs/protein_workbench_architecture.md`](../protein_workbench_architecture.md) 第 178–183 行规定 operation 信任 plan-normalized 参数和 admitted input，不重新编码、重算 digest 或重新解析引用。
- 同一架构第 191–225 行规定 direct route 不需要 Provider Readiness；Availability/Readiness 只服务 Adapter route 的真实 Provider entry。
- 同一架构第 691–707 行规定 Run Evidence Ledger 是 schema、因果、durability、reduction 和 public projection 的唯一 owner；现有 17 类 logical facts 必须保留各自含义。
- 同一架构第 842–859 行规定测试应以 Interface 为 surface，invalid case 只进入拥有 invariant 的 boundary；下游使用 admitted fixtures。

因此，本次重构的允许删除对象是：重复 ownership、重复 validation、重复 representation、历史 cutover、无调用 API、浅 wrapper、机械 authoring boilerplate、实现形状测试和未被消费的仓库杂项。

不得用“减行数”为理由删除或合并：

- Node Type、Method、Metric Definition 以及 unit、shape、missing-value 语义；
- residue identity/layout/map、mask、axis association；
- Candidate lineage、CDR join、selection conclusion；
- randomness、seed、provenance、Result Identity；
- 17 类 Ledger logical facts 及其 schema、causality、transaction、durable write 和 public projection；
- 12 个官方 Module Package、两个 folding binding、真实 Provider Adapter 与 15-tier acceptance；
- canonical bytes、digest、golden wire、package bundle 和 installed-package parity 所证明的当前契约。

## 定量基线

这里的 LOC 是物理行数，包含注释与空行，用于定位集中度，不代表复杂度本身。

| 区域 | Python 行数 | 文件数 | 占产品代码 |
|---|---:|---:|---:|
| `core/` | 22,586 | 18 | 42.8% |
| `modules/` | 27,495 | 79 | 52.1% |
| `datatypes/` | 1,915 | 8 | 3.6% |
| `protein_workbench_public/` | 798 | 4 | 1.5% |
| `run_server.py` | 6 | 1 | <0.1% |
| **产品合计** | **52,800** | **110** | **100%** |
| 支撑脚本 `scripts/`（不计入产品合计） | 893 | 4 | — |
| Python 示例 `examples/`（不计入产品合计） | 111 | 2 | — |
| 后端测试（含根 `conftest.py`） | **81,925** | — | 产品的 **1.55×** |

集中度：

- 产品代码中 31 个超过 500 行的文件合计 38,122 行，占 72.2%。
- 最大 10 个产品文件合计 23,398 行，占 44.3%。
- 产品 AST 中有 1,484 个函数、338 个类、201 个 dataclass；71 个函数超过 100 行，20 个超过 200 行，3 个超过 500 行。
- 测试中有 27 个超过 1,000 行的文件，合计 49,606 行，占全部测试的 60.6%。

最大的产品文件：

| 文件 | 行数 | 判断 |
|---|---:|---|
| [`core/run_execution_v2.py`](../../core/run_execution_v2.py) | 7,665 | 混合了 service、attempt、Ledger；不能按文件机械切割 |
| [`core/workflow_v2.py`](../../core/workflow_v2.py) | 2,699 | 编译、authoring、validation 所有权有重叠 |
| [`core/module_package.py`](../../core/module_package.py) | 2,500 | declaration/catalog authoring 过宽 |
| [`core/scoring_v2.py`](../../core/scoring_v2.py) | 2,099 | catalog 与 runtime descriptor 校验重叠 |
| [`core/port_types.py`](../../core/port_types.py) | 2,028 | generic envelope 与科学 codec 重复接纳 |
| [`modules/structure_transform/implementation.py`](../../modules/structure_transform/implementation.py) | 1,692 | 科学转换集中，优先审计接口而非拆文件 |
| [`modules/structure_transform/port_types.py`](../../modules/structure_transform/port_types.py) | 1,265 | nested axis codec 重复 validation 的主要实例 |
| [`datatypes/protein.py`](../../datatypes/protein.py) | 1,207 | provider-independent values；保留科学边界 |
| [`core/server.py`](../../core/server.py) | 1,196 | `create_app` 单函数约 1,099 行，路由装配过宽 |
| [`modules/acceptance_campaign.py`](../../modules/acceptance_campaign.py) | 1,047 | 15-tier owner；不能因尺寸拆散 canonical plan |

最大的内部对象也说明“长文件”并非同一种问题：`_RunEvidenceLedger` 约 2,499 行、`_NodeExecutionAttemptModule` 约 1,361 行、`V2RunService` 约 1,071 行。Ledger 是规范要求的 deep module；service/attempt 的风险则是外部 seam 泄漏和多种表示并存。应按 owner 和接口深度处理，而不是套统一行数上限。

## 已证实的重复校验

### 1. Workflow 参数在一次 compile 中被校验两次

证据：

- [`core/workflow_v2.py`](../../core/workflow_v2.py) 的 `_validate_parameter_values` 在第 917–1007 行定义；
- `_validate_static_semantics` 在第 1182–1193 行调用它；
- `compile_workflow` 又在第 2418–2429 行调用并消费 normalized parameters。

唯一 owner 应是 `compile_workflow` 的参数接纳/normalize 阶段。静态图语义验证应信任已接纳参数。删除静态语义中的重复调用，并删除只由测试使用的 `validate_workflow_parameter_values`（第 1010–1056 行）和无生产/测试消费者的 `validate_workflow_generation`（第 1059–1068 行）。

这是 P0 删除项：语义清楚、调用图闭合、风险低。

### 2. Port admission 当前是“encode 校验，再 decode 校验”

证据链：

- [`core/value_admission.py`](../../core/value_admission.py) 第 112–132 行的 `admitted_port_values` 先调用 `encode`；
- 同文件第 56–109 行的 `_admitted_from_canonical_bytes` 随后调用 `decode`；
- [`core/port_types.py`](../../core/port_types.py) 的 `PortTypeDefinition.encode` 在第 1358–1384 行校验，`decode` 在第 1386–1416 行再次校验；
- 多个 custom `from_wire` 又在进入 generic decode 之前自行校验。

对一个 aligned residue track 的计数探针显示，一次 admission 中顶层 track validator 被调用 4 次，layout domain validator 被调用 4 次，builtin residue-layout validator 又被调用 2 次；同一 layout 的验证路径总计达到 6 次。Nested axis association 还会通过 parent validation、child encode、child `from_wire`、child generic decode、parent generic decode 继续叠加。

目标接口应收敛为两个入口：

```text
admit_runtime(runtime_value) -> AdmittedValue
admit_bytes(canonical_bytes) -> AdmittedValue
```

每个入口一次性产生 canonical runtime value、canonical bytes、digest 和 projections；nested type 使用私有纯 codec，不再递归走完整 Port envelope admission。必须删除现有 encode→decode 回环、局部 envelope helper 和 custom/generic 双 validator，不能在旧路径上再包一层新 facade。

“trust after admission”只适用于 admitted value 的内存传播。object store、cache 或 Ledger 的 durable bytes 被重新加载时，仍必须通过 `admit_bytes` fail closed；durable-write seam 自身的 bytes/sequence/schema 检查也继续保留。不能把删除内存复验误解为信任未经接纳的持久化内容。

这部分的局部无争议删除约 80–180 行；完整所有权重构可能删除 2,000–4,000 行，但需要以 golden bytes、digest、residue axis/mask/projection 测试证明语义未变。

### 3. Catalog 已验证 descriptor，runtime 又验证其声明语法

证据链：

- [`core/module_package.py`](../../core/module_package.py) 中 `ObservationPropagationDefinition`（第 462–570 行）和 `ProducedObservationDefinition`（第 671 行起）拥有 declaration invariant；Catalog build 在第 2278–2341 行校验 descriptor 与 Port closure。
- [`core/scoring_v2.py`](../../core/scoring_v2.py) 第 1058–1148 行又检查 descriptor grammar；第 1660–1684 行再次检查 produced descriptor completeness。
- 同文件 `_admit_scoring_validation_ports`（第 1981–2036 行）和 `validate_produced_score_collection`（第 2039–2099 行）合计 117 行，只被测试使用；生产走 `validate_produced_score_collection_from_facts`。

删除 runtime 中“descriptor 是否构造正确”的分支；保留真正依赖当前 execution facts 的检查，例如 input 是否存在、互斥冲突、filter 语义、输出 fact 的精确对应和 axis shape。

两个 wrapper 没有生产消费者，但 `validate_produced_score_collection` 当前从 `core.__init__` 导出，并被多组测试直接调用。因此它是“无生产消费者的公开 surface”，不是私有 dead function。若确认 current public Python Interface 不再需要它，应在同一变更中删除 export、wrapper 和只为它存在的测试；不保留兼容 alias。

### 4. Public/storage/runtime 重复验证 Project/Run ID

[`protein_workbench_public/protocol.py`](../../protein_workbench_public/protocol.py) 第 413–484 行接纳 public payload，`core/storage.py` 又维护同一正则，`ProjectManager.load_meta` 和私有路径 helper 随后再次验证。一次 HTTP 请求中的同一个 ID 可被检查 2–3 次。

但 public protocol 与 `ProjectManager` 是两个可独立调用的 ingress Interface。只要 `ProjectManager` 仍接受裸字符串，它就必须保留自己的 contract admission；不能仅凭正则相同就删除这一层。可以直接删除的是 admission 之后私有 path helper 的复验。更深的方案是引入 admitted identifier value，让 protocol 和程序化入口各自完成接纳后都传递该类型。路径拼接和 durable-write 防止意外数据损失的检查仍保留。25–60 行是待 Interface 收敛的机会范围，不是已批准的直接删除量。

### 5. Ledger owner 返回的 event 被 server 再校验

`_RunEvidenceLedger` 在 stage/commit seam 拥有 public event schema；[`core/server.py`](../../core/server.py) 第 939–941、965–967 行又校验 Ledger 返回的 event。删除后一层重复检查；server 自己合成的 replay marker 仍在 server boundary 校验。

不要因此缩减 Ledger 自身的 `_validate_schema`、`_validate_causality`、transaction、sequence、durable bytes、size、redaction 或 publish 验证。它们保护的是不同边界，且由架构明确要求。

### 6. Adapter 拒绝官方 pinned writer 不会产生的假想响应

[`modules/folding/simplefold_adapter.py`](../../modules/folding/simplefold_adapter.py) 第 80–90 行在翻译 pinned writer 的 padding sentinel 时，额外拒绝“unexpected tail”。官方响应契约是权威边界，这个分支约 7 行属于假想 malformed-response hardening，可删除；确定性的 sentinel translation 保留。已文档化的 `ESMProteinError` 分支不能一并删除。

## 浅模块、dead API 与机械表示

### 静态无生产消费者不等于全部可直接删除

静态调用图确认 `core/scoring_v2._validate_metric_value` 没有消费者；它是私有死路径，可直接进入 P0。`core/process_control.enter_module_worker_process_group` 及只为它服务的 `verification_uses_shared_process_group` 也没有仓库调用点。`modules/provider_contract.esm_provider_identity`、`proteinmpnn_provider_identity`、`validate_biohub_token_file` 没有实际调用，其中 `proteinmpnn_provider_identity` 只剩一个 unused import。这些 module-level surface 仍应先确认没有生成脚本/安装包入口，再原子删除定义、import 与测试。

下列则是“无仓库消费者的公开 method”，不是私有 dead code：`CandidateCollection.manifest_facts`、`ScoreCollection.manifest_facts`、`ResidueTrack.specified_count`、`WorkflowAuthoringService.require_compiled_revision`、`ProjectManager.list_projects`、`LocalSimpleFoldConfidenceAdapter.normalize_native_confidence`。项目没有历史兼容义务，所以可以删除，但实施记录必须明确这是 current Python Interface 收窄，而不是声称行为完全不变。

`biohub_esmc_client_factory` 看似没有普通调用点，但被 installed-backend 测试生成的脚本引用，不能误删。credential file reader 也属于明确允许保留的 credential-hygiene boundary。

### `RunContext` 是可消失的浅模块

[`core/run_context.py`](../../core/run_context.py) 只有 128 行。它不是 dead：当前由 `ProjectManager.run_context` 构造、被 `RunResources.temporary_directory/cleanup` 使用，并从 `core.__init__` 导出；只是 `input_path`、`output_path`、`temporary_file` 没有生产消费者。

建议先把 Project/Run/Node-contained temporary directory 和 cleanup 语义迁移给 `RunResources`/`ProjectManager` 的唯一 owner，再删除 `RunContext` export 和 abstraction，而不是给它寻找新职责。净删除估计 80–110 行。这是需要职责迁移的 shallow-module 重构，不属于无行为变化的 P0 dead-code 删除。

### Direct Binding authoring 机械样板过多

12 个 `package.py` 合计约 5,629 行；package 测试 fixtures 约 4,888 行。静态盘点至少发现 11 个常量 `_available`、10 个常量 `_ready`，以及每个 direct binding 重复声明的 Availability/Readiness/factory wiring。架构已经规定 direct route 不需要 Provider Readiness。

一个有潜力的 authoring surface 是：

```text
direct_binding(scientific_declaration, operation)
adapter_binding(scientific_declaration, availability, readiness, adapter)
```

但这目前只能列为设计假设。架构正文说 Availability/Readiness 只服务 Adapter route，`CONTEXT.md`、ADR-0025、ADR-0029 与 ADR-0034 仍把 Availability/Readiness declaration 作为 Binding/digest/Execution Plan 的一部分。必须先判断后者是否被新架构取代，并用一份 ADR 原子解决规范冲突；在此之前不能直接决定 direct route 使用固定 availability 或 `readiness=None`。

若 ADR 最终确认该方向，科学事实仍应显式，core authoring seam 应删除公开的机械 declaration 对象和重复 fixture，而不是提供第二种可选写法。预计可删 800–1,500 行生产代码、1,500–3,000 行测试；这是设计 envelope，不是当前事实。

这会改变 package descriptor/version/digest，必须一次性更新所有 package、Catalog consumers、public bundle、examples、installed parity、文档和 ADR；不保留 alias 或 dual path。

### Exact Contract reference 存在多种重复表示

`core.workflow_v2.ContractLockEntry`、`datatypes.protein.ExactContractReference` 以及多个 raw dict mapper 有相似字段形状，但前者是 Workflow Contract Lock 成员，后者是科学值携带的 exact reference；它们的 domain role、排序和校验可能不同。这里能确认的是“重复结构候选”，尚未证明为同一个 ubiquitous domain concept。

应先做一次 domain-modeling 决策：若两者确实是同一 resolved exact reference，合并为一个 provider-independent datatype 并由它拥有 `from/to/key`；若角色不同，则保留两个类型，只共享经过证明完全相同的 validator/codec。`module_package.ContractIdentity` 是 unresolved declaration identity，不能一起合并。500–1,000 行仅是设计机会估算。

### JSON freezing 只能合并真正相同的契约

`datatypes` 的 I-JSON、module declaration freeze、workflow freeze、runtime plain/frozen JSON、operation container freeze 有重复 helper。可以统一真正的 I-JSON canonicalization，预计删除 100–300 行；科学值冻结、runtime admitted representation 和 declaration digest 若语义不同，必须继续分开。

## 测试熵

测试套件的体量不是独立缺陷；缺陷是一个 invariant 在多个测试层级被重复证明，或者测试锁住被规范明确拒绝的私有形状。

最大测试文件包括：

| 文件 | 行数 |
|---|---:|
| `tests/test_run_execution_v2.py` | 4,529 |
| `tests/test_proteinmpnn_v2.py` | 4,423 |
| `tests/test_scoring_v2.py` | 2,461 |
| `tests/test_structure_comparison_v2.py` | 2,456 |
| `tests/test_structure_annotation_v2.py` | 2,351 |
| `tests/test_esm3_v2.py` | 2,330 |
| `tests/test_workflow_compiler_v2.py` | 2,117 |
| `tests/test_public_protocol_v2.py` | 2,082 |

已确认的语义重复：

- `tests/test_solubility_v2.py` 第 994–1141 行和 `tests/test_protein_sol_v2.py` 第 953–1096 行，都通过 Contract Test Kit 跑三个 solubility package binding；后者约 144 行可删除或并入唯一套件。
- `tests/test_selection_v2.py` 第 692–758 行和 `tests/test_multi_objective_selection_v2.py` 第 948 行起，都通过 Contract Test Kit 跑三个 selection nodes；应保留一个 package interface suite。
- `tests/test_run_evidence_ledger_v2.py` 检查 `append/commit` 不存在、`tests/test_simplefold_confidence_v2.py` 检查私有 helper 不存在、`tests/test_candidate_reference.py` 检查某个 core export 不存在、`tests/test_workflow_commit_v2.py` 检查一组 method 不存在。这些属于实现形状/absence 测试，应删除。
- `tests/test_v1_runtime_cutover.py` 同时混入 current safety contract 和旧符号/旧路径 absence。保留当前 generation fail-closed、seed/数据损失等行为证明；删除已完成 cutover 的专门形状测试并把剩余行为移入当前 owner suite。

AST exact-duplicate 只能发现约 20 组 helper、约 426 行的下界；真正的大头是上述跨文件 semantic duplication。因此不建议以文本去重工具作为主要重构方法。

测试的目标分层应固定为：

| Owner | 唯一应证明的内容 | 下游删除内容 |
|---|---|---|
| Public protocol | wire schema、version、public ID/event | storage/server 的同型 malformed payload cases |
| Port admission | canonical roundtrip、bytes、digest、科学 layout/mask/axis | operation/ledger 私有 malformed value cases |
| Catalog/package | Node/Method/Binding/unit/shape/randomness/provenance declaration closure | runtime descriptor grammar cases |
| Scientific operation | units、shape、mapping、mask、seed、Method semantics | package wiring和 public route 的重复算法断言 |
| Adapter | 官方响应翻译、provider identity、invocation facts | 猜测 malformed provider response 的分支 |
| Ledger | 17 facts、因果、transaction、durability、projection | server 对 Ledger-owned event 的重复 schema cases |
| Contract Test Kit | package 经公开 interface 的一次端到端契约 | 每个历史文件重复一遍同一 binding matrix |
| Acceptance | 15-tier scenario 的真实科学结论 | mocks、第二次 certification、historical manifest |

## 建议执行波次

### 可选前置：仓库卫生（不计入架构删减量）

- `.scratch/`：114 个 tracked files、约 7,101 行；除一处文档引用外主要是完成后的历史草稿。
- `output/`：15 个 tracked PDB、约 7,723 行；未发现代码或文档消费者，且未被 ignore。

两者合计 129 个文件、14,824 行，但它们没有计入产品/测试净删估算。删除前必须确认 tracked PDB 不是未登记的科学证据或唯一不可恢复结果，并先迁移唯一文档引用；确认后再删除或移出活动仓库，并建立明确的 scratch/output 不入库规则。不要把 package 内的 `examples/`、PDB package data、public protocol bundle 或 `repositories/` gitlinks 当成生成垃圾。

### Wave 1A：已证实私有重复与死路径

1. 删除 Workflow double validation，以及未导出、无消费者的 workflow validation wrappers。
2. 删除 Catalog-owned descriptor grammar 的 runtime revalidation；保留 fact-dependent semantic checks。
3. 删除 server 对 Ledger-owned events 的复验，以及 admission 后私有 path helper 的 ID 复验。
4. 删除 SimpleFold hypothetical tail rejection，保留确定性 translation。
5. 删除已确认的私有 dead function、unused import 和对应 private-shape tests。

这部分不改变科学 contract、wire bytes 或 descriptor digest。高置信审计范围与下述公开 surface 合计约 360–575 行；实施前应逐项记录精确 diff，而不是把估算当配额。

### Wave 1B：公开 surface 收窄与 shallow-module 迁移

1. 确认并删除无生产消费者的公开 methods/module functions，明确记录 current Python Interface 变化。
2. 迁移 `RunContext` 的 temporary-directory/cleanup 职责后删除其 export 与 abstraction。
3. 决定是否删除已导出的 `validate_produced_score_collection`，同步删除 export 和只为它存在的测试。
4. 若要进一步收敛 Project/Run ID，先保留两个独立 ingress 或引入 admitted identifier value。

这部分符合“无历史兼容义务”，但不是 dead-code-only 变更，也不能声称 public behavior 不变。应与 Wave 1A 分开提交。

### Wave 2：Port admission 单一所有权

1. 先建立 canonical bytes/digest、runtime value、nested axis/layout/mask 的 golden proof。
2. 引入两个 admission entry；同一变更中删除 encode→decode 环和 custom/generic 双 validator。
3. 内存生产路径通过 `admit_runtime` 一次；object store、cache、Ledger durable bytes 的重建路径通过 `admit_bytes` 一次。operation 与 projection 只消费 `AdmittedValue`。
4. 删除 admitted value 在内存传播中的 malformed-private-call tests；保留损坏 persisted bytes 的 fail-closed 与 durable-write tests。
5. 通过计数测试证明每个 contract-owning validator 每次 admission 只运行一次；不要把该计数测试扩展成普遍的函数调用顺序测试。

这是收益最大、同时最需要科学语义保护的一波。

### Wave 3：Package authoring 与 exact reference 深化

1. 先用 ADR 解决 Direct Binding 在 architecture、`CONTEXT.md`、ADR-0025/0029/0034 之间的 Availability/Readiness 规范冲突；只有决议通过后才用 `direct_binding` / `adapter_binding` 取代相应机械 wiring。
2. 先确认 `ContractLockEntry` 与 `ExactContractReference` 是否属于同一 domain concept；只有结论为“相同”时才合并表示，否则只共享 codec/validator。
3. 统一真正相同的 I-JSON canonicalization。
4. 同步更新全部 producer、consumer、tests、examples、bundle、docs 和 ADR，直接删除旧 declaration surface。

若上述两个设计前提都成立，生产代码的 envelope 约为 1,400–2,800 行、测试约 2,000–4,000 行；不是当前承诺。descriptor/version/digest 变化应被当作有意的 current contract 更新，而非兼容问题。

### Wave 4：测试按 owner 收敛

1. 给每个 invariant 建立“唯一 owner test”清单。
2. 合并重复 Contract Test Kit matrices。
3. 删除私有 helper、absence、AST、调用顺序和结束后的 cutover tests。
4. 巨型测试文件只有在形成更清楚的 owner suite 时才拆；不为满足行数上限拆文件。

语义重复审计给出的测试设计 envelope 为 6,000–12,000 行，同时必须保持所有当前科学与 acceptance proof。这个总量已经包含 Port、Binding、exact-reference 重构带来的相关测试删除，不能再和各工作包的测试估算相加。

### Wave 5：最后处理 runtime giant modules

`_RunEvidenceLedger` 和 `_NodeExecutionAttemptModule` 必须晚于前四波。先让外部只依赖稳定的 transition/disposition interface，再删除 private assembly、宽 finalization intents、重复 representations 和测试 seam 泄漏。不要拆散 Ledger 的 17 facts、因果和 durable transaction ownership。

这一波潜在可删 1,000–2,000 行生产代码和 2,000–4,000 行测试，但当前证据不足以把它列为 P0；应单独写 ADR，并以调用图和 evidence lifecycle proof 驱动。

## 估算与优先级

以下先按证据等级分层。设计 envelope 相互重叠，不是承诺值：

| 工作包 | 生产净删 | 测试净删 | 置信度 | 风险 |
|---|---:|---:|---|---|
| 已证实重复校验、私有死路径、无生产消费者 surface | 360–575 | 由直接 diff 计数 | 高 | 低至中；部分 surface 已导出 |
| `RunContext` 与公开 surface 收窄 | 待职责迁移后实测 | 待实测 | 高（现状） | 中（Interface 变化） |
| Port admission 单一 owner | 2,000–4,000 | 1,000–3,000 | 中；设计 envelope | 高（wire/科学值） |
| Binding authoring | 800–1,500 | 1,500–3,000 | 中；先解规范冲突 | 中（descriptor） |
| Exact reference + I-JSON | 600–1,300 | 500–1,500 | 低至中；先定 domain role | 中 |
| 测试 owner 收敛总量 | — | 6,000–12,000，包含上述相关测试 | 中；设计 envelope | 中 |
| Ledger/attempt seam 收敛 | 1,000–2,000 | 2,000–4,000 | 低至中；后续波次 | 高（evidence） |
| **条件式第一阶段 envelope** | **4,000–8,000** | **6,000–12,000** | 仅在 Wave 2/3 ADR 成立后 | — |

只有在 Wave 2/3 的 domain 与 ADR 前提成立、且实际 diff 落入上述 envelope 时，52,800 行产品基线才可能下降到约 44,800–48,800 行。这个换算不是目标或验收门槛；第一阶段也可以在删除更少代码时正确结束。

## 每个删除 PR 的验收条件

1. PR 描述明确写出：旧 owner、唯一新 owner、删除了哪些 caller/check/test。
2. 产品代码与测试必须净减少；新增 facade、shim、alias、legacy parser 或 dual path 视为失败。
3. 同一 invariant 的 invalid cases 只存在于 owner interface suite；下游使用 admitted fixtures。
4. Node、Method、Metric、unit、shape、residue mapping、mask、randomness、lineage、provenance、evidence 的语义逐项列出并证明未丢失。
5. Port/descriptor 变更时验证 canonical bytes、digest、golden roundtrip、package bundle 和 installed parity；不得静默漂移。
6. Ledger 变更时逐项证明 17 facts、causality、transaction、sequence、durability、redaction 和 public projection。
7. Provider Adapter 只按官方/pinned spec 翻译；真实 provider acceptance 不由 mock 替代。
8. 运行聚焦测试，然后只运行后端 gate：

   ```bash
   .venv/bin/python scripts/verify_backend.py routine
   .venv/bin/python scripts/verify_backend.py deterministic-acceptance
   ```

9. 高风险波次在 clean revision 上运行一次串行 15-tier Acceptance Campaign。
10. 本任务明确排除废弃前端；不要让 `frontend` lint/build 成为本重构的实施或验收依赖。规范文件中残留的 frontend gate 应在实施前同步标记为废弃，以消除矛盾指令；这项文档一致性工作不计入后端净删量。

## 决策建议

可以立刻批准 Wave 1A 的逐项实现盘点与私有重复删除。Wave 1B 应作为独立的 current Python Interface 收窄/职责迁移提交。仓库卫生项先确认 tracked PDB 的证据与可恢复性，不与架构删减混算。

随后为 Wave 2 单独写一份 Port admission ADR，把“runtime value admission”和“durable canonical bytes admission”设为唯一两个入口。Wave 3 可以并行调研，但必须先分别解决 Binding 规范冲突和 exact-reference domain role；实现时与 Port admission 分开提交，以免 descriptor 变化和 wire admission 变化混在一起。

不建议先做 `run_execution_v2.py` 的文件拆分。它最显眼，却不是当前最安全的首刀。先删除外围重复 owner 和 private seam tests，巨型 runtime 文件会自然缩小；届时剩余的 Ledger 深度是资产，而不是熵。

## 可复现盘点命令

这些命令只统计后端，不包含 `frontend/` 与 `repositories/`：

```bash
find core datatypes modules protein_workbench_public -name '*.py' -print0 \
  | xargs -0 wc -l | sort -n

find tests -name '*.py' -print0 \
  | xargs -0 wc -l | sort -n

rg -n "validate|admit|encode|decode|from_wire|to_wire" \
  core datatypes modules protein_workbench_public tests

rg -n "_available|_ready|Availability|Readiness" modules core tests
```

AST 和运行时计数用于定位候选，不应变成新的 helper-count、function-length 或私有调用顺序 gate。
