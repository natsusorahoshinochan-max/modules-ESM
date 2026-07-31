# Protein Workbench 理论 Workflow 可用性调试任务与测试合同

日期：2026-07-31  
状态：讨论已接受；待锁定数值阈值与样例参数后执行

## 1. 文档地位

本文固化以下三条理论上可用的 Protein Workbench Workflow，以及使用
`2EMO.pdb`、`5G53.pdb` 和 `1PGA-75-gen1_0690.pdb` 对当前项目进行真实可用性
调试时的任务目标、输入合同、测试要求和结果分类。

本文是调试与缺口记录合同，不是修复计划、实现票据或替代 Workflow。后续执行必须以
本文定义的科学问题和判定 interface 为准；不能因为当前 Catalog、Port、Binding 或
provider 不支持，就缩小需求、改写科学问题或在 Workbench 外补接结果。

理论工作流讨论所依据的代码基线与当前项目测试输入：

- Git HEAD：`5dfb2c9`（`Refactor Protein Workbench modules and protocol workflows`）；
- 分支：`main`；
- `pdbs/2EMO.pdb`、`pdbs/5G53.pdb` 与 `pdbs/1PGA-75-gen1_0690.pdb`
  均是纳入 Git 的项目测试输入。

本文采用 `CONTEXT.md` 中的准确领域词汇。Node Type、Node Instance、Workflow、Run、
Execution Binding、Method、Candidate、Score Observation 和 Run Evidence Ledger 不得混用。

## 2. 调试任务目标

本任务的目标是：

1. 以三个具有真实科学复杂性的 PDB 作为原始 Project Input；
2. 按设计上理论成立的 Workflow 尝试在当前项目中完成 authoring、compile、Run
   admission、execution、result inspection 和 evidence inspection；
3. 暴露当前项目在科学合同、组合能力、执行、Readiness、provider、证据和用户可检查性
   上的不足；
4. 将每个不足定位到最早失效的公开 interface 或 seam；
5. 区分安全拒绝、不可解释失败和带有科学信息损失的伪成功；
6. 保存足以让后续维护者复核的原始事实，而不是边测试边修复。

本任务不以“让三个 Workflow 最终跑通”为当轮完成条件。能够安全、准确地证明某条
Workflow 当前不可用，也是有效调试结果。

## 3. 明确不在本任务中进行的工作

测试期间禁止：

- 修改 `core/`、`modules/`、`datatypes/`、public protocol、前端或测试代码；
- 新增 Node Type、Execution Binding、Method、Metric、Port Type 或 Utility Transform；
- 修复 Adapter、provider runtime、模型资产或下载流程；
- 在 Workflow 外编写辅助脚本以清洗 PDB、拆链、生成 FASTA、补 residue layout、构造
  Candidate Collection、建立 Candidate pairing 或拼接 Score；
- 因某个 Binding 不可用而自动或人工切换到 sibling Binding；
- 用 mock、历史 Cache 或已有输出替代要求的真实执行；
- 把未带准确 Method 和 Observation Context 的 PDB B-factor、文件名、裸分数或 provider
  details 提升为 Score Observation；
- 一边测试一边实施修复，然后继续把修复后的行为混入同一份原始缺口证据。

允许的状态变化仅限正常测试行为，例如创建 Project、导入 Project Input、保存
Workflow、compile、启动 Run，以及由这些操作产生的 Run Evidence 和 artifact。任何此类
状态变化必须能归属于准确测试 Run。

## 4. 理论可用的判定基础

“理论可用”不表示当前代码已经可以直接执行，而表示：

- Workflow 对应明确、合理且不过度声称的科学问题；
- 输入、科学操作、Candidate lineage、Metric、Method、Observation Context 和输出均有
  可定义的含义；
- Workflow 可以表示为通过准确 nominal Port Type 连接的 DAG；
- 所需能力若不存在，应被归类为项目缺口，而不是通过外部脚本回避；
- 即使 Run 成功，结论也必须受当前计算证据的科学解释范围约束。

测试 surface 是各 Module 的公开 interface。测试不需要穿过 interface 检查内部实现才
能判断成功；如果只有读取内部临时文件、私有对象或 provider 日志才能解释结果，则应
记录 evidence 或 interface 不足。

## 5. 统一结果分类

### 5.1 运行与能力缺口类型

#### `valid_rejection`

输入或请求超出准确声明的合同，系统在正确阶段以结构化、可解释的方式拒绝，并阻断
下游。安全拒绝可以是正确运行时行为，但不代表理论 Workflow 已可用。

#### `contract_gap`

理论 Workflow 所需的科学概念无法通过当前 Node Definition、Port Type、Metric、Method、
Observation Context 或参数合同表达。

#### `composition_gap`

单个能力可能存在，但输出和输入无法通过准确 Port 连接，或 Candidate lineage、pairing、
collection-level 操作无法在 Workflow 内表达。

#### `availability_gap`

选定 Execution Binding 的启动前提不存在，FrozenCatalog 应给出结构化 Availability
结论。

#### `readiness_gap`

Binding 在启动时可发现，但 Run admission 时的准确运行前提不满足。Readiness 必须发生
在任何 Cache lookup 之前。

#### `execution_gap`

Workflow 已通过 compile 和 Run admission，但 implementation、Adapter、provider 或
模型执行失败，且失败属于当前项目应管理的执行 seam。

#### `evidence_gap`

Run 或 Node 看似产生结果，但缺少足以解释 Candidate、Observation、alignment、artifact、
Method、pairing 或 terminal outcome 的 Run Evidence。

### 5.2 每条 Workflow 的顶层状态

#### `FULLY_USABLE`

理论 Workflow 按锁定合同完成，输出、Candidate lineage、Score Observation、artifact 和
Run Evidence 均完整且科学上可解释。

#### `SAFELY_BLOCKED`

系统在正确 interface 安全、结构化地阻断。运行时行为可以正确，但该 Workflow 当前仍
不可用；必须同时记录对应能力缺口。

#### `OPAQUE_FAILURE`

执行失败，但公开结果和 Evidence 不足以确定失败位置、原因或终止状态。

#### `UNSAFE_SUCCESS`

Run 或 Node 显示成功，却静默丢失、改写或错误解释科学信息，或者以隐式 fallback、顺序
配对、裸分数混合等方式产生误导性结果。这是最严重的结果。

同一测试可以同时具有运行时分类和项目能力分类。例如：系统明确拒绝不支持的 modified
residue，可记录为 `valid_rejection`，顶层状态为 `SAFELY_BLOCKED`，同时登记一个
`contract_gap`。

## 6. 三个样例与 Workflow 映射

| 样例 | 理论 Workflow | 首要设计检验 |
|---|---|---|
| `pdbs/2EMO.pdb` | 已知骨架的约束序列重设计 | modified residue、功能位点约束、结构比较解释 |
| `pdbs/5G53.pdb` | 多轨、可变长度的结构条件生成 | 多链选择、缺失 layout、显式长度分支 |
| `pdbs/1PGA-75-gen1_0690.pdb` | 多 folding Method 的结构共识验证 | structure-to-sequence lineage、多 Binding、sibling pairing |

测试直接引用上述 Git 管理的文件路径。执行记录通过 Git HEAD 固定输入版本，不得以仓库外
同名文件替代这些 Project Input。

## 7. Workflow 1：2EMO 约束骨架重设计

### 7.1 科学问题

给定成熟 GFP 结构，在明确保留 chromophore 相关区域和用户指定关键位置的前提下生成
序列 Candidate，并通过独立折叠、reference-relative 结构比较和序列可溶性预测进行计算
筛选。

允许的最终解释仅限于“预测保持 GFP-like fold 和 chromophore-forming motif”。本
Workflow 不证明荧光、光谱性质、成熟效率或实验稳定性。

### 7.2 原始输入事实

`pdbs/2EMO.pdb` 在固化时包含：

- 单链 A；
- 1,740 条 `ATOM`；
- 80 条 `HETATM`；
- 221 个标准 `ATOM` residue；
- residue 编号范围 A:6 至 A:229；
- A:64 后直接出现 A:68；
- `HETATM CSH A:66` 表达成熟 chromophore；
- 无显式多 MODEL；
- 有终止 `END`。

原始文件必须直接作为 Project Input。不能在测试前删除 HETATM、把 CSH 改写成普通氨基酸、
补残基或重编号。

### 7.3 理论 Workflow

```text
原始 2EMO structure
→ 建立可设计的蛋白结构表示
→ 声明 chromophore/关键位置固定约束
→ ProteinMPNN 生成 sequence Candidate Collection
→ 通过准确 folding Binding 独立折叠
→ 与 2EMO reference 做 residue-mapped Structure Alignment
→ 产生 TM-score、RMSD、folding confidence 和 solubility Observations
→ 通过显式阈值或注册 Utility 选择
→ 导出 Candidate 和完整 Run Evidence
```

该图描述理论科学操作，不表示当前 Catalog 必然已经提供每个所需 Node Type。

### 7.4 Project Input 与结构导入要求

导入必须完整保留：

- 原始 PDB 文本；
- 所有 ATOM/HETATM；
- chain 和 residue identity；
- Project Input provenance；
- 稳定 structure Candidate identity。

导入阶段不一定需要理解 CSH，但不能不可逆地丢失它。

### 7.5 Modified-residue 判定

面对 CSH，安全行为只有两类：

1. 以类型化合同保留 modified residue、准确 residue identity、其科学含义和转换 provenance；
2. 在建立 ProteinPrompt、设计结构或其他需要 canonical residue 的最早 interface，明确、
   结构化地拒绝，并阻断所有依赖该值的下游 Node Instance。

不安全行为包括：

- 静默跳过 CSH 后产生 221-residue ProteinPrompt；
- 把 A:64 与 A:68 视为普通连续肽键；
- 自动将 CSH 映射成一个普通氨基酸；
- 继续生成 Candidate，却没有记录 chromophore region 的 disposition；
- 让 provider traceback 成为用户首次得知 modified residue 不受支持的位置。

明确拒绝应登记为 `valid_rejection` + `contract_gap`，顶层状态为 `SAFELY_BLOCKED`。

### 7.6 设计约束要求

若 Workflow 能继续，约束必须：

- 以稳定 residue identity 引用位置，而不是临时数组索引；
- 将 chromophore 前体区域设为不可设计；
- 允许用户显式指定其他固定位置；
- 只开放明确列出的设计位置；
- 在 Candidate lineage 和 Run Evidence 中保留有效约束 identity。

不能在测试过程中手工换算被忽略 residue 后的 ProteinMPNN 索引。

### 7.7 ProteinMPNN、折叠与选择要求

- ProteinMPNN 只能接收其准确合同支持的结构值；
- 每个 sequence Candidate 必须保留准确 parent structure 和约束 provenance；
- folding Node Instance 必须固定准确 Execution Binding，不允许 fallback；
- pLDDT、pTM、TM-score、RMSD 和 solubility 必须是绑定 Candidate、Metric、Method 和
  Observation Context 的 Score Observation；
- 不同 Metric 的裸值不得直接相加；
- 若使用 weighted rank 或 Pareto，必须存在准确注册的 Utility Transform；
- 若当前缺少 Utility Transform，应记录 `contract_gap`，不能临时归一化。

### 7.8 结构比较与 Evidence 要求

Structure Alignment 和下游 Metric 必须明确：

- subject/reference Candidate；
- 实际参与 alignment 的 residue correspondence；
- modified/missing region 的处理；
- reference-normalized TM-score 的准确 reference；
- normalization length 和 aligned atom count；
- alignment Method 和 evidence digest。

若产生 TM-score 却无法说明 A:64–A:68 如何处理，应记录 `evidence_gap`，不能判为成功。

## 8. Workflow 2：5G53 多轨、可变长度结构条件生成

### 8.1 科学问题

基于 5G53 中 A2A receptor chain A 的已解析结构，在准确识别坐标缺口的前提下，为指定
缺失环区建立多个长度分支，生成 sequence/structure Candidate，并判断已解析 receptor
core 是否保持。

第一轮不验证配体结合、mini-Gs 结合、active-state signalling、膜环境稳定性或 receptor
功能。

### 8.2 原始输入事实

`pdbs/5G53.pdb` 在固化时包含：

- 四条蛋白链 A、B、C、D；
- A、B 为 A2A receptor 的两个结构副本；
- C、D 为 engineered mini-Gs 的两个结构副本；
- 本地坐标接触关系为 A–C 和 B–D；
- 7,247 条 `ATOM` 与 112 条 `HETATM`；
- chain A 有 283 个已建模标准 residue；
- chain A 存在 A:146→A:159 和 A:211→A:224 两个明显编号缺口；
- 文件包含 NEC、GDP 和 SOG 等非蛋白记录；
- 无显式多 MODEL；
- 有终止 `END`。

原始四链文件必须直接作为 Project Input。不能在 Workbench 外先拆出 chain A。

### 8.3 第一轮理论 Workflow

```text
原始 5G53 complex
→ 显式选择 receptor chain A
→ 建立保留坐标缺口的 ProteinPrompt
→ 在准确缺口位置插入 masked residues
→ 建立多个显式长度分支
→ ESM-3 paired generation
→ 通过准确 folding Binding 独立折叠生成 sequence
→ 分别与原始 resolved core 和 ESM-3 counterpart 比较
→ 检查 core 保持、loop 连续性、clash 和 Method-specific confidence
→ 合并 Candidate Collection
→ 通过准确 Observation 过滤或选择
→ 导出 Candidate 和 Run Evidence
```

第一轮只将 chain A 的 protein-only ProteinPrompt 送入 ESM-3。C、D 和配体是必须明确
处置的原始上下文，但不参与生成或功能评价。

### 8.4 导入与链选择要求

导入必须保留四条链、全部 HETATM、原始文本和 provenance。系统不得：

- 自动选择距离最近的链组合作为 biological assembly；
- 合并 A/B 或 C/D；
- 因下游只需要 chain A 而在导入阶段丢弃其他记录。

Workflow 必须通过显式 Node Instance 选择 chain A。链选择结果必须记录：

- 保留和排除的 chain identities；
- chain-A HETATM 的处置；
- 输出结构与原始复合物的 provenance 关系。

protein-only Prompt 可以排除 NEC/SOG 等非蛋白值，但必须明确声明它们没有成为生成条件。
静默排除后仍把结果描述为 agonist-conditioned，应判为 `UNSAFE_SUCCESS`。

### 8.5 缺失 residue layout 要求

A:146→A:159 和 A:211→A:224 不得被解释为普通连续肽键。理论 Workflow 必须能够：

- 保留原始已解析 residue identities；
- 指定准确插入位置；
- 为插入 residue 分配稳定、chain-qualified identity；
- 将插入位置的 sequence 和 structure 初始设为 masked；
- 保持已解析 receptor core 的所有未编辑 track；
- 明确区分观察到的坐标、用户声明的目标 layout 和生成值。

若只能随机在全链插入，无法指定 gap，应记录 `contract_gap`。若系统压缩编号并把 gap 两侧
当作连续结构，应判为 `UNSAFE_SUCCESS`。

### 8.6 可变长度分支要求

每个被测试的 gap 至少应形成三个显式分支：

- shorter；
- numbering-implied length；
- longer。

准确长度在执行前另行锁定。每个分支必须具有：

- 独立有效 residue layout；
- 明确的有效随机性；
- 独立 Candidate lineage；
- 准确 Node/Binding/Method identity；
- 可在 Workflow 内通过 collection-level Node 合并的输出。

不得在 Workbench 外复制运行三次后手工拼接 Candidate。若当前项目只能这样完成，应记录
`composition_gap`。

### 8.7 ESM-3 生成要求

- 只有指定 gap 的 sequence/structure 位置可以 masked；
- resolved core track 必须保持原值和 residue identity；
- sequence Candidate 与 ESM-3 structure counterpart 必须有显式 one-to-one pairing；
- 不同长度分支必须保持独立 lineage；
- selected Binding 不支持该 Prompt 时必须结构化阻断；
- 不允许从 remote Binding 切换到 local Binding，或从 paired generation 改成
  sequence-only generation。

### 8.8 独立折叠、比较与选择要求

每个生成 sequence 至少需要两类结构比较：

1. 独立折叠结构相对于原始 chain-A resolved core；
2. 独立折叠结构相对于其 ESM-3 structure counterpart。

不同长度 Candidate 的 reference comparison 必须使用明确、可比较的 resolved-core residue
scope。不得直接使用不同 normalization length 的全链 TM-score 横向排名。

至少检查：

- resolved-core TM-score；
- resolved-core RMSD；
- gap 两侧主链连续性；
- 新生成 loop 与 receptor core 的 clashes；
- folding Method 的 confidence；
- ESM-3 counterpart 与独立 folding Method 的结构一致性。

如果只能获得无法解释 residue correspondence 的整体分数，应记录 `evidence_gap`。

## 9. Workflow 3：1PGA-75 生成结构的多 Method 共识验证

### 9.1 科学问题

给定一个已有生成结构，提取其准确序列，分别通过 ESMFold2 和 SimpleFold 的准确
Execution Binding 独立重新折叠，并判断输入结构与两种 Method 输出是否一致。

第一轮只验证一个 sequence Candidate；每个 Method 只生成一个结构；不进行 Candidate
排名。

### 9.2 原始输入事实

`pdbs/1PGA-75-gen1_0690.pdb` 在固化时包含：

- 单链 A；
- 连续 A:1 至 A:75；
- 618 条 `ATOM`；
- 无 `HETATM`；
- 无显式多 MODEL；
- 主链 N/CA/C/O 完整；
- 有终止 `END`；
- B-factor 约为 81–97，但文件没有提供足以把它解释为某个准确 Method 的 pLDDT
  Observation 的 provenance。

文件名中的 `gen1_0690` 只能作为 Project Input 标签，不能成为 Method identity。

### 9.3 理论 Workflow

```text
原始 generated structure Candidate
→ 提取带 parent lineage 的 sequence Candidate
├─ folding.fold + exact ESMFold2 Binding
└─ folding.fold + exact SimpleFold Binding
→ 两路分别与输入 structure Candidate 对齐并评分
→ 根据共同 sequence parent 显式建立 sibling structure pairing
→ 两个 folding Method 的输出相互对齐并评分
→ 保留各自 Method-specific confidence Observations
→ 形成 three-way structural-consistency 结论
→ 导出结构、alignment、Observations 和 Run Evidence
```

### 9.4 Structure-to-sequence lineage 要求

从结构提取出的序列必须成为可以连接 `folding.fold` 的 sequence Candidate，并至少表达：

```text
input structure Candidate
└─ extracted sequence Candidate
```

不接受：

- 只产生无法连接 folding Node 的裸 `ProteinSequence`；
- 在 Workflow 外生成 FASTA 后重新导入；
- 提取序列后丢失 parent identity；
- 用文件名或 Node 执行顺序重建 lineage。

若结构序列可以提取，但不能进入 Candidate Collection 和 folding Port，应记录
`composition_gap`。

### 9.5 Folding Binding 要求

两个 Node Instance 必须分别固定：

- `folding.fold` 的准确 ESMFold2 Binding；
- `folding.fold` 的准确 SimpleFold Binding。

二者消费同一个 sequence Candidate，各生成一个 structure Candidate。必须保留：

- exact Binding、Method、contract digest 和 result-affecting identity；
- Availability；
- Run-scoped Readiness；
- Candidate parent lineage；
- 每个实际启动 Engine Invocation 的 terminal fact。

一个 Binding 不可用或不 ready 时，不得自动改用另一个 Binding。安全阻断应记录对应
`availability_gap` 或 `readiness_gap`，顶层状态为 `SAFELY_BLOCKED`。

### 9.6 分别与输入 reference 比较

必须进行：

```text
ESMFold2 structure → input structure reference
SimpleFold structure → input structure reference
```

每一路至少产生：

- 明确的 Structure Alignment；
- reference-normalized TM-score；
- RMSD；
- subject/reference Candidate identity；
- residue/atom correspondence；
- normalization length 与 aligned atom count；
- alignment Method provenance 和 evidence digest。

三者理论上具有同一 75-residue sequence。任何长度、sequence 或 residue correspondence
变化必须结构化报告。

### 9.7 跨 Method sibling pairing 要求

ESMFold2 和 SimpleFold structure Candidate 必须通过共同 sequence parent 建立显式
pairing：

```text
                    ┌─ ESMFold2 structure Candidate
sequence Candidate ─┤
                    └─ SimpleFold structure Candidate
```

不得按 collection 顺序、文件名或“每边恰好一个值”隐式配对。若当前项目没有表达 sibling
pairing 的 collection-level Node，应记录 `composition_gap`，不能外部构造 pairing 文件。

### 9.8 B-factor 与 confidence 要求

输入 PDB 的 B-factor 必须作为未经解释的原始坐标字段保留。它不得：

- 自动成为 pLDDT Score Observation；
- 与新 Run 中的 pLDDT 求平均；
- 进入 filter、sort、rank 或阈值判断；
- 被赋予从文件名猜测得到的 Method。

只有本次 Run 中由准确 Binding 产生、并带完整 Metric/Method/Context 的 confidence
Observation 才可解释。两个 Method 的 confidence 必须保持分开。

自动把输入 B-factor 解释为 pLDDT，应判为 `UNSAFE_SUCCESS`。

### 9.9 Three-way 结果分类

数值阈值锁定前，逻辑结果固定为：

- `three_way_consistent`：两个 Method 均接近输入结构，且彼此接近；
- `method_disagreement`：一个 Method 接近输入，另一个明显不同；
- `input_disagreement`：两个 Method 彼此一致，但都不同于输入；
- `all_disagree`：三者均缺乏一致性；
- `insufficient_evidence`：Binding 不可用、comparison 不完整或 provenance 不足。

这些只描述计算结构一致性，不证明稳定性或功能。

## 10. 统一执行纪律

每条测试执行时必须：

1. 记录当前 Git HEAD、工作树状态和准确输入文件名；
2. 记录 FrozenCatalog identity；
3. 保存准确 Workflow 文档和 revision；
4. 记录每个 Node Instance 的 Node Type、Binding、Method、版本和 contract digest；
5. 保存 save/relock/compile 结果；
6. 保存 Availability 和 Run-scoped Readiness；
7. 保存 Run ID、Run terminal outcome 和 Run Evidence Ledger；
8. 保存 Node Execution Attempt、Operation Attempt 与 Engine Invocation 事实；
9. 保存产生的 Candidate、Score Observation、alignment 和 artifact identity；
10. 检查结果 inspection interface 是否足以让用户复核；
11. 对最早 blocking seam 分类；
12. 不实施修复，转入下一项独立测试。

一个测试的失败不授权修改项目，也不自动阻止其他独立测试。若某个 Workflow 在 authoring
阶段已因能力缺失无法表达，应记录该最早缺口，不通过外部加工强行推进该 Workflow；随后
仍可执行不依赖该缺口的其他样例。

## 11. 建议实际执行顺序

执行顺序按输入复杂度，而不是按 Workflow 编号：

1. `1PGA-75-gen1_0690.pdb`：基线结构、lineage、多 Binding 与 comparison；
2. `2EMO.pdb`：modified-residue 与功能位点语义；
3. `5G53.pdb`：多链、HETATM、缺失 layout 和可变长度组合。

## 12. 缺口记录的最小内容

每个发现至少记录：

- finding ID；
- 样例输入文件名；
- Git HEAD、Catalog identity、Workflow revision 和 Run ID；
- 预期理论合同；
- 实际观察；
- 最早失效的 interface 或 seam；
- 分类：`contract_gap`、`composition_gap`、`availability_gap`、`readiness_gap`、
  `execution_gap` 或 `evidence_gap`；
- 顶层 Workflow 状态；
- 原始错误、Ledger fact、manifest、artifact 或截图位置；
- 对下游科学解释的影响；
- 是否可稳定复现。

缺口记录可以说明“缺少什么合同”以及“为什么当前结果不可用”，但不得在本调试任务内
继续实施修复或把修复后的复测覆盖到原始证据中。

## 13. 执行前尚需锁定的参数

以下参数尚未在讨论中确定，不能由执行者擅自猜测：

1. 2EMO 中除 chromophore 区域之外的固定位置和允许设计位置；
2. 2EMO 的生成 Candidate 数、ProteinMPNN sampling 参数和筛选阈值；
3. 5G53 选择哪一个缺口作为第一轮生成目标；
4. 5G53 的 shorter、numbering-implied 和 longer 三个准确长度；
5. 5G53 的 ESM-3 sampling 参数、Candidate 数和 resolved-core 比较阈值；
6. 1PGA-75 three-way consistency 的 TM-score、RMSD 和 confidence 阈值；
7. 每个真实 provider Binding 的执行预算和允许的最长等待时间。

在这些参数被讨论并明确接受以前，可以进行输入与 Catalog 的只读 preflight，但不能把
任何临时数值作为正式测试合同执行。
