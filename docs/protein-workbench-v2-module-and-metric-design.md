# Protein Workbench v2 后端模块、执行与指标合同

日期：2026-07-27
最后同步：2026-07-28

状态：整体架构已接受，可作为 v2 规格与实现票据的输入；运行时代码尚未按本合同重构。

前提：把 `.scratch/protein-workbench-backend-repair/spec.md` 完成后的后端视为 v1
基线。本文记录 v2 的唯一目标合同，不要求兼容 v1。

## 1. 目标、维护者与范围

Protein Workbench 的目标保持不变：

1. 通过可连接的节点组合蛋白设计、折叠、评价、转换与选择 Workflow；
2. 让具备开发经验的仓库维护者能够方便地新增科学操作。

“自定义节点”在 v2 中明确指仓库内开发者扩展：

- 在 `modules/` 中新增或扩展一个内聚的 Module Package；
- 提供 Node Definition、Method、Execution Binding、implementation 或 Adapter，
  纳入 `MODULE_PACKAGE` registration，并通过统一 Contract Test Kit；
- 不修改 `core/`；
- 由启动发现纳入同一个不可变 Catalog。

v2 不实现第三方 `pip install` 插件、插件管理、运行时热加载或依赖自动安装。未来可以
增加 Python entry point loader，但它只能向同一个 Registry 提交相同的
`ModulePackage` 注册对象，不能形成第二套扩展合同。

当前前端不构成后端设计约束。后端合同稳定后，现有前端将被废弃并另行重写。

## 2. 核心领域与扩展模型

### 2.1 Node Type、Method、Binding 与 Adapter

- Node Type 表达一个科学操作，其输入、输出和跨 Binding 参数由唯一 Node Definition
  声明。
- Method 表达决定科学解释和可复现性的准确算法、模型、checkpoint、featurization
  或版本组合。
- Execution Binding 把一个 Node Type 与一个 Method，以及 direct implementation
  或所需 Adapter 关联起来；registration 只负责提供相应 lazy factory。
- Adapter 把 provider、SDK、模型运行时、服务端点或部署模式翻译到 Workbench
  合同，不改变 Node Type 的科学含义。

因此，本地和远程 ESMFold2 可以共享一个折叠 Node Type，但必须使用不同的 Bindings；
若模型或算法身份不同，则 Binding 指向不同 Method。模型、checkpoint、Adapter、
结果相关实现和部署身份必须进入 provenance 与 Result Identity。

这一 seam 让新增部署路径具有 locality：Module Package 拥有自己的 Definition、
Binding、Adapter、Availability 与 Readiness 声明；`core/` 只消费统一 interface，
不认识 ESM-3、SoluProt、Protein-Sol 或某个 provider 的专有规则。

### 2.2 一个内聚 Module Package 可以提供多个 Node Types

分包依据是共享科学能力、依赖、Adapter、领域语义和测试资产，不是机械的“一目录一
节点”。每个 Node Type 仍恰好拥有一份独立 Node Definition；多个 Node Types 可以共享
同一个内聚 implementation、Adapter、资源和测试夹具。

推荐的按需目录合同是：

```text
modules/<package_name>/
├── __init__.py
├── package.py
├── definitions/
│   └── <node_type>.yaml
├── metrics/                    # 仅在该包声明 Metric 时存在
│   └── <metric>.yaml
├── implementation.py           # 一个内聚实现时
├── implementations/            # 确有多个内聚实现时，替代上项
├── adapters.py                 # 一个内聚 Adapter 集时
├── adapters/                   # 确有多个内聚 Adapter 时，替代上项
├── availability.py             # 需要时
├── readiness.py                # 需要时
├── resources/                  # 仅在存在运行资源时
└── tests/                      # 源码共置，但排除在 production wheel 外
```

不创建空目录。单文件与子目录二选一，不额外建立与 Node Definition 一一对应的机械
脚手架。测试与实现共置以保持 locality，但测试 cases 和 fixtures 不属于生产注册对象。

### 2.3 Definition 与 typed registration 的职责

Node Definition YAML 只包含公共语义字段：

```text
schema_version
node_type_id
version
title / summary / category
inputs[] / outputs[]:
  name, port_type_id, port_type_version, required, multiplicity, meaning
parameter_groups[]
node_parameters[]:
  name, parameter_scope=scientific, scientific_meaning,
  value_contract, required/default
```

`parameter_scope=scientific` 与非空 `scientific_meaning` 是每个 Node/Binding
Workflow 参数的显式准入分类；Environment Configuration、credential、endpoint、
runtime/model source 不存在可进入 Workflow 的分类值。`value_contract` 只允许
Catalog Builder 明确支持并完整验证的闭合关键字子集，object 参数必须
`additionalProperties: false`。因此不支持或不完整的参数合同在 Catalog 原子发布前
失败，而不是推迟到编译或执行阶段。

Metric Definition YAML 只包含科学测量合同：

```text
schema_version
metric_id
version
title / description
value_shape
unit
direction
canonical_range
granularity
aggregation_semantics
observation_context_schema
validation_contract
```

Unknown fields、未知 schema version、重复 ID/version 和不完整合同均使启动失败。YAML
不声明 factory、凭据、设备、路径、provider probe 或测试 cases。

Method、Execution Binding、Port Type、Utility Transform、factory、Availability 和
Readiness 声明使用 immutable typed Python registration。每个 Binding 至少固定：

```text
binding_id + version
node_type_id + node_type_version
method_id + method_version
lazy implementation / Adapter factory
binding_parameter_contract
Availability declaration
Readiness declaration
determinism and cacheability declaration
result-affecting implementation identity
```

Method 固定科学身份；Binding 参数只允许该执行路径中仍然可调、且不会改变 Method
身份的参数。模型名称不是同一 Binding 下的自由文本开关。

### 2.4 单一生产入口与显式资源

每个一级 Module Package 只暴露：

```text
modules/<package_name>/package.py:MODULE_PACKAGE
```

`MODULE_PACKAGE` 是 immutable typed `ModulePackage` 注册对象，显式逐项列出：

- Node Definition resources；
- Metric Definition resources；
- Methods；
- Execution Bindings；
- Port Type Definitions；
- Utility Transforms；
- lazy implementation/Adapter factories、Availability 与 Readiness
  declarations/probes。

禁止 glob、递归资源扫描、受命名约定驱动的隐式 helper 枚举、分散的 `register()` 和
import side effect。`package.py` 不得急切导入可选 provider 依赖。Contract Test Kit
作为测试期的独立消费者读取同一个生产注册对象。

### 2.5 原子 Registry 与 FrozenCatalog

启动发现按照固定次序建立一个临时 Catalog：

1. 扫描 `modules/` 的一级包；
2. 读取每个 `package.py:MODULE_PACKAGE`；
3. 解析显式 Node/Metric YAML resources；
4. 合并 Methods、Bindings、Port Types 和 Utility Transforms；
5. 检查引用、所有权、版本、contract digest 和冲突；
6. 解析每个 Binding 的 startup Availability；
7. 全部成功后一次性发布 `FrozenCatalog`。

任何包导入、Definition、registration、引用或合同冲突都使启动失败，不发布部分
Catalog。Catalog 发布后不可变。所有 compiler、Run admission、executor 和查询
interface 消费同一个 `FrozenCatalog`，不维护平行的 Definition Registry、factory
字典或 provider 映射。

每个 Node Type、Method、Binding、Metric、Port Type 和 Utility Transform 都有 exact
ID、version 与 contract digest。同一 ID/version 对应不同 digest 时 fail closed；不支持
version range、`latest` 或环境相关的自动升级。Binding contract digest 包含 immutable
Availability/Readiness declarations，但不包含它们在某次 startup 或 Run 中的观察结果。

相关决定见
[ADR-0018](./adr/0018-module-packages-and-startup-discovery.md)、
[ADR-0023](./adr/0023-independent-node-definitions-flat-by-default.md) 和
[ADR-0025](./adr/0025-execution-bindings-own-availability.md)。

### 2.6 Port Type 是显式、版本化的名义合同

每个 Port 精确引用 `port_type_id + version`。每个 Port Type Definition 提供：

```text
type_id + version + contract_digest
runtime validator
canonical codec
content-digest procedure
```

Core 可以提供内建类型，Module Package 也可以通过统一 registration 提供新类型。未知
类型不会因为在 YAML 中出现一个新字符串而被自动创建。Port compatibility 只接受完全
相同的 `type_id + version`；结构相似、隐式 coercion、subtyping 和版本范围都不构成
连接兼容。科学转换必须由显式 Node Type 表达。

相关决定见
[ADR-0028](./adr/0028-port-types-are-versioned-nominal-contracts.md)。

### 2.7 参数与 Environment Configuration

Node Definition 只声明所有 Bindings 之间具有相同科学含义的参数。Method 或 Adapter
特有、但不改变 Method 身份的参数由 Execution Binding 声明。Workflow 分别保存
`node_parameters` 与 `binding_parameters`，不使用一个混合参数字典。

凭据、设备选择、部署端点和运行时文件系统位置属于 Environment Configuration，不是
Workflow 参数。实际值由 trusted backend configuration 按 Binding scope 注入；secret
使用 opaque handle，不进入 Workflow、Result Identity 或公开证据。环境选择若影响
科学结果，其安全、稳定身份仍必须进入 Method、Binding 或 Result Identity。

相关决定见
[ADR-0027](./adr/0027-node-and-binding-parameters-are-separated.md)。

## 3. Workflow、编译与运行准入

### 3.1 v2 Node Instance 形状

每个 Workflow 文档在顶层保存 `schema_version`；每个持久化 Node Instance 至少保存：

```text
node_id
node_type_id
node_type_version
binding_id
binding_version
node_parameters
binding_parameters
```

Method 不重复持久化；它由 exact Binding 唯一派生。连接引用 `node_id` 与具名 Port。
Workflow、示例、seed 和 fixtures 都必须固定 exact Node Type/Binding 版本，不允许根据
当前机器自动选择“任意可用 Binding”，也不允许静默回退 Method、Adapter 或部署方式。

### 3.2 Compiler 与 ExecutionPlan

Compiler 只执行静态解析：

- schema 与图结构验证；
- exact Node Type/Binding lookup 与 ownership；
- Port Type compatibility；
- Node/Binding 参数规范化；
- startup Availability 检查；
- Metric、Method、Observation Context、Selection Objective 与其 exact Utility
  Transform 引用解析；
- contract digest 固定。

成功后产生 immutable `ExecutionPlan`，包含执行所需的 resolved identities 与合同，但
不声称 provider 此刻可调用。每个 Run 使用同一个 `FrozenCatalog` 校验
`ExecutionPlan`，并在任何 Cache lookup 或 Node execution 之前完成 Readiness。

相关决定见
[ADR-0026](./adr/0026-workflows-pin-execution-bindings.md)。

### 3.3 Availability、Readiness 与 Invocation 不可互相替代

| 事实 | 生命周期 | 含义 |
| --- | --- | --- |
| Availability | startup | Binding 的基础结构性前提是否存在 |
| Readiness Attestation | 每个 Run 的准入期 | exact selected Binding 此刻是否可以开始执行 |
| Engine Invocation | 实际执行期 | 是否真正跨入声明的科学 engine seam |

每个 Run 对所有 distinct selected Bindings 产生自己的 Readiness Attestation，而且必须
先于第一次 Cache lookup。Cache hit 不能绕过 Readiness；v2 不承诺 provider 不可用时的
隐式离线 replay。

凭据、端点、二进制、路径和设备等 volatile prerequisites 每个 Run 重新观察。昂贵且
immutable 的 proof 只有在 Binding 显式声明 identity、scope、maximum age 与
invalidation contract 时才可复用；Run 仍记录自己的 attestation。禁止零参数的
process-global readiness cache。

相关决定见
[ADR-0029](./adr/0029-readiness-precedes-cache-lookup.md)。

## 4. 目标 Module Packages

v2 把当前 45 个 Node Types、43 个一级节点目录归并为 11 个生产 Module Packages：

| Module Package | 纳入的科学能力 |
| --- | --- |
| `prompt_authoring` | layout、residue edits、Prompt assemble、function annotation、track map/override、random mask/insert，以及通用 Prompt sequence update |
| `esm3` | sequence/structure/paired generation，共享本地与远程 ESM-3 Adapters |
| `folding` | ESMFold2 与 SimpleFold folding Bindings；独立的 existing-structure confidence Node |
| `proteinmpnn` | constraints、design、score 和 random fixed positions |
| `structure_annotation` | secondary structure、SASA 与 secondary-structure agreement |
| `structure_comparison` | single/pairwise alignment、TM-score、batch TM-score 与 RMSD |
| `structure_transform` | chain selection、backbone extraction 与 sequence extraction |
| `protein_io` | sequence/structure import 与 export |
| `selection` | filter、sort、top-k、weighted-rank、Pareto 与 diversity selection |
| `collection_ops` | Candidate concatenation 与 Score merge；不原样迁移无 subject 的跨 Metric aggregation |
| `solubility` | SoluProt 与 Protein-Sol 评分 Methods 和 Metrics |

`stub.echo` 从生产发现移除，转为 Contract Test Kit fixture。该归并不是把旧目录换名：
重复的 YAML loading、registration、provider probing、Adapter glue、provenance 和测试
脚手架必须在内聚包内收敛。

相关决定见
[ADR-0024](./adr/0024-consolidate-nodes-into-capability-packages.md)。

## 5. Metric、Observation 与 Selection Objective

### 5.1 正式评分身份

Score Observation 的正式身份是：

```text
Candidate + Metric + Method + Observation Context -> Value
```

- Candidate 是稳定、run-independent、带 lineage 的被评价对象；
- Metric Definition 声明科学量、shape、单位、方向、canonical range、granularity 与
  aggregation semantics；
- Method 声明得到该量的准确算法或模型组合；
- Observation Context 声明解释观察所需的 typed scientific context；
- Value 不属于观察 identity。

Intrinsic observation 使用固定的 `intrinsic` context。Pairwise observation 使用
typed role labels，并记录 reference Candidate identity、content digest 和 normalization。
Metric Definition 声明允许的 context schema。Workflow 和 selector 精确选择
Metric、Method 与 Context，不能让运行时任意挑选。

同一完整 observation identity 的相同值可以去重；相同 identity 的冲突值或不明确重复
fail closed，除非 Workflow 显式选择了具有固定 Method 的 aggregation Node。

相关决定见
[ADR-0019](./adr/0019-scientific-metric-and-method-identity.md)。

### 5.2 Utility 由 Workflow 的 Selection Objective 拥有

Metric Definition 只描述科学测量，不拥有任务偏好，也不提供隐式 Utility。每个
Selection Objective 精确固定：

```text
metric + method + context selector
Utility Transform ID + version + parameters
weight
missing-value policy
```

Utility Transform 是 Catalog 可解析、受控且版本化的 mapping，把 canonical value 映射
到无量纲 `[0, 1]`；不允许任意 Python。Weight 必须 finite、非负，且至少一个大于零；
执行时按总和归一化，并在 provenance 中同时记录 raw 与 effective weights。默认
missing policy 是 `error`，任何忽略或替代行为都必须显式声明。

禁止负权重、隐式 dataset-relative min-max、range guessing，以及直接相加不同 Metric
的 raw values。

相关决定见
[ADR-0021](./adr/0021-weighted-rank-uses-explicit-utilities.md)。

### 5.3 pLDDT 的 canonical 公共合同

Workbench 对外只暴露：

- `structure.plddt.per_residue`：逐有效蛋白残基序列，`[0, 100]`；
- `structure.plddt.mean_residue`：上述序列的残基等权算术平均，`[0, 100]`。

两者无量纲且越高越好。平均值排除 padding、chain break、非蛋白 token 与 NaN，不用
逐原子加权聚合量代替。

尺度转换由 Adapter 的静态合同决定：ESM-3 SDK 和 ESMFold2 的 `[0, 1]` 值乘以 100；
SimpleFold 高层 wrapper 的 `[0, 100]` 保持不变；直接使用 ConfidenceModule 的
`[0, 1]` 输出时乘以 100。禁止用 `max(values) <= 1` 猜尺度。结构序列化仍采用 provider
要求的 native scale。pTM 保持 `[0, 1]`，PAE 使用埃；过时的经典 Meta ESMFold 不在
项目范围内。

事实核查见
[pLDDT 数值尺度与公共契约核查](./research/2026-07-27-plddt-value-contract.md)，决定见
[ADR-0020](./adr/0020-canonical-plddt-contract.md)。

### 5.4 SimpleFold confidence Method 固定真实 pipeline

SimpleFold folding 与 existing-structure confidence evaluation 是 `folding` Module
Package 中两个不同 Node Types。Evaluation 不重新折叠，也不暴露可变 `model_name`。
当前 Method 固定：

- `simplefold_1.6B.ckpt` latent checkpoint；
- `plddt_module_1.6B.ckpt` output head；
- `esm2_t36_3B_UR50D.pt` encoder checkpoint；
- structure featurization 与 native-to-canonical pLDDT scale contract；
- upstream scientific source identity。

Binding 与 Result Identity 另外固定 Workbench Adapter 和 implementation identity。
三份 checkpoint 都按
[provider install contract](./provider-install-contract.md)
保存实际解析的 immutable content digest。
未参与该计算的 folding checkpoint 不加载、不作为 Readiness prerequisite，也不进入
Method 或 invocation provenance。任何结果相关 checkpoint、head、encoder、
featurization、source、Adapter 或 scale 变化都建立新 Method/Binding。

相关决定见
[ADR-0032](./adr/0032-simplefold-confidence-method-is-fixed.md)。

## 6. 三组扩展验收案例

### 6.1 本地 ESMFold2

在 `folding` 包中增加本地 Binding、Adapter、Availability/Readiness 声明和合同测试；
共享折叠 Node Definition。若它与远程路径使用同一科学 Method，Method 可共享；部署与
implementation identity 仍由不同 Binding 固定。无需修改 `core/`。

### 6.2 本地 ESM-3

在 `esm3` 包中增加本地 Bindings，并复用多个 generation Node Types、模型加载与测试
资产。Node Definition 不出现凭据、设备或 checkpoint path；模型身份由 Binding/Method
固定，路径与设备由 Environment Configuration 注入。它是“仓库内扩展、零核心修改、
启动发现、统一测试”的首要验收案例。

### 6.3 SoluProt 与 Protein-Sol

调研范围只采用 `/Users/sorachan/Documents/ESM-workflow-NEXT` 中作为依赖仓库存在的
SoluProt 与 Protein-Sol，不采用该目录其他实现。

- SoluProt 的 full 与 no-TM 预测器是不同 Methods/Bindings，不是同一 Method 的自由
  `model_name` 参数。
- Protein-Sol 的 percent-sol 与 scaled-sol 若对外公开，应是两个候选级 Metrics。
- pI 是独立物理 Metric。
- population-sol 是固定 baseline/calibration context，不是每个 Candidate 的同类
  Score Observation；不得把它与候选预测值压成一个 `score_id`。
- 一个 Method 可以产生多个 Metrics；每个 observation 仍使用完整
  Candidate/Metric/Method/Context identity。

这两个仓库共同验收 `solubility` Module Package、Metric Definitions、多个 Methods、
统一 Port Types、Readiness、provenance 与 Contract Test Kit。

## 7. 执行证据

执行事实分为三个层次：

```text
Node Execution Attempt
└── Operation Attempt             # 仅在 Cache miss/bypass 后 implementation 实际运行
    └── Engine Invocation         # 仅在跨入声明的科学 engine seam 时
```

Cache hit 只终结 Node Execution Attempt，不产生 Operation Attempt 或 Engine
Invocation。一个 Operation Attempt 可以包含零个、一个或多个带显式 parent-child role
的 Invocations。

每个已开始的 Operation Attempt 与 Engine Invocation 必须恰有一个 terminal fact：
`succeeded`、`failed`、`cancelled`、`interrupted` 或 `outcome_unknown`。Engine 成功但
decode、normalization、output validation 或 artifact post-processing 失败时，
Invocation 保持成功，外层 Operation/Node 失败。worker 丢失后不得臆造远端结果。

Run Evidence Ledger 是 typed run facts 的唯一写入 interface。事实经过 schema/causal
validation、安全 redaction、durable persistence 与 monotonic sequence 分配后，才投影
为 manifest、JSONL lifecycle stream 或 WebSocket events。证据提交失败时 Node 不能
发布成功，也不能写 Cache。Acceptance 检查 ledger closure 和 causal relationships，
不固定历史调用条数。

相关决定见
[ADR-0030](./adr/0030-execution-evidence-separates-attempts-and-invocations.md)。

## 8. Result Identity 与 Project-scoped Cache

v2 使用全仓库统一 schema namespace：

```text
protein-workbench-cache/v3
```

Result Identity 是 run-independent 的 canonical identity，包含所有会影响结果的 resolved
contracts：

- exact Node Type、output、Port Type、Binding、Method、Adapter；
- implementation、model、checkpoint、source、binary 等结果相关 identities；
- normalized Node/Binding parameters；
- canonical typed input identities 与 content digests；
- effective randomness；
- 相关 Metric、Observation Context 与 Utility contracts。

Project ID、Run ID、Node Instance ID、凭据、private paths、timestamps、UI metadata 和
只影响性能的环境选择不进入 Result Identity。若任何结果相关 identity 无法可靠解析，
该 Binding 禁用 cross-Run caching，而不是产生不完整 key。

全局的是 identity schema；物理 authority、object store 与 Cache 均归一个 Project 所有，
不进行跨 Project 查找或 replay。committed Run Ledgers 通过 Node Result Manifest 对
Result Identity 提供权威映射；manifest 固定 compiler-owned contract metadata，并引用普通
与 artifact-capable Port 的 canonical value manifests。相同 Result Identity 只有在 manifest
相等时才允许跨 Run 发布，任何冲突都是 `result_identity_conflict`。

Cache v4 只保存已提交 Node Result Manifest 与 immutable objects 的引用，不内嵌或 base64
复制 typed scientific values。replay 保留 original producer provenance，并记录当前 Run 的
materialization，但不复制旧 Availability、Readiness、Operation Attempt 或 Engine
Invocation。Cache absence 是 miss；无效的当前 entry 立即失败；Cache publication 失败不
回滚已提交的 Node success。失败、取消、中断、partial、uncontrolled stochastic、身份不足
的远端结果，以及必须依赖 standalone artifact 的 export 结果不可缓存。

Candidate identity 从 producer Result Identity、output slot/sample identity、parent
Candidate identities 与 content digest 稳定派生；不使用 Run UUID，也不只使用 content
digest。Cache replay 保留 Candidate identity；相同 Candidate identity 对应冲突 content
或 lineage 时 fail closed。

相关决定见 [ADR-0031](./adr/0031-result-identity-and-project-scoped-cache.md) 与
[ADR-0039](./adr/0039-node-outcomes-publish-atomically-through-immutable-value-objects.md)。

## 9. 首次发布前的破坏性重置

v2 是唯一受支持的运行时格式：

- 不实现 v1 Workflow migrator、旧 Score alias、双格式 reader 或 pLDDT 自动换算；
- 仓库跟踪的示例、seed Workflow 和 fixtures 直接重写为 v2；
- Workflow、manifest 与 Cache 同步使用 v2 schema；
- 旧格式只返回 `unsupported_schema_version`，不猜测或转换；
- v1 规格和 superseded ADR 只保留为历史记录。

本地 `projects/`、Cache 和 run records 是可丢弃的开发状态，但本文只决定其不兼容性；
实际清理仍是独立、显式授权的破坏性操作，不能因实现本合同而自动删除。

相关决定见
[ADR-0022](./adr/0022-v2-is-a-pre-release-breaking-reset.md)。

## 10. 实施阶段

0. 把本文、`CONTEXT.md` 与 ADR-0018～ADR-0032 作为规格输入冻结；
1. 实现 Port Type Definition contracts、canonical codecs 与 FrozenCatalog view；
2. 实现 immutable `ModulePackage`、atomic Registry 和 `FrozenCatalog`；
3. 实现 Workflow v2 parser、compiler 与 immutable `ExecutionPlan`；
4. 实现 Binding-scoped Environment Configuration、Availability 与 Readiness；
5. 实现 Run Evidence Ledger、attempt/invocation 模型与 projections；
6. 实现 Result Identity、Candidate identity 与 Project-scoped Cache；
7. 实现 Metric/Method/Observation Context 与 Score Collections；
8. 实现 Selection Objective、Utility Transforms 和 selectors；
9. 按 11 个目标 Module Packages 迁移现有 Nodes，删除重复样板；
10. 修正 pLDDT/SimpleFold，并用本地 ESMFold2、本地 ESM-3、SoluProt 和 Protein-Sol
    验收零核心修改扩展；
11. 重写 examples、seed、fixtures 和完整 acceptance；后端合同稳定后另行设计前端。

每一阶段都先建立合同测试和删除旧平行路径。后续阶段不得临时引入第二套 Registry、
identity、provider mapping 或 evidence writer。

## 11. 已闭合与明确延期的事项

本蓝图不再有阻塞 v2 规格拆分的架构未决项。以下决定已经闭合：

- Utility 由 Workflow Selection Objective 拥有；
- Node/Metric 使用 YAML，Method/Binding/Port Type 等使用 typed Python registration；
- `MODULE_PACKAGE` 显式列出 resources，不使用 glob/helper discovery；
- Port Type、Observation Context、Readiness-before-Cache、Evidence Ledger、
  Result Identity 与 Candidate identity 已形成正式合同；
- SimpleFold confidence Method 已固定真实 pipeline。

以下是有意延期或可由实现票据在既定合同内决定的内容，不是架构 blocker：

- Private Run workspace 是否提取为独立 module；
- 未来 Python entry point loader；
- Run Evidence Ledger 的物理文件格式和内部类/helper 名称；
- 各目标 Module Package 的最终 ID 命名与具体源码拆分；
- frontend 和外部展示格式。

这些票据级选择不得改变 atomic Registry、FrozenCatalog、exact identity、
Readiness-before-Cache、single evidence writer、project-scoped Cache 或零核心修改的
既定 interface。
