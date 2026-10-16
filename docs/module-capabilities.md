# 模块能力与工具翻译

功能职责以[当前决策](documentation-governance-decisions.md#功能模块设计)为准。本文提供已接入能力的源码入口，以及仍适用的工具翻译约定；源码现状不代表目标行为已经实现。载体、模块与公共接口边界见[架构](architecture.md)，运行行为见[执行规则](execution.md)。

## 功能职责与现有代码包

模块按用户任务组织，可以提供多个节点、编辑器和查看器。同一工具可以服务多个功能模块；下表不是未来插件清单或强制拆包方案。

| 已确认的功能职责 | 当前相关代码 | 已存在的能力及边界 |
|---|---|---|
| 蛋白数据导入与导出 | [`protein_io`](../modules/protein_io/definitions/) | 单条或多条序列、PDB/mmCIF 结构导入及序列/结构导出。单条 FASTA 入口拒绝多记录并提示批量导入；结构保留原格式输出。支持格式转换，单文件多构象可明确选择一个或按选择顺序拆分为单构象候选；原始输入保留；候选结果支持非蛋白组分的全原子显示、明确选择及 PDB/mmCIF 导出。 |
| 序列与设计条件编辑 | [`prompt_authoring`](../modules/prompt_authoring/definitions/)、[`residue_data`](../modules/residue_data/definitions/) | Prompt 组合、拆解与编辑，带残基身份的轨道及序列物化。随机插入和局部采用按[Prompt 编辑要求](prompt-editing.md)落实，内部位置映射由模块处理。 |
| 序列生成与设计 | [`esm3`](../modules/esm3/definitions/)、[`proteinmpnn`](../modules/proteinmpnn/definitions/) | ESM-3 的序列、结构轨道和配对生成；ProteinMPNN 按骨架与约束生成序列，并保留真实生成父结构和逐次调用 seed。 |
| 结构预测 | [`folding`](../modules/folding/definitions/) | ESMFold2 本地/远程与 SimpleFold 折叠，保留对应结构与预测置信度。 |
| 结构编辑与处理 | [`structure_transform`](../modules/structure_transform/definitions/) | 链选择、残基轴解析、骨架和序列提取、明确的区域片段提取，以及 CSH 归一化。比较的区域选择不调用提取操作。 |
| 结构比较 | [`structure_comparison`](../modules/structure_comparison/definitions/) | 两侧独立选择链上不连续残基，自动对应与对齐，RMSD/TM-score 投影；另有三方一致性分类与插入环分析。 |
| 候选评价 | [`solubility`](../modules/solubility/definitions/)、[`folding`](../modules/folding/definitions/)、[`proteinmpnn`](../modules/proteinmpnn/definitions/)、[`structure_annotation`](../modules/structure_annotation/definitions/) | SoluProt/Protein-Sol、已有结构 SimpleFold confidence、ProteinMPNN 评分、DSSP 注释及二级结构一致性。ProteinMPNN 评价接受独立序列与所选骨架，以 pairwise 结果记录评价关系，不改写生成来源。 |
| 指标分析 | [`structure_prediction`](../modules/structure_prediction/definitions/)、[`structure_comparison`](../modules/structure_comparison/definitions/) | 置信度物化及已有逐残基数值的区域均值，保留原指标、主体、方法、上下文和有效数量；不重新预测。 |
| 候选筛选与排序 | [`selection`](../modules/selection/definitions/)、[`collection_ops`](../modules/collection_ops/definitions/) | 阈值、排序、top-k、加权排序、Pareto、多样性、手动选择及集合/关系组合。作用范围由用户构建流程表达，不固定为整批或每骨架二选一。 |

ESMC 序列表征位于 `esm3.represent_sequence`：`outputs` 可选择 embedding、logits 或 both（默认）。保存 Provider 的 1152 维整序列 mean embedding，以及去除 CLS/EOS 行后与输入残基顺序对应的 `L×64` 实际 logits；未请求值为 null。保留全部模型类别列，列索引为固定 SDK 的模型类别索引，不将其称为概率。模块查看器逐位置显示数值，同名 Port 可交给下游模块；不增加 hidden states、SAE 或新分析算法。

### ProteinMPNN 设计与评价

设计与评价分别使用独立请求。设计保留骨架父结构、约束、完整链/片段映射、每个父结构的有效 seed 与采样顺序；评价接收一个完整序列和用户选择的一个骨架，返回 `fixed_reference` / `provider_masked_mean` 的 pairwise 标量，明确记录序列 subject 与骨架 reference。评价不要求二者存在生成父子关系。

没有残基身份的独立序列按完整骨架残基轴的位置顺序对应，长度必须相同；已有显式身份时默认必须与所选轴一致；选择另一骨架时，可通过 `sequence_correspondence` 明确将每个原序列位置对应到一个骨架残基，必须完整且一一对应，不猜测或静默重排。对应关系随本次评价 Context 保存，原 Candidate 的内容与生成来源不变。Adapter 将轴的每个共价片段映射为工具安全链名和连续编号，保留原链和残基身份对应。PDB 或 mmCIF 的来源格式不改变这一工具输入合同。

设计开放 seed、数量、温度、骨架噪声、固定/可设计位置、链选择、全局和逐位置氨基酸禁止、全局/逐位置 logit 偏置、绑定残基组及成员权重、PSSM；评价开放 seed、骨架噪声和完整位置对应。约束位置使用所连骨架的残基选项，不由用户填写内部身份。

PSSM 每行按 `ACDEFGHIKLMNPQRSTVWY` 顺序提供 20 个归一化概率和 20 个 log-odds。启用概率混合时，实际混合权重为 `pssm_multi × coefficient`；启用 log-odds 时按严格大于 `pssm_threshold` 的掩码处理，保留官方 `0.001` 概率项后重新归一化，因此这是软筛选。全局禁止项作用于模型 logits，逐位置禁止项在 PSSM 后应用；不将二者伪称相同顺序的操作。

绑定组只生成一个共同氨基酸。固定上游将成员加权 logits 求和后除以组大小，并仅从组内最后一个成员读取位置禁止项、偏置和 PSSM。为使用户所选条件全部生效，组内所有成员的这三类设置必须相同；不一致会明确拒绝。`tied_weights` 可分别配置成员权重，未指定时为 1，不按权重和重新归一化。

评分默认 seed 42 是本模块的明确可重复默认值，零也作为精确 seed；噪声默认 0 与固定上游一致。数量、温度、噪声不施加工具无依据的额外上限。默认模型仍为 `v_48_020`，本次不新增计算模式。当前真实 CPU 小规模调用覆盖逐位置禁止、PSSM 概率混合、全局偏置/绑定组、独立序列评价与另一骨架的明确对应；新公共 API 测试另覆盖不一致绑定条件拒绝及评价对应保留。未新增模型或计算模式。

### ProteinMPNN 输出范围

现有评分实现公开的是整序列标量，虽然注册中已存在逐残基 NLL 指标定义，尚无对应公开输出。定义存在不等于功能已实现，也不自动确认逐残基输出是重做的必需功能。

固定上游采样可返回逐位置概率等附带值，当前集成未完整保留。采样时的分布与按给定序列另做 forward 后得到的 NLL 不是同一结果，不能互相冒充。实现按已确认功能正确传参和接回所需结果；尚未确认保留哪些额外采样字段，不扩建指标或证据体系。源码入口见[现有实现](../modules/proteinmpnn/implementation.py)、[Provider 翻译](../modules/proteinmpnn/provider_runtime.py)及[上游采样](../repositories/ProteinMPNN/protein_mpnn_utils.py)。

## 跨模块数据约定

序列、结构和指标保留正确对象及残基对应；评价关系与生成来源分别记录。区域表达能指向链上的不连续残基区间，不要求未来项目用户维护内部 ID 或映射。工具自然产生且属于所需功能的分数随结果保留，不能因模块拆分而丢弃。

当前 `ProteinPrompt` 包含一个 `ResidueLayout`，序列与坐标逐位置对齐；二级结构和 SASA 可整轨 absent。`None` 整轨与 present 但全部位置缺失是不同状态，不能静默合并。Prompt 是设计条件表达，不要求其他工具都采用它作为统一输入。

当前二级结构实际状态为 `H/B/E/G/I/T/S/C`；Prompt 的 `-` 与 DSSP 的 `P` 转为 `C`，DSSP `_` 转为逐残基缺失 `None`。SASA 为绝对面积，单位 Å²，不是归一化比例或离散 token 编号。对应的[数据类型](../datatypes/)与[模块声明](../modules/residue_data/package.py)是现有表示入口。

### 当前序列输入边界

以下描述当前源码的接纳范围，不把模块限制升级为所有工具的官方限制，也不要求载体统一采用某个工具的字母表。[输入限制核实](tool-input-restrictions.md)区分官方依据、项目维护 Provider 契约与仍未决的路线边界。

| 当前边界 | 接纳范围 | 源码 |
|---|---|---|
| 完整 `ProteinSequence` | 非空大写 `ACDEFGHIKLMNPQRSTVWYBXZJUO`；不包含空格、`_` 或 `-`。 | [序列类型](../datatypes/sequence.py) |
| Prompt 的逐残基序列条件 | 同一字母表，另以 `None` 表示未指定位置；`_` 是 Provider 编码，不是内部残基符号。 | [残基元素](../modules/residue_data/elements.py)、[Prompt 准入](../modules/prompt_authoring/prompts.py) |
| ESM-3 实际 SDK 条件投影 | `ACDEFGHIKLMNPQRSTVWYXBZUO`，未指定位置转 `_`；当前不能表示 `J`。 | [ESM-3 Adapter](../modules/esm3/adapter.py) |
| 现有 folding 输入 | 大写标准20种残基，且是单链。 | [折叠输入](../modules/folding/_output_construction.py) |
| 现有 SoluProt、Protein-Sol 输入 | 大写标准20种残基，长度另按对应路线要求；不静默删除未知符号。独立 SoluProt CLI 的不同默认处理见其 README。 | [可溶性入口](../modules/solubility/implementation.py) |
| ProteinMPNN 序列/约束 | 独立序列评分接受大写标准20种残基及官方未知符号 `X`；设计参考序列与约束仍为标准20种。完整序列默认按骨架顺序对应；显式身份不同时必须指定完整位置对应，约束按原始残基身份寻址。 | [当前序列检查](../modules/proteinmpnn/implementation.py)、[约束](../modules/proteinmpnn/domain.py) |

结构预测置信度与结构内容、预测残基轴及产生它的计算保持对应。PAE 单位为 Å，pTM 为无量纲；pLDDT 原生标度由相应 Adapter 转换，不能把百分数与单位区间混用。缺失 PAE 不补零。现有均值的缺值及范围规则应按具体指标说明，不能用一个简写抹平所有操作。

## ESMFold2 推理参数

ESMFold2 的采样步数、循环、LM dropout/mask、MSA depth/column mask 由所选 Binding 声明并传给对应官方接口；远程范围不用于限制本地路线。nullable 数值保留为数值或 null，不转为字符串。MSA 参数只影响带 MSA 的输入，不新增输入模式；本地标准模型不消费的 sampler overrides 不作为可用控制。路线默认值及适用范围见[参数审查](tool-parameter-exposure-audit.md#esmfold2-当前参数接入与适用范围)。

## 不连续区域：比较、提取与已有指标统计

模块使用同一位置表达：`{chain_id, residue_number, insertion_code}`，对应原始链、作者残基编号和独立插入码。编辑器可逐项选择不连续位置，不要求填写内部身份或对应表。空列表表示完整轴；未知位置和重复位置失败，实际顺序沿用输入残基轴。两侧区域独立，比较的自动对应仍由已选算法负责。

- `structure_comparison.align_pairs` 的 `subject_region` / `reference_region` 只限制进入对齐工具的位置；原结构、原轴及 Candidate 保持不变。序列优先 affine/SVD 与现有单片段 TM-align 路线均使用所选位置；TM-align 原有单片段适用边界保留。RMSD 采用对应 CA，TM-score 的归一化长度为选定参考区域长度，coverage 为对应 CA 数除以两侧所选区域长度的最大值。对齐结果保留两侧完整引用、原轴摘要、所选身份、自动对应和实际 Method；已有结果未记录区域时只显示“未记录”，不补造。
- `structure_transform.extract_region` 是明确改变输出内容的操作，为每个输入建立一个新片段 Candidate，父来源指向原 Candidate。保留所选原子坐标、链、作者编号和插入码及适用修饰声明；SEQRES/entity_poly_seq 只声明所选片段的实际组分，以便后续解释 MSE 等修饰残基；mmCIF 为派生片段建立独立 entity，聚合物 num 引用保留的 label_seq_id；作者与 label 链、编号、插入码及修饰位置引用不变。PDB 中删去位置形成的断点写为 TER；mmCIF 保留选中原子及片段聚合物声明，不保留组装或指向已排除位置的连接。原候选和保存原文不改写。该节点只提取已解释的蛋白残基，不替代其他组分选择操作。
- `structure_comparison.region_statistics` 接收现有 Score Collection，按 `metric_id` 选择数值型逐残基观察，每个主体/方法/上下文分别统计。输出均值沿用原指标单位。`exclude_null` 排除所选缺值，`require_all` 在任一所选位置缺值时失败；全缺值均失败。报告含 `selected_count` 和非空的 `valid_count`，完整保留来源 Metric、Method、Context、partition、集合摘要、主体和残基轴。没有 Provider 重算，也不改变全轴 pLDDT 均值或专用环方法原规则。

统计输出是 `structure_comparison.region_statistics` 名义值，可交给接受该类型的下游模块；已用外部下游模块验证完整传递。它不是 `score.collection`，不能直接连接现有 Selection；不自动发明新 Metric 或区域筛选语义。模块查看器显示区域、均值、数量和来源，保存结果可重开。

结构解析保持已有身份规则，不改写保存的来源标签，例如作者编号 `A42` 保持 `A:A42`。比较/提取在结构中核对独立的 `(chain, author number, insertion)` 后才选择轴位置。已有身份表示仍可能把作者编号 `12A`、无插入码与数字 `12`、插入码 `A` 都表示为 `A:12A`；两者同时存在的结构轴明确失败，不猜对应，也不根据是否碰撞更换身份。修订身份表示必须先解决既有 Prompt 来源重开的保全，当前没有引入新编码、旧解析器或别名。统计使用原观察已保存的残基轴，不重新推断作者编号。

## ESM-3 生成参数

单轨道生成的采样设置属于所选 Binding；配对生成使用独立 `sequence_*` 与 `structure_*` 设置。两次调用分别保留实际请求参数及 SDK 有效步数，包含禁止采样 token ID 与坐标条件开关。仅本地 Binding 提供有效 seed，Biohub 随机性由 Provider 控制。当前配置及路线范围见[参数审查](tool-parameter-exposure-audit.md#esm3-当前参数接入与适用范围)。

生成失败后可在运行结果中主动继续原批次。已完成的序列、结构、重建结构及置信度保留；联合生成在序列完成而结构失败时只继续结构请求。续算沿用原 Commit 与结果身份，改变输入或参数应启动新计算。

## ESM-3 条件翻译

以下规则由 [`modules/esm3/adapter.py`](../modules/esm3/adapter.py)实现，属于 ESM-3 Adapter 的工具输入处理，不是载体或所有模块的数据限制。

### 序列与轨道

- 序列缺失位置编码为 `_`；已有符号按固定 SDK 可表示字母表传递，不能静默替换为其他残基。当前 Adapter 支持 `ACDEFGHIKLMNPQRSTVWYXBZUO`；具体公开输入边界以对应操作声明为准，不将这套字母表套用于 SoluProt 等工具。
- 二级结构整轨 absent 传 `None`；已存在轨道的缺失位置传 `_`。
- SASA 整轨 absent 传 `None`；已存在轨道按位置传绝对 Å² 浮点值或缺失值。SDK 的 [SASA tokenizer](../repositories/esm/esm/tokenization/sasa_tokenizer.py)负责按其边界离散化；不把 bucket 序号当作绝对面积传入，通用数据不依赖这些 bucket。
- 当前 ESM-3 Adapter 不支持保持多链对齐条件的 SDK 编码；该限制属于此工具接入，不限制通用画布或结构值保存多链内容。

### 坐标与功能注释

通用坐标按原子名称保存，不能先按 atom37 过滤整个 Prompt。Adapter 仅将 ESM-3 支持的原子复制到 `[L, 37, 3]` float32 tensor，缺失槽位为 NaN。非 atom37 原子在该次工具投影中忽略，仍保留在原始通用数据中；不能因它们存在而报错。没有任何支持原子时，该工具视图的 coordinates 为 `None`。

功能注释绑定 Prompt 的残基身份。Adapter 根据同一 layout 将起止身份转换成官方 `FunctionAnnotation` 的 **1-based、包含端点**位置，保留 label 和已接纳顺序；空注释在 SDK 输入中为 `None`。位置或链的转换不通过猜测 PDB 编号完成。

当前注释可交叠或相互包含；完全相同的 label 与起止残基三元组不得重复。编辑入口处理规范顺序；不因重叠而自动裁剪、合并或去重。Provider 的 InterPro 版本与标签要求见[官方 encode 快照](biohub-api-reference/v1/endpoints/encode.md)。

### 条件投影与本地 seed

一个不可变条件投影同时生成实际 SDK 输入和 functional-input digest；两种编码形式保持各自精度和缺值语义。digest 使用 float32 坐标位模式、float64 SASA 位模式及空注释 `[]`；SDK 输入使用新建的可变对象、float32 坐标 tensor、Python float SASA 及空注释 `None`。digest 只覆盖实际进入工具的 atom37 坐标投影。

本地 call seed 是以下 ASCII 内容的 SHA-256 前六字节按 big-endian 解释的整数；缺少 base seed 时不派生 seed：

```text
protein-workbench-esm3-call-seed/v2:{base_seed}:{functional_digest}:{sample_index}:{track}
```

配对生成的结构子调用仅以已生成序列替换投影中的 sequence，其他条件保持原值，再据实际输入计算对应 digest 与 seed。远程 Biohub 不声称采用此 seed；其随机性记录为 Provider 控制。该说明保留现有正确传参和随机流知识，不建立额外证据系统。

## 尚未对齐的实现

[参数开放审查](tool-parameter-exposure-audit.md)记录 ESM-3、ESMFold2、SimpleFold 等现有固定参数与范围差异。[治理问题清单](2026-10-15-documentation-governance-issues.md)记录输入、模块接入、区域表达和其他实现缺口。文档中的目标要求不构成已完成声明；未确认的工具模式、逐残基 ProteinMPNN 输出或所有内部张量不自动成为开发范围。

### SimpleFold 折叠采样参数

折叠 Binding 提供 `num_steps`（正整数，默认 500）与 `tau`（非负数，默认 0.1），无额外上限。默认值来自固定官方 CLI；界面与保存使用同一 Binding 声明，调用将用户值传至官方 wrapper。已有结构的独立 confidence 不重新采样，不提供这两个参数。本地模型执行排除，仅进行不加载模型的契约验证。

### SimpleFold 运行失败与主动续算

SimpleFold 每个输入序列对应一次官方推理请求，该请求一次产生所选数量的样本。[固定上游调用](../repositories/ml-simplefold/src/simplefold/wrapper.py)没有专用失败返回；当前只将已加载模型的 `run_inference` 抛出的 [PyTorch `torch.cuda.OutOfMemoryError`](https://docs.pytorch.org/docs/2.14/generated/torch.cuda.OutOfMemoryError.html) 作为明确资源失败。资产准入、输入准备、模型加载和输出转换保持各自失败边界；普通 `RuntimeError`、`ValueError` 不转换，也不通过错误文本猜测其他设备的内存失败。

这类推理失败停止尚未开始的序列请求。此前完整请求的结构及置信度随失败节点持久保存，供重开查看和导出；下游仍被阻断。用户通过公共“继续批次”入口继续原输入与参数，跳过完成的序列请求，保留原候选身份与有效 seed，仅重新尝试失败及未开始请求。首请求失败也能继续；不添加自动重试，不读取失败请求的残缺样本。

当前覆盖为不加载模型的受控官方调用边界，以及测试专用模块装配生产 Operation 的公共 Run 行为；未启动 SimpleFold 本地模型，未诱发真实设备内存耗尽，不据此宣称真实模型或其他设备失败处理已经验证。
