# 已有工具功能的参数开放审查

## 依据与范围

依据[当前决策 Q26](documentation-governance-decisions.md)：已提供功能中，官方支持、适用且影响结果的输入与参数允许用户配置，默认值和限制有明确依据。科学性以正确传参为尺度，不新增指标或证据体系。

本报告排除 ProteinMPNN。核对 ESM3/ESMC、ESMFold2、SimpleFold、SoluProt、Protein-Sol、DSSP、结构比较及通用参数界面。依据本地固定上游、仓库保存的官方 API 快照及实现；不声称全部当前线上接口已复验；各实现调整的验证状态分别说明。

新增工具模式、部署路径/设备、满足当前固定输出所必需的开关，不因存在常量就自动成为缺陷。能通过 Binding 选择的功能不算隐藏。部署入口与已接入的应用内模块设置见[Provider 配置](provider-configuration.md)；凭据、路径和服务地址与计算参数分开。

下文的“固定”描述当前实现，不将其升级为目标要求。[Biohub 接入说明](biohub-api-reference/product-contract-supplement.md)采用当前 Q26，不以 Method identity 为由禁止开放适用参数。文档已经按决定对齐，不表示所列实现差异已修正。

## 参数范围与默认值需要对齐的事项

| 接入 | 差异 | 判断 |
|---|---|---|
| ESM3及fold样本数 | 项目上限100。 | 这是批量编排限制，不是单次官方请求参数。依据未明确，不声称工具无限支持。 |

限制位置：[ESM3 序列生成](../modules/esm3/definitions/generate_sequence.yaml)、[结构生成](../modules/esm3/definitions/generate_structure.yaml)、[联合生成](../modules/esm3/definitions/generate_paired.yaml)与[折叠节点](../modules/folding/definitions/fold.yaml)的样本数参数声明。上游单次请求接口不提供该项目批量上限的依据。

## 当前参数接入与适用范围

### SimpleFold 折叠

折叠 Binding 公开正整数 `num_steps`（默认 500，无额外上限）与非负数 `tau`（默认 0.1，无额外上限），经 Operation、Adapter 原样传到官方 `InferenceWrapper`。默认值依据[固定上游 CLI](../repositories/ml-simplefold/src/simplefold/cli.py)，[官方示例](../repositories/ml-simplefold/README.md)使用 500 步和 tau 0.01；所调用 Torch sampler 对 tau 开平方，因此不接受负数。独立 confidence 操作不采样，不新增这两个参数。界面根据 Binding 声明编辑和保存计算参数，保留已保存的显式值。

### ESMFold2 当前参数接入与适用范围

[Binding 声明](../modules/folding/package.py)向两条路线开放 `num_sampling_steps`、`num_loops`、`lm_dropout`、`lm_mask_pct`、`msa_max_depth`、`msa_column_mask_rate`；Operation 将已准入配置交给各 Adapter，分别传到官方 `FoldingConfig` 和本地 builder。

| 参数 | Biohub fast | 当前本地标准模型 |
|---|---|---|
| 采样步数 | 1–100，默认 100 | 正整数，无远程上限，默认 200 来自所调用 builder |
| 循环次数 | 0–20，默认 20 | 非负整数，无远程上限，默认 20 |
| LM dropout | `[0,1]`，默认 0.3 | `[0,1]` 或 null；默认 0.3，null 或 0 保留 checkpoint 配置 |
| LM mask | `[0,1]`，默认 0.1（fast 模型） | `[0,1]` 或 null；默认 null 使用 checkpoint 配置 |
| MSA depth | 1–16384 或 null，默认 1024 | 正整数或 null，默认 1024；null 不进行行抽样 |
| MSA column mask | `[0,1]`，默认 0.1 | `[0,1]`，默认 0.1 |

MSA 设置只影响带 MSA 的输入，不因此新增 MSA 输入模式。`include_pae=true` 保持既定置信度输出，其他未提供的输出开关不新增；每个独立请求仍只生成一个结果，由 `num_samples` 编排批次。

依据：[官方远程快照](biohub-api-reference/v1/endpoints/fold.md)、[SDK 配置](../repositories/esm/esm/sdk/api.py)、[本地 builder](../repositories/esm/esm/models/esmfold2/processor.py)。本地模型由 [Adapter](../modules/folding/esmfold2_local.py)选择标准 `ESMFold2Model`，其版本固定在 [pyproject.toml](../pyproject.toml)。已核对该固定安装源码：标准模型 `forward` 不消费 builder 转发的 `noise_scale`、`step_scale`、`max_inference_sigma`、`early_exit`，因此不展示这些无效控制，也不切换到实验模型。

当前已接入参数和 numeric/null 编辑；调用方须保留所选路线的参数语义。

### ESM3 当前参数接入与适用范围

[Binding 声明](../modules/esm3/package.py)拥有路线采样参数：`num_steps`、`temperature`、`top_p`、`schedule`、`strategy`、`temperature_annealing`、`invalid_ids` 与 `condition_on_coordinates_only`。配对生成分别使用 `sequence_*`、`structure_*`，传给两次调用，不再共用一套设置；单轨道使用不带前缀的字段。`num_samples` 仍为节点批次参数。

Biohub 步数为 1–100、`top_p` 为 `(0,1]`；本地 SDK 步数为正整数且保留 SDK 对实际采样位置的步数处理，`top_p` 为 `[0,1]`。两条路线温度均不设无依据上限，显式默认 1 来自固定 SDK `GenerationConfig`，并非省略 HTTP 字段后采用 API 默认 0.5。`invalid_ids` 默认空列表；坐标条件默认 true；均实际传给 SDK。本地 seed 只在本地 Binding 声明，Biohub 不再显示无效 seed，也不虚构服务端控制。

依据：[固定 SDK 参数](../repositories/esm/esm/sdk/api.py)、[本地 nucleus sampling](../repositories/esm/esm/utils/sampling.py)、[官方远程快照](biohub-api-reference/v1/endpoints/generate.md)。`only_compute_backbone_rmsd` 仅影响当前不保留的 cRMSD，不新增对应输出或模式。

当前已调整声明、Adapter 与调用方。

### SoluProt 非标准字符处理

项目始终传 `--check_unknown`，且调用前拒绝非标准残基；项目自有 Provider CLI 将其定义为可选且默认 false。关闭检查时 Provider 会删除非标准字符，改变评价对象。保持检查符合正确传递用户输入的要求，不把静默删除字符作为应直接开放的普通计算参数。实际 Provider 接受标准20种、最短20残基，依据与版本边界见[输入限制](tool-input-restrictions.md#有依据的约束与对齐)。

依据：[固定参数](../modules/solubility/soluprot.py#L238)、[前置检查](../modules/solubility/implementation.py#L53)、[自有 CLI](../repositories/soluprot-next/soluprot_core/cli.py#L65)、[过滤行为](../repositories/soluprot-next/soluprot_core/features.py#L259)。这里的 CLI 是项目自有代码，不当作第三方官方规范。

### DSSP 注释

固定版本官方 CLI 提供 `min-pp-stretch`，当前调用未开放；但项目将 `P` 翻译成 `C`，它对当前公开轨道的影响需确认，暂不列为确定结果变化。[项目调用](../modules/structure_annotation/adapter.py#L294)、[标签转换](../modules/structure_annotation/adapter.py#L34)、[官方 v4.6.1 CLI](https://github.com/PDB-REDO/dssp/blob/v4.6.1/src/mkdssp.cpp#L63-L69)。

### Protein-Sol

当前调用官方 October 2017 包的 `multiple_prediction_wrapper_export.sh`，入口接收 FASTA 文件路径。官方包的 `fasta_seq_reformat_export.pl` 在两个记录出口均要求过滤后至少21个标准残基；并会删掉非标准字符。Workbench 在调用前拒绝短序列及非标准字符，避免静默改变评价对象。这一长度依据来自实际入口判断，不是由滑动窗口推测。

[官方软件入口](https://www.protein-sol.manchester.ac.uk/software)提供源码；已核对的包、parser 摘要及与本机部署的一致性见[输入限制依据](tool-input-restrictions.md#有依据的约束与对齐)。[Adapter](../modules/solubility/protein_sol.py)传入文件路径并调用该 wrapper，[Operation](../modules/solubility/implementation.py)在进入工具前检查输入。未发现该 wrapper 声明其他用户计算参数，不据此推断其他 Protein-Sol 产品或版本的接口。

## 不应误判为本原则冲突的事项

- **SoluProt full/no-TM**：已通过 Method/Binding 选择，不能因为节点参数为空就认定用户无法配置。
- **SimpleFold 的步数控件**：界面按 Binding 声明编辑，当前无 50 步上限。
- **SimpleFold 现有结构 confidence**：直接执行 confidence head，不重新采样，不应给它凭空添加折叠 steps/tau。
- **DSSP accessibility 恒开启**：当前操作承诺输出 SASA，开启该计算是履行既定输出，不直接作为应新增关闭选项的证据。
- **ESMC 表征其他输出模式**：hidden states、层选择、SAE 等不自动纳入。embedding 和实际 logits 通过 outputs 选择请求和持久化；未请求值为 null，实际 logits 按输入残基顺序去除 CLS/EOS 行。
- **模型路线和设备路径**：不因为模型固定就自动要求新增全部模型；部署配置与节点计算参数的开放范围分开。
- **自写结构对齐设置**：BLOSUM62、gap 等常量属于项目自定算法配置，不是外部工具官方参数缺失。可另审其用户配置需求，但不冒充已接入工具的参数遗漏。

## 前端检查结论

未发现前端额外隐藏或覆盖 ESM3、folding、solubility 已公开声明的普通参数。界面逐项读取 Node 和 Binding 参数，折叠面板展开后可编辑；默认示例卡只提供少数快捷项，不等于其他参数不可用。

因此主要改动位置是后端的参数声明、适配器传参及必要输入表示，再由界面展示这些配置；不能仅增加控件却仍传固定值。

证据：[参数读取](../webui/src/workflow-authoring.ts#L129)、[参数渲染](../webui/src/WorkflowParameters.tsx#L124)、[参数更新](../webui/src/App.tsx#L350)。

## 结论

ESM3 生成条件及采样参数、ESMFold2 推理参数、SimpleFold 的 tau 和步数范围已接入。SoluProt 与 Protein-Sol 保留已有输入对象，拒绝工具会删除的字符；Protein-Sol 最短21已有官方入口依据。DSSP 的公开轨道影响、折叠路线的特殊字符范围等未决项继续核实，不升级为未经证实的缺陷。本报告没有决定这些模块需要全部重写，也没有新增计算模式。
