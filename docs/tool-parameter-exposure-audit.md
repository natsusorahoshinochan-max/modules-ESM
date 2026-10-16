# 已有工具功能的参数开放审查

## 依据与范围

依据[当前决策 Q26](documentation-governance-decisions.md)：已提供功能中，官方支持、适用且影响结果的输入与参数允许用户配置，默认值和限制有明确依据。科学性以正确传参为尺度，不新增指标或证据体系。

本报告排除 ProteinMPNN。核对 ESM3/ESMC、ESMFold2、SimpleFold、SoluProt、Protein-Sol、DSSP、结构比较及通用参数界面。依据本地固定上游、仓库保存的官方 API 快照及实现；不声称全部当前线上接口已复验；各实现调整的验证状态分别说明。

新增工具模式、部署路径/设备、满足当前固定输出所必需的开关，不因存在常量就自动成为缺陷。能通过 Binding 选择的功能不算隐藏。部署入口与 Q47 尚未实现的应用内设置见[Provider 配置](provider-configuration.md)。

下文的“固定”描述当前实现，不将其升级为目标要求。[Biohub 接入说明](biohub-api-reference/product-contract-supplement.md)采用当前 Q26，不以 Method identity 为由禁止开放适用参数。文档已经按决定对齐，不表示所列实现差异已修正。

## 明确不符合参数开放原则的实现

| 接入 | 当前情况 | 对用户的影响 | 依据 |
|---|---|---|---|
| ESMFold2 远程 | 固定采样步数100、循环次数20、`lm_dropout=.3`、`lm_mask_pct=.1`、`msa_max_depth=1024`、`msa_column_mask_rate=.1`。 | 用户只能配置 seed/样本数等公开字段，无法调整这些已提供折叠功能的推理参数。 | [固定参数](../modules/folding/esmfold2_remote.py#L77)、[公开节点](../modules/folding/definitions/fold.yaml#L22)、[SDK 参数](../repositories/esm/esm/sdk/api.py#L397) |
| ESMFold2 本地 | 同类推理参数固定。 | 本地折叠同样缺少用户配置入口。 | [本地调用](../modules/folding/esmfold2_local.py#L125) |
| SimpleFold 折叠 | `tau=.1` 固定，官方 CLI 提供配置。 | 用户无法选择官方示例中使用的 `.01` 等值；`.1` 有官方默认依据，问题是不可修改。 | [项目调用](../modules/folding/simplefold_runtime.py#L260)、[官方 CLI](../repositories/ml-simplefold/src/simplefold/cli.py#L23)、[官方示例](../repositories/ml-simplefold/README.md#L51) |
| SimpleFold 折叠 | 步数已开放，但限定1–50。 | 官方 CLI 默认及 README 示例使用的500步在项目中不可设置；未找到50上限的依据。 | [Binding 限制](../modules/folding/package.py#L424)、[官方 CLI](../repositories/ml-simplefold/src/simplefold/cli.py#L22) |

以上是已提供操作的参数问题，不要求接入新的计算模式。参数之间的适用条件仍须按对应接口处理，不将“开放”理解为允许任意无效组合。

## 参数范围与默认值需要对齐的事项

| 接入 | 差异 | 判断 |
|---|---|---|
| ESMFold2 本地步数默认 | 项目100；本地builder默认200；远程SDK默认100。 | 默认值依据待核，不能仅凭差异认定错误；用户应能配置的结论不变。 |
| ESM3及fold样本数 | 项目上限100。 | 这是批量编排限制，不是单次官方请求参数。依据未明确，不声称工具无限支持。 |

证据：[本地 ESMFold2 入口](../repositories/esm/esm/models/esmfold2/processor.py#L327)。

## 有固定行为，但需进一步核实适用范围

### ESMFold2 本地其他推理参数

所调用的官方 builder 还接受 `noise_scale`、`step_scale`、`max_inference_sigma`、`early_exit`，当前未开放，沿用默认。需要按该调用路线核对参数的实际作用和适用条件，再给出配置；不能无条件照搬全部参数。[官方入口](../repositories/esm/esm/models/esmfold2/processor.py#L327)。

### ESM3 当前参数接入与待验收范围

[Binding 声明](../modules/esm3/package.py)拥有路线采样参数：`num_steps`、`temperature`、`top_p`、`schedule`、`strategy`、`temperature_annealing`、`invalid_ids` 与 `condition_on_coordinates_only`。配对生成分别使用 `sequence_*`、`structure_*`，传给两次调用，不再共用一套设置；单轨道使用不带前缀的字段。`num_samples` 仍为节点批次参数。

Biohub 步数为 1–100、`top_p` 为 `(0,1]`；本地 SDK 步数为正整数且保留 SDK 对实际采样位置的步数处理，`top_p` 为 `[0,1]`。两条路线温度均不设无依据上限，显式默认 1 来自固定 SDK `GenerationConfig`，并非省略 HTTP 字段后采用 API 默认 0.5。`invalid_ids` 默认空列表；坐标条件默认 true；均实际传给 SDK。本地 seed 只在本地 Binding 声明，Biohub 不再显示无效 seed，也不虚构服务端控制。

依据：[固定 SDK 参数](../repositories/esm/esm/sdk/api.py)、[本地 nucleus sampling](../repositories/esm/esm/utils/sampling.py)、[官方远程快照](biohub-api-reference/v1/endpoints/generate.md)。`only_compute_backbone_rmsd` 仅影响当前不保留的 cRMSD，不新增对应输出或模式。

当前已调整声明、Adapter 与调用方；完整适用门禁与 Biohub 真实验收仍待本次集成验证，本地重模型执行明确排除。参数契约检查不代替真实 Provider 验收。

### SoluProt 非标准字符处理

项目始终传 `--check_unknown`，且调用前拒绝非标准残基；项目自有 Provider CLI 将其定义为可选且默认 false。关闭检查时 Provider 会过滤非标准字符，不是原样评价。因此项目固定了工具的一项输入处理选择，需要与参数策略对齐，但不能简单删除检查并静默改变输入。

依据：[固定参数](../modules/solubility/soluprot.py#L238)、[前置检查](../modules/solubility/implementation.py#L53)、[自有 CLI](../repositories/soluprot-next/soluprot_core/cli.py#L65)、[过滤行为](../repositories/soluprot-next/soluprot_core/features.py#L259)。这里的 CLI 是项目自有代码，不当作第三方官方规范。

### DSSP 注释

固定版本官方 CLI 提供 `min-pp-stretch`，当前调用未开放；但项目将 `P` 翻译成 `C`，它对当前公开轨道的影响需确认，暂不列为确定结果变化。[项目调用](../modules/structure_annotation/adapter.py#L294)、[标签转换](../modules/structure_annotation/adapter.py#L34)、[官方 v4.6.1 CLI](https://github.com/PDB-REDO/dssp/blob/v4.6.1/src/mkdssp.cpp#L63-L69)。

### Protein-Sol

当前调用外部部署的 wrapper，工作区未找到该固定脚本源码，不能确定还有哪些官方参数被遗漏。项目的最短21残基要求尚未核实上游依据，不将其称为官方硬限制。[调用入口](../modules/solubility/protein_sol.py#L158)、[长度要求](../modules/solubility/implementation.py#L152)。

## 不应误判为本原则冲突的事项

- **SoluProt full/no-TM**：已通过 Method/Binding 选择，不能因为节点参数为空就认定用户无法配置。
- **SimpleFold 的步数控件**：界面已可编辑，问题是后端给出的范围，不是前端写死50。
- **SimpleFold 现有结构 confidence**：直接执行 confidence head，不重新采样，不应给它凭空添加折叠 steps/tau。
- **DSSP accessibility 恒开启**：当前操作承诺输出 SASA，开启该计算是履行既定输出，不直接作为应新增关闭选项的证据。
- **ESMC 表征其他输出模式**：hidden states、层选择、SAE 等不自动纳入。embedding 和实际 logits 已确认应作为可选输出供查看及后续模块使用；当前仅保留 logits shape 属于已决定待对齐的结果问题。
- **模型路线和设备路径**：不因为模型固定就自动要求新增全部模型；部署配置与节点计算参数的开放范围分开。
- **自写结构对齐设置**：BLOSUM62、gap 等常量属于项目自定算法配置，不是外部工具官方参数缺失。可另审其用户配置需求，但不冒充已接入工具的参数遗漏。

## 前端检查结论

未发现前端额外隐藏或覆盖 ESM3、folding、solubility 已公开声明的普通参数。界面逐项读取 Node 和 Binding 参数，折叠面板展开后可编辑；默认示例卡只提供少数快捷项，不等于其他参数不可用。

因此主要改动位置是后端的参数声明、适配器传参及必要输入表示，再由界面展示这些配置；不能仅增加控件却仍传固定值。

证据：[参数读取](../webui/src/workflow-authoring.ts#L129)、[参数渲染](../webui/src/WorkflowParameters.tsx#L124)、[参数更新](../webui/src/App.tsx#L350)。

## 结论

ESM3 生成条件及采样参数已调整接入，等待完整集成验收；ESMFold2 推理参数、SimpleFold 的 tau 和步数范围仍需对齐。SoluProt 输入处理策略需避免静默改输入；DSSP 与 Protein-Sol 等证据不完整项继续核实，不升级为未经证实的缺陷。本报告没有决定这些模块需要全部重写，也没有新增计算模式。
