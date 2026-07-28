# Protein Workbench v2 模块与指标契约讨论纪要

日期：2026-07-27

状态：讨论进行中；“已确认”内容可作为后续规格输入，“待定”内容尚不能实现

前提：把 `.scratch/protein-workbench-backend-repair/spec.md` 完成后的后端视为 v1 基线

## 1. 目标与范围

最初的产品目标保持不变：

1. 通过可连接的节点组合蛋白设计、折叠、评价、转换与选择流程；
2. 让具备开发经验的仓库维护者能够方便地新增科学操作。

当前前端实现不作为 v2 后端设计约束。后端模块、数据和 API 契约稳定后，现有前端将被
废弃并另行重写。

“方便地自定义节点”在 v2 中明确指：

- 开发者在仓库内新增或扩展一个 Module Package；
- 提供 Node Definition、实现或 Adapter，以及统一契约测试；
- 不修改 `core/`；
- 启动时发现并注册。

v2 暂不包含第三方 `pip install` 插件、插件管理、运行时热加载或依赖自动安装。设计保留
未来 Python entry point 的接入点，但它只能向 Registry 提供同一种 Module Package
注册对象，不能形成第二套模块契约。

## 2. 已确认的模块边界

### 2.1 Node Type 表达科学操作

Node Type 按科学操作划分；本地、远程、SDK、服务端点或其他部署差异由 Adapter 承接，
并形成不同的 Execution Bindings。因此“本地 ESMFold2”和“远程 ESMFold2”可以共享
同一科学 Node Type，而不是两个互不相干的 Node Type；若模型或版本的科学身份不同，
则由 Method 明确区分。

Adapter、模型、checkpoint、运行时与部署身份必须进入缓存、manifest 和 provenance。
只要这些身份会影响结果，就不能被缓存键或可复现记录忽略。

### 2.2 Module Package 是内聚交付单元

一个 Module Package 可以提供多个 Node Types。分组依据是共享的科学能力、依赖、
Adapter 或领域语义，而不是机械地坚持“一目录一个节点”。

YAML 是 Node Definition 的唯一公共合同。Python 只负责把 Definition 绑定到工厂、
Adapter 与执行方式，不另行定义一套用户可见的节点元数据。

### 2.3 Node Definition 独立且默认平铺

- 每个 Node Type 恰好维护一份独立 YAML Node Definition；
- 同一个 Module Package 的 Definitions 默认平铺在 `definitions/`；
- Node Definition、Python 实现、Adapter、测试和目录不要求一一对应，多个 Node Types
  可以共享内聚的实现、Adapter 与测试夹具；
- 只有确有节点专属模板、脚本、大型 fixture 或 golden files 时，才建立相应的资源或
  测试子目录；
- Module Package 注册对象显式绑定 Definition 与实现或 Adapter，Registry 对每份
  Definition 只加载一次；
- 统一契约测试按 Module Package 的 Definitions 参数化，不复制每节点测试脚手架；
- v2 不新增会重复 Node 合同的包级 YAML，也不要求“一节点一目录”。

该决定由
[ADR-0023](./adr/0023-independent-node-definitions-flat-by-default.md)
记录；外部先例与取舍见
[Module Package 与 Node Definition 组织方式调研](./research/2026-07-27-module-package-layout-prior-art.md)。

### 2.4 发现与错误语义

- `modules/` 下每个一级目录代表一个 Module Package，并只暴露一个显式
  `ModulePackage` 注册对象；
- 该对象显式列出包提供的 Node Definitions、实现或 Adapters、Metric Definitions 和
  可用性检查；
- 启动发现只扫描一级包并读取统一对象，不递归搜索任意 `definition.yaml`，不调用分散在
  各节点中的 `register()`，也不依赖 import side effect；
- 包入口不得急切导入可选 provider 依赖；依赖缺失必须由可用性检查表达为
  `unavailable`；
- Definition 格式错误、包导入失败、注册失败或合同冲突：启动原子失败，不允许产生部分
  Registry。
- 包合同有效，但模型、GPU、运行时、二进制或凭据缺失：Node Type 仍被发现；受影响的
  Execution Binding 以结构化 `unavailable` 状态说明原因。
- Registry 在启动完成后不可变；v2 不支持运行时热加载。
- 每个 Module Package 必须通过统一的契约测试工具。

这些决定由 [ADR-0018](./adr/0018-module-packages-and-startup-discovery.md) 记录，并取代
v1 的 [ADR-0007](./adr/0007-module-registration-two-phase.md)。

显式入口的文件名和符号，以及实现与测试子目录的最终命名尚未确定；当前决定已经固定
发现边界、“每包一个对象”，以及 Definition 的默认物理组织原则。

### 2.5 Execution Binding 拥有可用性

一个 Node Type 可以具有多个 Execution Bindings。每个 Binding 显式关联：

- 一个 Node Type；
- 一个 Method；
- 一个 Adapter 或 factory；
- 该执行路径自己的 Availability。

Node Definition 始终描述并发现科学操作，不因当前机器缺少某个可选依赖而消失。模型、
GPU、运行时、二进制或凭据缺失只会使受影响的 Binding 变为结构化
`unavailable`；同一 Node Type 的其他 Bindings 不受影响。Binding 合同错误或相互冲突
仍属于启动期原子失败。

该决定由
[ADR-0025](./adr/0025-execution-bindings-own-availability.md)
记录。Binding 特有参数放在何处仍待后续讨论。

### 2.6 Workflow 显式固定 Execution Binding

每个持久化 Node Instance 必须同时保存：

- `node_type_id`：选择的科学操作；
- `binding_id`：选择的准确执行路径。

Workflow 加载与验证必须确认 Binding 存在、属于对应 Node Type，并且当前可用。所选
Binding 不可用时，在执行前返回结构化验证错误；不得根据当前机器自动选择“任意可用
Binding”，也不得静默回退到其他 Method、Adapter 或部署方式。

`binding_id` 必须进入 cache key、run manifest 与 provenance。仓库内示例、seed
Workflow 和测试 fixtures 也必须显式固定 Binding，保证相同 Workflow 不会因运行环境
不同而悄然改变科学 Method 或部署路径。

该决定由
[ADR-0026](./adr/0026-workflows-pin-execution-bindings.md)
记录。

### 2.7 已确认的现有 Node 归并

当前快照包含 45 个 Node Types、43 个一级节点目录、43 个 `register()` 和 87 次
Definition 加载。v2 不把这些物理目录原样平移，而按科学能力、依赖、Adapters 与测试
资产归并为以下十个生产 Module Packages：

| Module Package | 纳入的当前能力与迁移处理 |
| --- | --- |
| `prompt_authoring` | layout、residue edits、Prompt assemble、function annotation、track map/override、random mask/insert，以及改为通用 Prompt 操作的 `esm3.update_prompt_sequence` |
| `esm3` | sequence generation、structure generation 与配对 generation，共享 ESM-3 Adapters、转换、校验和 provenance |
| `folding` | ESMFold2 与 SimpleFold folding 归并为一个科学 Node Type 的不同 Bindings；SimpleFold structure confidence evaluation 保持独立 Node Type |
| `proteinmpnn` | constraints、design、score，以及输出 `proteinmpnn.constraints` 的 random fixed positions |
| `structure_annotation` | 重复的 mkdssp secondary-structure Nodes 与 SASA 调用归并为一个同时输出 secondary-structure/SASA tracks 的结构注释 Node；secondary-structure agreement 保持独立 |
| `structure_comparison` | single/pairwise alignment、TM-score、batch TM-score 与 RMSD |
| `structure_transform` | chain selection、backbone extraction 与 sequence extraction |
| `protein_io` | sequence/structure import 与 export，共享路径、artifact 和格式合同 |
| `selection` | filter、sort、top-k、weighted-rank、Pareto 与 diversity selection |
| `collection_ops` | Candidate concatenation 与 Score merge；`aggregate_confidence` 不按当前跨 Metric、无 subject 的行为原样迁移 |

`stub.echo` 从生产发现中移除并转为契约测试 fixture。未来本地 ESM-3 扩展 `esm3` 的
Bindings，本地 ESMFold2 扩展 `folding` 的 Bindings；SoluProt 与 Protein-Sol 组成新的
`solubility` Module Package。

该决定由
[ADR-0024](./adr/0024-consolidate-nodes-into-capability-packages.md)
记录。

## 3. 已确认的评分模型

评分身份从单一 `score_id` 提升为：

```text
Candidate + Metric + Method -> Value
```

- **Candidate**：被评价的对象；
- **Metric**：测量的科学量；
- **Method**：得到该量的算法、模型或模型变体；
- **Value**：该次观察值。

Module Package 在 YAML 中声明 Metric Definitions，并在启动时合并到 Metric Registry。
同一 Metric 可以由多个包声明，但科学含义、value shape、单位、方向、canonical range、
granularity 与 aggregation 必须一致；不一致时启动失败。Workflow 与 selector 必须指向
精确的 `metric + method`，不能让运行时任意选择实现。

该决定由 [ADR-0019](./adr/0019-scientific-metric-and-method-identity.md) 记录。

### 3.1 Weighted Rank 只组合 Utility

Weighted Rank 禁止直接相加不同 Metric 的 canonical raw values。每个参与组合的精确
`metric + method` 必须具有显式、版本化且可审计的 Utility Transform，把 canonical
value 映射到无量纲 `[0, 1]`；weight 只作用于转换后的 utility。缺少有效转换时，
Workflow 验证失败。

例如，pLDDT `80` 可通过线性 `x / 100` 得到 utility `0.8`，pTM `0.8` 可通过 identity
得到 utility `0.8`。禁止根据当前 Candidate 集合做隐式 min-max，也禁止由数值范围猜测
转换方式。实际采用的转换身份、版本与参数必须可持久化并进入 run provenance；它具体由
Metric Definition 还是 Workflow objective 拥有，仍待讨论。

该决定由 [ADR-0021](./adr/0021-weighted-rank-uses-explicit-utilities.md) 记录。

## 4. 三组扩展案例带来的结论

### 4.1 本地 ESMFold2

ESMFold2 证明科学操作与部署方式必须分离。本地模型与远程服务可共享折叠 Node Type，
但各自形成 Execution Binding；Adapter、Method、模型版本和部署身份必须进入
provenance 与缓存身份。

### 4.2 本地 ESM-3

ESM-3 的能力不必被塞进单个“大节点”。一个内聚的 ESM-3 Module Package 可以提供多个
生成或转换 Node Types，并共享本地 Adapter、模型加载和测试夹具。它应成为“仓库内新增
包、启动发现、零核心修改”的验收案例。

### 4.3 SoluProt 与 Protein-Sol

调研边界仅包括 `/Users/sorachan/Documents/ESM-workflow-NEXT` 中作为依赖仓库存在的
SoluProt 和 Protein-Sol，不采用该目录其他实现。

- SoluProt 的多个模型变体说明 Metric 与 Method 必须分离；
- Protein-Sol 同时产生 percent-sol、scaled-sol、population-sol、pI 等不同科学字段，
  说明一个 Method 可以产生多个 Metrics，不能压缩成一个 `score_id`。

这两个工具也应成为 Module Package、Metric Registry 与统一契约测试的验收案例。

## 5. 已确认的 pLDDT 公共合同

Workbench 对外只暴露：

- `structure.plddt.per_residue`：逐有效蛋白残基序列，`[0, 100]`；
- `structure.plddt.mean_residue`：上述序列的残基等权算术平均，`[0, 100]`。

两者均为无量纲且数值越高越好。平均值排除 padding、chain break、非蛋白 token 与
NaN，不能用逐原子加权的聚合量代替。

转换必须由 Adapter 的静态合同决定：

- ESM-3 SDK 的当前公开值为 `[0, 1]`，乘以 100；
- ESMFold2 的当前公开值为 `[0, 1]`，乘以 100；
- SimpleFold 高层 wrapper 已返回 `[0, 100]`，保持不变；
- 若直接使用 SimpleFold ConfidenceModule 的 `[0, 1]` 输出，则乘以 100。

禁止用 `max(values) <= 1` 猜测尺度。结构序列化仍使用各 provider 要求的 native scale，
避免重复乘以 100。pTM 继续使用 `[0, 1]`，PAE 继续使用埃；经典 Meta ESMFold 不属于
项目范围，不进入需求、迁移或验收。

SimpleFold 的 Method 必须标识实际使用的 confidence head 与 latent checkpoint，不能把
未参与 pLDDT 计算的 folding `model_name` 当作评分 Method。具体参数修正方式仍待设计。

事实核查见
[pLDDT 数值尺度与公共契约核查](./research/2026-07-27-plddt-value-contract.md)，正式决定见
[ADR-0020](./adr/0020-canonical-plddt-contract.md)。

## 6. 已确认的开发期破坏性重置

当前项目尚未投入使用，v2 因此是首次正式发布前的破坏性合同重置，也是唯一受支持的
运行时格式：

- 不实现 v1 Workflow 迁移器、旧 Score 别名、双格式读取器或 pLDDT 自动换算；
- 本地 `projects/`、缓存和运行记录属于可丢弃的开发状态，切换时直接清理并重新生成；
- 仓库跟踪的示例、seed Workflow 和测试 fixture 必须直接重写为 v2；
- Workflow 文件增加顶层 schema version；manifest schema 与 cache namespace 同步切换
  到 v2；
- 旧格式只返回结构化 `unsupported_schema_version`，不猜测或转换；
- v1 规格与旧 ADR 可以作为历史记录保留，但不参与运行时行为。

缓存必须使用全局 v2 namespace，不能只依赖开发者逐个提升 Node Type 的版本，否则公共
Score、Metric、Method 等数据结构变化可能错误复用遗漏升级的缓存。

该决定由 [ADR-0022](./adr/0022-v2-is-a-pre-release-breaking-reset.md) 记录。

## 7. 已确认的实施顺序

1. 冻结 v2 术语与功能规格；
2. 实现统一 Module Package 注册、启动发现和契约测试工具；
3. 实现 Metric Registry 与新的 Score Observation；
4. 按新规范重构现有模块并移除重复样板；
5. 修正 pLDDT 尺度与 Method 身份；
6. 重写 selector 与其他消费者，并将 Workflow、manifest 和 cache 切换为纯 v2 合同；
7. 重新生成示例与 fixture，并用本地 ESM-3、SoluProt 和 Protein-Sol 验证零核心修改扩展；
8. 后端契约稳定后再设计并重写前端。

## 8. 尚未定案

以下内容仍需逐项讨论，不能视为实现要求：

1. Utility Transform 由 Metric Definition 还是 Workflow objective 拥有，以及 weight
   的符号与归一化规则；
2. Module Package 注册入口的文件名和符号、实现与测试子目录命名、YAML 的确切字段，
   以及 Definition 是逐项显式列出还是由受控 helper 枚举；
3. Binding 特有参数放在 Node Definition、Binding 合同还是 Workflow 配置中的何处；
4. SimpleFold evaluate 的 Method 身份与误导性参数如何修正。
