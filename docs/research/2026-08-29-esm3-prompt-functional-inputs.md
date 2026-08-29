# ESM-3 Prompt：完整功能输入模型

研究日期：2026-08-29

## 结论

ESM-3 的 Prompt 不是“上传一个模板 PDB，再决定遮罩哪些残基”。它是一个共享长度轴上的多轨道条件集合；PDB/坐标只是一种可选条件来源。面向产品讨论，必须一次同时裁决：目标长度与残基轴、sequence、structure coordinates、secondary structure、SASA、function annotations、每条轨道逐位置的已知/未知状态、要生成的目标轨道，以及多步生成顺序。

ESM-3 **允许没有模板 PDB**。严格由官方来源确认的起点包括：

- 只给定长度的全遮罩 sequence，进行无条件 sequence generation；
- 完整或部分 sequence；
- coordinates 而没有 sequence，用于 inverse folding；
- secondary-structure、SASA 或 coordinates 作为确定长度的首条轨道；
- function annotations 与任一能够确定长度的轨道组合；
- 多轨道的局部 motif/hotspot 条件；
- 依次生成 secondary structure → structure → sequence 的 chain-of-thought。

“完全不提供任何东西”则不是可执行起点：即使是无条件生成，也必须先给定蛋白质长度。官方 `ESMProtein` 不能仅从 function annotations 推断长度。

本项目的 `ProteinPrompt` 已能表达“长度轴 + 五类用户条件”的大部分 conditioning，但当前 ESM-3 Nodes 只生成 sequence、structure，或固定的 sequence → structure 配对；没有开放 secondary-structure、SASA、function generation，也没有开放任意 chain-of-thought 次序。当前 structure generation 还额外要求完整 sequence。这些是**本项目当前能力边界**，不是 ESM-3 本身的能力边界。

## 证据层级与范围

### 权威 provider facts

- 本项目固定官方 Biohub `esm` SDK revision [`917af90b624535eed1e072d343c717e3ec11fef4`](https://github.com/Biohub/esm/tree/917af90b624535eed1e072d343c717e3ec11fef4)，见 [`pyproject.toml`](../../pyproject.toml)。以下 SDK 行为以该 revision 为当前 provider contract。
- 模型能力与实验语义来自原始论文 [Hayes et al., *Simulating 500 million years of evolution with a language model*](https://doi.org/10.1126/science.ads0018) 及其公开 [bioRxiv v2](https://doi.org/10.1101/2024.07.01.600583)。
- API 值域和迭代生成行为来自官方 SDK 的 [`ESMProtein` / `GenerationConfig`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/api.py#L27-L66)、[raw encoding](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/encoding.py#L21-L152)、[model encoding](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/models/esm3.py#L429-L508) 和 [iterative sampling](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/generation.py#L99-L127)。

### 本项目 contract

- provider-independent authoring value：[`datatypes/prompt.py`](../../datatypes/prompt.py)
- authoring validation 与组装：[`modules/prompt_authoring/domain.py`](../../modules/prompt_authoring/domain.py)、[`modules/prompt_authoring/prompts.py`](../../modules/prompt_authoring/prompts.py)
- provider translation 与 operation：[`modules/esm3/adapter.py`](../../modules/esm3/adapter.py)、[`modules/esm3/implementation.py`](../../modules/esm3/implementation.py)
- Node contracts：[`modules/esm3/definitions/`](../../modules/esm3/definitions/)、[`modules/prompt_authoring/definitions/`](../../modules/prompt_authoring/definitions/)
- 边界测试：[`tests/test_esm3_v2.py`](../../tests/test_esm3_v2.py)、[`tests/test_prompt_authoring_prompt_v2.py`](../../tests/test_prompt_authoring_prompt_v2.py)

本文不会把论文中一次实验采用的 prompt engineering 做法提升为通用 provider 约束，也不会从当前 Workbench 限制反推 ESM-3 模型限制。

## 1. ESM-3 接受并组合哪些输入

### 1.1 面向用户的 high-level `ESMProtein`

官方 `ESMProtein` 暴露五类 prompt 字段，它们可以任意组合：

| 用户输入 | 官方 raw 表达 | 作用 |
|---|---|---|
| Sequence | `sequence: str \| None` | 每个位置可固定氨基酸或留作待生成 |
| Structure coordinates | `coordinates: Tensor \| None` | 每个残基的 atom37 坐标；可仅给局部坐标 |
| Secondary structure | `secondary_structure: str \| None` | 每位置 SS8 条件或遮罩 |
| SASA | `sasa: list[float \| None] \| None` | 每位置绝对 SASA 条件或遮罩 |
| Function annotations | `function_annotations: list[FunctionAnnotation] \| None` | 有标签的一维残基区间 |

来源：[官方 `ESMProtein`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/api.py#L27-L66)。论文将可编程输入概括为 sequence、structure coordinates、SS8、SASA、function keywords，并展示跨轨道组合 prompt；见 [论文](https://doi.org/10.1101/2024.07.01.600583) 的 Fig. 1、Fig. 2 和 Appendix A.3.10。

### 1.2 模型内部的七条 input tracks

论文 Appendix A.1.5.1 区分七条模型输入：

1. sequence tokens；
2. structure coordinates；
3. structure tokens；
4. SS8 tokens；
5. quantized SASA；
6. function keyword tokens；
7. residue/InterPro annotations。

用户在 high-level API 中给 `coordinates` 后，SDK 通过 structure encoder 得到 structure tokens；function annotations 同时编码为 function tokens 和 residue-annotation tokens。因此，用户界面不应把“structure tokens”误作必须手工填写的第六类输入，也不应把 function keywords 与 residue annotations 当成两套互不相关的 high-level authoring 对象。官方编码路径见 [`ESM3.encode`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/models/esm3.py#L429-L508) 和 [`tokenize_function_annotations`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/encoding.py#L138-L152)。

## 2. 值域、缺省/遮罩语义与必要关系

### 2.1 共享长度轴

所有 present tracks 必须描述同一个长度 `L`，且每个位置相互对齐。raw `ESMProtein` 按 sequence → secondary structure → SASA → coordinates 的顺序找到第一条 present track 来推断长度；四者均不存在时失败。Function annotations 自身不能确定 `L`。来源：[官方 `ESMProtein.__len__`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/api.py#L56-L66) 与 [`ESM3.encode`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/models/esm3.py#L456-L497)。

因此“无条件生成”的功能输入仍是一个长度 `L`；不是没有 prompt，而是除长度以外没有固定生物条件。

### 2.2 各轨道语义

| 轨道 | provider 值域与 mask | 本项目值域与翻译 |
|---|---|---|
| Sequence | raw string；`_` 被转为 mask token。官方 tokenizer vocabulary 包含 20 个 canonical amino acids、`X/B/U/Z/O` 以及特殊符号；见 [constants](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/constants/esm3.py#L41-L64) 与 [encoding](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/encoding.py#L21-L45)。 | 每位置为 `ACDEFGHIKLMNPQRSTVWYBXZJUO` 或 `None`；Adapter 将 `None` 变为 `_`，但明确拒绝 provider 不可表示的 `J`。等长全-null track 是完整 sequence mask，翻译为全 `_`。见 [`domain.py`](../../modules/prompt_authoring/domain.py) 与 [`adapter.py`](../../modules/esm3/adapter.py)。 |
| Coordinates / structure | raw atom37 tensor；局部缺失由非有限/NaN 坐标表示，整条缺失为 `None`。论文明确说 partially or fully masked coordinates 可输入。 | 每位置为非空 named-atom → finite Cartesian 3-vector map 或 `None`。concrete value 直接发送并成为该 residue 的结构 conditioning；`None` 发送 NaN。全-null structure track 翻译为 `coordinates=None`。Adapter 只接受 atom37 名称。 |
| Secondary structure | SS8：`G,H,I,T,E,B,S,C`；`_` 作为 raw mask。论文描述 canonical SS8、unknown、mask；官方 tokenizer 见 [`ss_tokenizer.py`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/tokenization/ss_tokenizer.py)。 | `G,H,I,T,E,B,S,-` 或 `None`；`-` 是 canonical coil，Adapter 变为 provider `C`，`None` 变为 `_`。 |
| SASA | raw `list[float \| None]`；`None` 编码为 mask。论文将连续 SASA 离散为 16 bins；固定 SDK boundaries 见 [`constants/esm3.py`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/constants/esm3.py#L77-L95)。 | 每位置为 finite、`>= 0` 的绝对 SASA，单位 Å²，或 `None`；不归一化，Adapter 原值传递。 |
| Function annotations | `FunctionAnnotation(label,start,end)`；区间为 one-based inclusive。label 必须能被官方 function keyword、InterPro 或 residue-annotation tokenizer 识别；见 [`types.py`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/types.py#L14-L33) 与 [`encode_decode.py`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/function/encode_decode.py#L13-L81)。`None` 表示没有 raw functional conditioning。 | 区间同为 one-based inclusive，另保存 chain 与端点 residue identity 以维持 layout 关联；Adapter 只把 label/start/end 交给 provider。overlap policy 只属于添加/编辑 operation，不进入 annotation value。空 collection 被转为 `None`。当前本地 validator 只验证一般字符串形状，不验证 label 是否属于 provider vocabulary；未知标签会在 provider 编码时报错。 |

### 2.3 Canonical 空状态

- Workbench sequence 与 structure 永远携带等长 nullable tracks；全-null 是唯一完整 mask，不再同时接受 field absent。
- track 某位置为 null：该位置明确留给模型；sequence 使用 `_`，coordinates 使用缺失/NaN。
- secondary structure 与 SASA 仍允许 whole-track absent；目前没有证据把它们与 present-but-all-null 宣布为同一科学状态。
- 在 iterative generation 中，如果目标 track 整条为 `None`，SDK 会为它构造全 mask；如果目标 track present，则只采样其中的 masked positions。没有 mask 的目标 track不能生成。来源：[官方 generation utilities](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/generation.py#L130-L166) 和 [mask selection](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/generation.py#L225-L329)。

本项目 `ProteinPrompt` 必须有 identity-complete `target_layout`、sequence track 和 structure track；SS/SASA 为可选 tracks。所有 present tracks 长度必须等于该 layout。见 [`validate_protein_prompt`](../../modules/prompt_authoring/prompts.py) 和 [`PROTEIN_PROMPT_PORT_TYPE`](../../modules/prompt_authoring/prompt_types.py)。

### 2.4 跨轨道关系

Provider 的基本必要关系是共享 `L` 和同位置对齐；function interval 必须落在 `1..L`。不同轨道可以任意组合并共同 conditioning。

论文 Appendix A.3.10 的一个组合实验在已有 structure constraints 的位置遮罩 SS8，以避免该实验中的约束冲突。这是**一种 prompt construction 做法**，不是论文或 SDK 声明的普遍强制规则。当前 Workbench 也不替用户猜测、修复或自动消解跨轨道科学矛盾。

## 3. 没有模板 PDB 时的合法起点

| 起点 | provider 权威依据 | 当前项目 |
|---|---|---|
| Length-only / blank | 官方 `get_default_sequence(L)` 返回 `_ * L`；论文 Appendix A.3.6 在给定不同 `L` 时做 unconditional sequence generation。 | 创建 target layout 与等长全-null sequence/structure tracks；Adapter 形成全 `_` sequence 和 `coordinates=None`。可用于 sequence 或 paired generation。 |
| Partial sequence | 官方 cookbook 用一个带固定片段和 `_` 的 sequence 补全其余位置。 | 支持；每位置 `None` 变 `_`。 |
| Complete sequence | 官方 cookbook 清除 coordinates 后生成 structure（folding）。 | 支持 structure generation；当前 Node 明确要求 sequence 完整。 |
| Structure-only | 官方 cookbook 把 `sequence=None`、保留 coordinates，再生成 sequence（inverse folding）。 | 可组装 layout + concrete structure values；全-null sequence track 由 Adapter 发送为全 `_`；支持 sequence generation。 |
| Secondary-structure-only | 官方 `ESM3.encode` 可以用 secondary structure 推断长度；论文以 SS8-only/partial SS8 prompting 和 SS8-first CoT 生成。 | 可用 layout + SS track 对 sequence generation 做 conditioning。 |
| SASA-only | 官方 `ESM3.encode` 可以用 SASA 推断长度；论文独立评估 SASA prompting。 | 可用 layout + SASA track 对 sequence generation 做 conditioning。 |
| Function + length | Function annotations 本身不能推断长度；必须再给 masked sequence、SS、SASA 或 coordinates。论文展示 function keyword prompting。 | target layout 会变成 provider 的全 mask sequence，因此功能区间可以与长度轴共同作为 sequence-generation prompt。 |
| Multimodal partial motif/hotspot | 论文组合 partial sequence、atomic coordinates、SS8、SASA 与 function keywords；不同条件可位于连续或不连续位置。 | 数据模型可表达这些组合；必须是同一个 layout，当前 ESM provider translation 只允许单链。 |
| CoT without template | 官方 cookbook 以 function 条件起步，依次生成 secondary_structure、structure、sequence；论文 Appendix A.3.6 也评估 SS8 → structure → sequence。 | 当前没有 SS/SASA/function generation Nodes，也不允许没有完整 sequence 的 structure-generation Node，因此尚不能表达该完整路线。 |

官方代码示例总览：[官方 ESM-3 cookbook snippet](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/cookbook/snippets/esm3.py)。

结论：产品必须把“创建空白长度轴”作为 PDB import 的同级入口，而不是把 ProteinPrompt Studio 设计成 PDB 编辑器。

## 4. Generation target / operation 与 conditioning 的关系

`ProteinPrompt` 回答的是：**哪些轨道、哪些位置现在是条件，哪些位置未知？**

`GenerationConfig.track` 回答的是：**这一次要把哪一条目标轨道的 masked positions 生成出来？**

固定 SDK 声明的 generation targets 是 `sequence`、`structure`、`secondary_structure`、`sasa`、`function`；其他参数包括 `num_steps`、temperature、top-p、schedule、strategy、temperature annealing 等。来源：[官方 `GenerationConfig`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/api.py#L320-L372)。

一次 operation 只迭代 unmask 被选中的 target track，其他输入轨道保持为 conditioning。目标轨道上已经固定的位置也保持不变；只有 masked positions 被采样。SDK 会把 `num_steps` 降到实际需要采样的位置数，且目标没有 mask 时返回错误。来源：[官方 iterative sampling](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/generation.py#L354-L533)。

多步生成不是一个 Prompt 的隐藏属性，而是一系列有顺序的 operations：前一步生成的轨道成为后一步的新 conditioning。例如官方 CoT 是 function → generate SS → generate structure → generate sequence；当前 Workbench paired operation 固定为 sequence → structure。

## 5. 本项目 `ProteinPrompt` 与 provider 类型的差异和限制

### 5.1 `ProteinPrompt` 相比 `ESMProtein` 增加的合同

- 必须有 identity-complete `target_layout`，保留 chain-qualified residue identities；provider 只有位置轴。
- 所有 present tracks 明确对齐该 layout。
- structure 只有 named-atom values/null；provider 只有 coordinates/NaN，不存在第二条 scientific visibility track。
- function annotations 增加 chain、端点 residue provenance；provider 只收 label/start/end。overlap policy 留在 authoring operation。
- SASA 明确固定为绝对 Å²、无归一化。
- `None` 是 authoring 层统一的“该位置未指定”，Adapter 再翻译成各 provider track 的 mask 表达。

### 5.2 当前 translation

[`protein_prompt_to_provider`](../../modules/esm3/adapter.py) 总是创建 high-level `ESMProtein`：

- sequence track 的 null 位置 → `_`；等长全-null track → 全 `_`；
- SS `-` → `C`，`None` → `_`；
- SASA `None` 原样作为 provider mask；
- structure track 的 null residue → atom37 NaN；全-null track → `coordinates=None`；
- function annotations → provider label/start/end。

Generation config 还固定 `condition_on_coordinates_only=True`，意味着生成时使用 raw coordinates conditioning，并清除由其编码出的 structure-token conditioning；见 [`generation_config`](../../modules/esm3/adapter.py)。

### 5.3 当前 capability gaps

1. **生成目标被缩窄**：只有 sequence、structure、固定 paired；provider 的 SS、SASA、function targets 未开放。
2. **CoT 被缩窄**：只能单轨生成或 sequence → structure，不能用户编排任意 track 顺序。
3. **structure generation 前置条件更严格**：当前 operation 要求完整 assigned sequence；ESM-3 官方 tensor workflow 和论文展示了 SS → structure → sequence。
4. **只允许单链翻译**：`ProteinPrompt` 能保存多链 layout，但 Adapter 明确拒绝向 ESM SDK 翻译 multi-chain aligned tracks；见 [`adapter.py`](../../modules/esm3/adapter.py) 和 [`test_multichain_prompt_round_trip_preserves_explicit_esm3_refusal`](../../tests/test_prompt_authoring_prompt_v2.py)。
5. **不开放 raw token tracks**：structure tokens、function tokens、residue-annotation tokens、pLDDT conditioning 不属于当前 authoring surface。
6. **function label 可发现性缺失**：项目 authoring validator 接受一般合法字符串，官方 tokenizer 只接受已知 InterPro/function/residue labels。UI 不能暗示任意自然语言都一定可接受。
7. **sequence 字母表存在边界差**：authoring 层允许 `J`，但 Adapter 明确拒绝；测试见 [`test_adapter_preserves_every_representable_prompt_track_and_symbol`](../../tests/test_esm3_v2.py)。
8. **paired controls 共享**：当前 paired Node 对 sequence 与 structure 两次调用使用同一组 generation parameters；不能分别设置。
9. **没有模板并非限制**：layout-only、partial sequence、structure-only conditioning 已可由数据模型表达；缺的是把这些起点变成直观的产品功能。

## 6. 产品功能讨论必须整体裁决的维度

下一轮不应再逐个询问“要不要给 sequence 加一个 mask 按钮”。应把下面这组问题作为一个完整功能模型共同裁决：

1. **Prompt 起点**：空白长度、FASTA/sequence、PDB/coordinates、SS8、SASA、function constraints，以及加载已有 ProteinPrompt，哪些是一等入口？
2. **目标轴**：用户怎样定义长度、chain、residue identities；没有模板时怎样创建和编辑该轴？
3. **五类 high-level 条件**：sequence、coordinates、SS8、SASA、function annotations 如何在同一 residue axis 上同时可见和编辑？
4. **每位置状态**：每条轨道怎样明确区分“未提供整条轨道”“该位置 masked/unknown”“该位置 fixed”；sequence/structure 的全-null canonical state 如何显示？
5. **选择与批量编辑**：单残基、连续区间、多个不连续区间如何一次选择，并对多条轨道应用一个明确的编辑意图？
6. **条件组合与冲突**：界面如何同时展示不同抽象层级的条件；哪些组合只是提示潜在科学冲突，哪些由 provider contract 直接禁止？不得静默修改用户条件。
7. **Generation target**：本次生成 sequence、structure、SS、SASA 还是 function；目标轨道哪些位置实际有 mask；没有 mask 时应在运行前说明。
8. **Generation program**：单步还是 sequence/structure/SS 等多步链；每步顺序、输入继承和各自参数是否可见、可编辑？
9. **Provider/项目能力差异**：UI 显示的是完整 ESM-3 概念模型，还是当前 Workbench 已实现子集；未实现目标不能伪装成模型不支持。
10. **Function vocabulary**：用户从什么权威 label vocabulary 中查找/选择 InterPro、关键词和 residue annotations；是否需要自然语言搜索只是产品交互问题，不能改变 provider 接受值域。
11. **无模板工作流**：必须以至少一个完整用户旅程验证 blank length → sequence → structure；另验证 structure-only → inverse-folded sequence，以及 SS/function-conditioned design。
12. **科学预览与运行摘要**：运行前应显示有效长度、每条轨道 fixed/masked counts、目标轨道、operation 顺序和模型，以便研究人员确认模型实际会收到什么。

## 7. 仍需裁决或研究的事项

以下没有被本次来源证明为现成产品决定：

- UI 是否直接开放 provider 的 SS/SASA/function generation targets，还是首版只做 sequence/structure；
- multi-chain ESM-3 能力是否进入当前产品范围。官方最新 cookbook 展示 complex folding，但本项目固定合同明确拒绝 multi-chain Prompt translation；这需要独立规格决定，不能在 UI 中猜测；
- arbitrary function keyword vocabulary 的检索、别名和人类可读描述数据源；
- coordinates 与 SS/SASA/function 条件发生科学张力时，应提供何种解释和警告。论文实例不能自动升级为通用冲突规则；
- 允许直接编辑 atom coordinates 的深度，还是只提供 motif 选择与刚体变换。3D viewer visibility 只属于 opaque UI state，不改变科学 Prompt。
