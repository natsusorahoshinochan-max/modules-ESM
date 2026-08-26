# Protein Workbench 理论 Workflow 可用性调试任务与测试合同

日期：2026-07-31  
状态：历史调试基线；测试合同已经执行，本文件中的版本矩阵保留为当时快照

本文件中的命令、版本矩阵、双阶段判定和 confirmation retry 纪律均不适用于
当前单阶段 Acceptance Campaign。

## 1. 文档地位

本文固化以下三条理论上可用的 Protein Workbench Workflow，以及使用
`2EMO.pdb`、`5G53.pdb` 和 `1PGA-75-gen1_0690.pdb` 对当前项目进行真实可用性
调试时的任务目标、输入合同、测试要求和结果分类。

本文是历史调试与缺口记录，不是当前修复计划、实现票据或执行纪律。其科学
场景已由当前 Workflow 和 acceptance tests 接管。

理论工作流讨论所依据的代码基线与当前项目测试输入：

- Git HEAD：`5dfb2c9`（`Refactor Protein Workbench modules and protocol workflows`）；
- 分支：`main`；
- `examples/v2/structures/2EMO.pdb`、`examples/v2/structures/5G53.pdb` 与
  `examples/v2/structures/1PGA-75-gen1_0690.pdb`
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
状态变化必须能归属于准确测试 Run。另允许按第 13.6 节写入缺口报告和公开 protocol
响应副本；这些是测试记录，不是项目修复。

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
| `examples/v2/structures/2EMO.pdb` | 已知骨架的约束序列重设计 | modified residue、功能位点约束、结构比较解释 |
| `examples/v2/structures/5G53.pdb` | 多轨、可变长度的结构条件生成 | 多链选择、缺失 layout、显式长度分支 |
| `examples/v2/structures/1PGA-75-gen1_0690.pdb` | 多 folding Method 的结构共识验证 | structure-to-sequence lineage、多 Binding、sibling pairing |

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

`examples/v2/structures/2EMO.pdb` 在固化时包含：

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
→ 与 2EMO reference 产生 residue-mapped Structure Alignment Evidence
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

本轮设计范围固定如下：

- `CSH A:66` 必须作为由三个 parent residues 形成的 modified residue 处理；根据
  [RCSB 2EMO entry](https://www.rcsb.org/structure/2EMO) 的 polymer modification 记录，
  其语义 parent span 为 A:65–A:67，固定为 Ser–His–Gly。该外部记录只用于声明
  chromophore precursor 约束，不能替代或改写原始 Project Input；
- 固定 residue identities 为 A:42、A:44、A:46、A:60–A:72、A:92、A:94、A:96、
  A:110、A:112、A:121、A:123、A:145、A:148、A:150、A:165、A:167、A:183、
  A:203、A:205、A:220 和 A:222；
- A:60–A:72 整段固定，用于覆盖 chromophore precursor 和直接序列邻域；其余离散位置
  来自原始坐标中距 `CSH A:66` 任一重原子不超过 6 Å 的 residue 集合；
- A:6–A:229 中具有建模坐标且不在上述固定集合内的 canonical parent residues 全部允许
  设计；不得增加未建模端部 residue；
- 若系统不能把 `CSH A:66` 与 A:65–A:67 的 parent span 类型化关联，应在约束建立前
  安全阻断，而不是把 A:65–A:67 当成三个无坐标普通位置。

上述 residue identities 是测试合同。任何零基 ProteinMPNN 位置只能由 Workbench 内的
显式 residue mapping 产生，不能由执行者手工换算。

### 7.7 ProteinMPNN、折叠与选择要求

- ProteinMPNN 只能接收其准确合同支持的结构值；
- 每个 sequence Candidate 必须保留准确 parent structure 和约束 provenance；
- folding Node Instance 必须固定准确 Execution Binding，不允许 fallback；
- pLDDT、pTM、TM-score、RMSD 和 solubility 必须是绑定 Candidate、Metric、Method 和
  Observation Context 的 Score Observation；
- 不同 Metric 的裸值不得直接相加；
- 若使用 weighted rank 或 Pareto，必须存在准确注册的 Utility Transform；
- 若当前缺少 Utility Transform，应记录 `contract_gap`，不能临时归一化。

本轮准确执行参数为：

- `proteinmpnn.constraints.local@3.0.0` 使用 `designed_chains=["A"]`、
  `fixed_chains=[]`、`omit_amino_acids=[]`、`tied_residue_groups=[]`、
  `bias_by_residue=[]`；`designable_residue_ids` 与 `fixed_residue_ids` 只能使用上一节的
  稳定 residue identities；
- ProteinMPNN Binding：`proteinmpnn.design.local@4.0.0`；其 Method 保持
  `proteinmpnn.design.v_48_020_8907e667@3.0.0`；
- ProteinMPNN `effective_seed=2066001`、`num_sequences=8`、`temperature=0.1`、
  `backbone_noise=0`；
- 独立折叠 Binding：`folding.fold.esmfold2_remote@3.0.0`；
- 折叠 `effective_seed=2066002`、`num_samples=1`；远程 Binding 不声明 provider seed
  control，因此该 seed 只固定 Workbench randomness identity；
- 可溶性 Binding：`solubility.protein_sol.local@2.1.0`；
- 第二阶段按顺序应用四个 exact Observation filter：reference-normalized TM-score
  `>= 0.80`、Cα RMSD `<= 2.50 Å`、mean-residue pLDDT `>= 70`、
  `solubility.protein_sol_scaled >= 0.446`；
- 不做 weighted rank，也不以“至少必须选出一个 Candidate”为可用性条件。若八个
  Candidate 均未通过，但执行、Observation 和 Evidence 完整，仍可判定 Workflow 能力
  可用，并报告零个科学筛选通过值。

### 7.8 结构比较与 Evidence 要求

Structure Alignment Evidence 和下游 Metric 必须明确：

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

`examples/v2/structures/5G53.pdb` 在固化时包含：

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

第一轮只生成 A:211 与 A:224 之间的缺口。A:146→A:159 仍必须作为明确的未解析 chain
discontinuity 保留，不得压缩成普通肽键、被同时生成或计入已解析 core 的连续性判断。

目标缺口形成三个已锁定分支：

| 分支 | 插入数 | 插入位置与 residue identity |
|---|---:|---|
| shorter | 8 | A:211 后、A:224 前；`A:gap211_224.short.01` 至 `.08` |
| numbering-implied | 12 | A:211 后、A:224 前；A:212 至 A:223 |
| longer | 16 | A:211 后、A:224 前；`A:gap211_224.long.01` 至 `.16` |

synthetic identity 只表示本轮 target layout，不得伪装成原始 PDB residue 编号。每个分支
必须具有：

- 独立有效 residue layout；
- 明确的有效随机性；
- 独立 Candidate lineage；
- 准确 Node/Binding/Method identity；
- 可在 Workflow 内通过 collection-level Node 合并的输出。

Candidate Collection 合并顺序固定为 shorter-8、numbering-implied-12、longer-16；该顺序
只用于稳定展示与 sample-slot provenance，不能用于推断 pairing。

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

本轮固定使用 `esm3.generate_paired.biohub_medium@3.0.0`，不允许切换到 Biohub Open
或 local-open Binding。三个分支的参数为：

| 分支 | `effective_seed` | `num_samples` | `num_steps` | `temperature` |
|---|---:|---:|---:|---:|
| shorter-8 | 5353008 | 2 | 20 | 0.7 |
| numbering-implied-12 | 5353012 | 2 | 20 | 0.7 |
| longer-16 | 5353016 | 2 | 20 | 0.7 |

三者共同使用 `top_p=1.0`、`schedule=cosine`、`strategy=random` 和
`temperature_annealing=true`。远程 provider 不提供 seed control；`effective_seed` 固定
Result Identity 与 sample-slot provenance，但不构成远程输出可逐位复现的声明。总计应产生
六对 sequence/structure counterpart Candidates。

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

独立折叠固定使用 `folding.fold.esmfold2_remote@3.0.0`，参数为
`effective_seed=5353999`、`num_samples=1`。第二阶段对每个 Candidate 使用以下闭合判定：

- resolved core 是原始 chain A 中全部 283 个已建模标准 residues；插入 residues、HETATM
  与 A:146→A:159 的未建模位置不属于 resolved core；
- 独立折叠相对于原始 resolved core：reference-normalized TM-score `>= 0.75` 且 Cα RMSD
  `<= 3.00 Å`；
- 独立折叠相对于其 ESM-3 counterpart：TM-score `>= 0.70` 且 Cα RMSD
  `<= 3.50 Å`；
- 独立 folding Method 在 resolved-core scope 的 mean-residue pLDDT `>= 70`；新生成 loop
  的 pLDDT 单独报告，不作为第一轮硬过滤项；
- A:211–新 loop 和新 loop–A:224 两个连接处的主链 C–N 距离均在 `1.15–1.55 Å`；
- 排除共价相邻 atom 后，新 loop 与 resolved core 之间不存在小于 `2.00 Å` 的非键合
  heavy-atom 距离；
- 所有比较必须使用显式 residue correspondence 和 counterpart pairing。

这组阈值是本测试的保守一致性 gate，不是 GPCR 功能、膜稳定性或 G-protein coupling 的
普适生物学阈值。零个 Candidate 通过不等于能力失败；只要执行链和 Evidence 完整，仍应
报告为可执行但本轮没有科学筛选通过值。

## 9. Workflow 3：1PGA-75 生成结构的多 Method 共识验证

### 9.1 科学问题

给定一个已有生成结构，提取其准确序列，分别通过 ESMFold2 和 SimpleFold 的准确
Execution Binding 独立重新折叠，并判断输入结构与两种 Method 输出是否一致。

第一轮只验证一个 sequence Candidate；每个 Method 只生成一个结构；不进行 Candidate
排名。

### 9.2 原始输入事实

`examples/v2/structures/1PGA-75-gen1_0690.pdb` 在固化时包含：

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

- `folding.fold.esmfold2_remote@3.0.0`：`effective_seed=1075001`、
  `num_samples=1`；
- `folding.fold.simplefold_local@3.0.0`：`effective_seed=1075002`、
  `num_samples=1`，Binding parameter `num_steps=50`。

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

- 明确的 Structure Alignment Evidence；
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

只有满足以下条件的 Method 输出才可进入 three-way 判定：

- 输出 sequence 与输入提取 sequence 完全一致且长度为 75；
- 结构、alignment、residue/atom correspondence 和 Method provenance 完整；
- 该 Method 的 mean-residue pLDDT `>= 70`。输入 PDB 的 B-factor 不参与此门槛。

任意一对结构定义为 `close`，当且仅当该对的 reference-normalized TM-score `>= 0.80`
且 Cα RMSD `<= 2.50 Å`。分别计算 input–ESMFold2、input–SimpleFold 和
ESMFold2–SimpleFold 三条 edge。前两条以 Method 输出为 subject、输入结构为 reference；
第三条以 ESMFold2 输出为 subject、SimpleFold 输出为 reference。然后按以下规则产生结果：

- `three_way_consistent`：三条 edge 全部为 `close`；
- `method_disagreement`：仅一条 input–Method edge 为 `close`，另外两条不为 `close`；
- `input_disagreement`：仅 ESMFold2–SimpleFold edge 为 `close`；
- `all_disagree`：三条 edge 均不为 `close`；
- `insufficient_evidence`：Binding 不可用、任一 Method confidence 未达门槛、comparison
  或 provenance 不完整；
- 若出现两条 edge 为 `close`、第三条不为 `close` 的阈值非传递图样，也归入
  `insufficient_evidence`，并记录 subreason `threshold_boundary_nontransitive`，不得强行
  塞入一致或不一致类别。

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

## 11. 已锁定的实际执行顺序

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

## 13. 已锁定的跨 Workflow 执行合同

### 13.1 两阶段测试

每条 Workflow 按两个判定阶段执行：

1. **能力链路阶段**：检查 public authoring、save/relock、compile、Run admission、execution、
   raw Candidate/Observation 产生和 Evidence inspection。该阶段只判断合同和执行能力，
   不根据数值宣布 Candidate 科学合格；
2. **端到端科学判定阶段**：仅在所需 raw Observation 与 provenance 完整时，应用第 7–9 节
   已锁定的 filter 或 three-way 分类。若第一阶段阻断，第二阶段保持结构化 blocked，不能
   由执行者在 Workbench 外手工计算补齐。

两个阶段可以位于同一 Workflow 和同一 Run 中；阶段划分是判定边界，不要求重复调用
provider。`FULLY_USABLE` 要求两阶段均可由公开产品 interface 完成。零个 Candidate 通过
科学阈值本身不构成能力缺口。

### 13.2 测试 surface

- 根据 2026-07-31 正式测试开始后的用户澄清，当前 React 前端将被废弃并重写，不属于
  本轮测试范围；其行为不得登记为 finding，也不得影响 Workflow 顶层状态；
- 本轮唯一验收 surface 是 public v2 REST/WebSocket protocol：Project 创建、Project Input
  导入、Workflow authoring、Binding 选择、save/relock、compile、启动 Run、进度、Run
  Projection、Ledger、结果和 artifact inspection 均通过该 interface 执行；
- 每条 Workflow 只建立合同规定的 primary Run；不再区分 UI Run 与 diagnostic Run；
- 私有 Python 对象、临时目录、未公开数据库记录或 provider 原始日志不能替代 public
  Evidence。

### 13.3 Exact Binding 选择

当前 active Catalog generation 的 Binding version 必须逐项锁定，不能从 package version
或其他 Binding 推断：

- `proteinmpnn.constraints.local` 与
  `proteinmpnn.random_fixed_positions.local` 固定为 `3.0.0`，
  `proteinmpnn.design.local` 固定为 `4.0.0`；
- `protein_io.import_sequence.direct`、`protein_io.import_structure.direct` 与
  `protein_io.export_structure.direct` 固定为 `3.0.0`；
- `prompt_authoring.prompt_from_structure.direct` 固定为 `3.0.0`；
- `structure_transform.select_chains.direct`、
  `structure_transform.extract_backbone.direct`、
  `structure_transform.extract_sequence.direct`、
  `structure_transform.normalize_csh_parent_span.direct` 与
  `structure_transform.backbone_to_structure.direct` 固定为 `3.0.0`；
- `structure_annotation.dssp_compute.mkdssp_local` 固定为 `3.0.0`；其余三个
  `structure_annotation` direct Binding 固定为 `2.2.0`；
- `structure_comparison.align_pairwise.direct`、
  `structure_comparison.align_pairwise.fixed_reference`、两个
  `batch_tm_score` Binding 与两个 `rmsd` Binding 固定为 `2.2.0`；
- 三个 ESM3 generation Node Type 的九个 Binding 与三个 `folding.fold` Binding
  固定为 `3.0.0`；
- `esm3.represent_sequence.biohub_esmc_600m_2024_12` 与
  `folding.simplefold_confidence.simplefold_local` 固定为 `2.2.0`；
- 未列入上述不兼容切换集合的 active Binding 固定为 `2.1.0`。

上述版本矩阵只记录 active Binding identity；Node Type 与 Method 具有各自独立的 exact
identity，不能由 Binding version 推断。实际 Workflow 仍只能选择下文列出的准确 ID，
不得因为某个 Binding 已注册就把它加入这三条 Workflow。

模型或 provider-backed Node Instance 固定如下：

| Workflow | Node Type | Node Type Version | Execution Binding | Binding Version |
|---|---|---|---|---|
| 2EMO | `proteinmpnn.design` | `4.0.0` | `proteinmpnn.design.local` | `4.0.0` |
| 2EMO | `folding.fold` | `3.0.0` | `folding.fold.esmfold2_remote` | `3.0.0` |
| 2EMO | `solubility.score_sequence` | `2.1.0` | `solubility.protein_sol.local` | `2.1.0` |
| 5G53 | `esm3.generate_paired` | `3.0.0` | `esm3.generate_paired.biohub_medium` | `3.0.0` |
| 5G53 | `folding.fold` | `3.0.0` | `folding.fold.esmfold2_remote` | `3.0.0` |
| 1PGA-75 | `folding.fold` | `3.0.0` | `folding.fold.esmfold2_remote` | `3.0.0` |
| 1PGA-75 | `folding.fold` | `3.0.0` | `folding.fold.simplefold_local` | `3.0.0` |

当前 Campaign 后来增加的 fresh-local route、exact Method evidence、Observation Selector 与
Contract Lock 规则不属于本历史版本矩阵；其现行 owner 是
[`backend-verification.md`](backend-verification.md)。

所需 repository-owned Binding 也必须逐个写入 Workflow，不允许依赖“唯一可用项”的隐式
选择。本轮允许使用的准确 IDs 为：

- `protein_io.import_structure.direct`、`protein_io.export_structure.direct` 和
  `protein_io.export_sequence.direct`；
- `structure_transform.select_chains.direct` 与 `structure_transform.extract_sequence.direct`；
- `prompt_authoring.prompt_from_structure.direct`、
  `prompt_authoring.build_residue_layout.direct`、
  `prompt_authoring.edit_residue_layout.direct`、
  `prompt_authoring.map_residue_track.direct`、
  `prompt_authoring.assemble_protein_prompt.direct` 和
  `prompt_authoring.override_protein_prompt_track.direct`；
- `proteinmpnn.constraints.local`；
- `collection_ops.concat_candidates.direct`、`collection_ops.merge_scores.direct` 与
  `collection_ops.rebind_candidate_pairing.direct`；
- `structure_comparison.align_single.direct`、
  `structure_comparison.align_pairwise.fixed_reference`、
  `structure_comparison.align_pairwise.direct`、
  `structure_comparison.rmsd.fixed_reference`、
  `structure_comparison.rmsd.per_subject_counterpart`、
  `structure_comparison.tm_score.fixed_reference`、
  `structure_comparison.batch_tm_score.fixed_reference` 和
  `structure_comparison.batch_tm_score.per_subject_counterpart`；
- `selection.filter.direct`。

authoring 时必须把实际使用的每个 exact Binding ID 写入 Node Instance，并把完整 Workflow
文档作为证据保存。如果理论操作没有对应 Node Type 或 Binding，不得发明 ID；应在该位置
登记 `contract_gap` 或 `composition_gap`。

所有 `selection.filter` Node Instance 固定使用 `out_of_scope_policy=error`、
`tie_policy=candidate_id_ascending`；对应 Observation Selector 固定
`match_cardinality=exactly_one`、`missing_policy=error`。selector 必须同时固定 Candidate
input、Score Collection input、source partition、Metric、Method 和 Observation Context；
不得只用显示名称或 Metric ID 匹配分数。

### 13.4 Randomness、Run 和重试

- 每条 Workflow 只有一个 primary Run；本轮不以多次采样估计统计稳定性；
- 所有 stochastic Node Instance 使用第 7–9 节锁定的 `effective_seed`；
- `effective_seed` 固定 Result Identity 和有效随机性 provenance，但只有 Binding 明确声明
  seed control 时才支持相应复现主张；
- 禁止自动重试。若首次结果是疑似瞬时 `execution_gap` 或 `OPAQUE_FAILURE`，允许至多一个
  confirmation Run；它必须保持相同 Workflow revision、FrozenCatalog、Binding 和参数，
  使用新 Run ID，并与首次 Evidence 并列保存；
- confirmation Run 的成功不得覆盖首次失败，也不得被描述为相同远程随机输出的复现。

### 13.5 当前环境与执行预算

测试使用启动时已有的 checkout、Environment Configuration、credential handle、provider
安装和模型资产。不得为测试执行安装依赖、下载或替换模型、修改 key、补环境变量或改变
device。缺失项分别记录为 `availability_gap` 或 `readiness_gap`。

单次等待上限固定为：

| seam | 最长等待时间 |
|---|---:|
| public API authoring、compile、admission 或 repository-owned Node | 2 分钟 |
| ProteinMPNN Operation Attempt | 15 分钟 |
| Biohub ESM-3 Engine Invocation | 15 分钟 |
| Biohub ESMFold2 Engine Invocation | 10 分钟 |
| SimpleFold local Engine Invocation | 120 分钟 |

primary Run 总时限为：1PGA-75 `150 分钟`、2EMO `120 分钟`、5G53 `180 分钟`。远程请求
预算为：1PGA-75 至多 1 次 ESMFold2；2EMO 至多 8 次 ESMFold2；5G53 至多 12 次
ESM-3 generation Engine Invocations（六个 paired Candidate 各 sequence/structure 一次）和
6 次 ESMFold2。confirmation Run 使用一份独立、相同上限的预算。

到达上限时必须从公开 interface 请求取消并保存 terminal evidence。若取消后无法获得准确
terminal outcome，应记录 `OPAQUE_FAILURE` 和相应 `evidence_gap`，不能继续无界等待。

### 13.6 缺口与 Evidence 落盘位置

- 首轮人类可读报告固定为
  `docs/workflow-usability-debug-runs/2026-07-31-initial-pass.md`；
- 原始 Run Evidence Ledger、manifest、Candidate 与 artifact 保持在所属 Project/Run 的
  durable storage 中，报告通过 identity 和 Run ID 引用，不复制改写；
- 公开 protocol 响应副本写入
  `.local/verification-results/workflow-usability-debug/2026-07-31/<workflow-id>/`，该目录不得提交；
- 报告按第 12 节逐项登记 finding，并明确 primary Run 与 diagnostic/confirmation Run；
- credential、key、未脱敏 provider payload 和本地私有路径不得进入提交的报告。

### 13.7 闭合结论

三个样例的科学范围、固定与可设计位置、生成数量、随机性、长度分支、阈值、Binding、
surface、预算、重试规则和记录位置均已锁定。执行者不得再补充临时科学参数；可以开始
只读 preflight，并在 preflight 记录完成后按第 11 节启动正式测试。
