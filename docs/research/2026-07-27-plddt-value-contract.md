# pLDDT 数值尺度与 Protein Workbench 公共契约核查

日期：2026-07-27

状态：ADR-0020 之前的历史研究；尺度裁决已经实现

结论适用范围：本文中的“当前 Workbench”“当前 Adapter”和测试缺口均指
2026-07-27 的研究快照。现行公共合同由
[ADR-0020](../adr/0020-canonical-plddt-contract.md) 定义：所有公开 pLDDT 使用无量纲
`0–100`，Provider-native `0–1` 只在声明该尺度的 Adapter 边界转换一次。当前实现见
[`modules/esm3/adapter.py`](../../modules/esm3/adapter.py) 和
[`modules/folding/domain.py`](../../modules/folding/domain.py)。Meta ESMFold v1 只保留为
历史名称辨析证据，不属于项目需求、迁移或验收范围。

## 1. 结论

用户提出的核心判断成立，但必须附加版本与调用层级：

1. pLDDT 对用户公开时的通行尺度是无量纲的 `0–100`，数值越大表示局部结构置信度越高。
   Google DeepMind 的 AlphaFold 官方输出合同明确把逐残基 pLDDT 定义为 `0–100`，并把它写入
   PDB 的 B-factor 字段。参见
   [AlphaFold README 固定提交](https://github.com/google-deepmind/alphafold/blob/c77e5d2a8961d1a353632c462914ff0a32a950f6/README.md#L606-L624)。
2. 当前 ESM-3 SDK 的公开 `ESMProtein.plddt` 是 `0–1`；当前 ESMFold2 的模型输出与 SDK
   结果也是 `0–1`。
3. SimpleFold 的置信度头输出 `0–1`，但官方高层推理 wrapper 已乘以 100，因此 Workbench
   当前从 wrapper 接收的是 `0–100`。
4. 旧版 Meta ESMFold v1 与 ESMFold2 不能混为一谈：它的置信度头先产生 `0–1`，但
   `forward()`/`infer()` 对外返回前已经乘以 100。
5. 研究快照中的 Workbench 因而确实存在公共尺度不一致：
   - ESM-3 Score：`0–1`；
   - ESMFold2 Score：`0–1`；
   - SimpleFold Score：`0–100`。
6. Workbench v2 后来在 Adapter 边界按方法的静态合同实现了一次转换，对外只暴露 `0–100`。
   不能通过 `max(values) <= 1` 猜测尺度。
7. 仅统一尺度仍不够。公共合同还必须区分逐残基 pLDDT 与“逐残基等权平均 pLDDT”，并保留
   method/model 身份；不同模型的同尺度置信度不代表已经完成跨模型校准。

## 2. 核查范围与代码身份

本次核查区分四层，不把它们互相代替：

1. 模型置信度头或解码器产生的原生张量；
2. SDK、模型 wrapper 或公开推理结果；
3. Protein Workbench 的 `Score`；
4. PDB/mmCIF 的 B-factor 或 QA metric 写出值。

本地依赖快照：

- `Biohub/esm`：
  `917af90b624535eed1e072d343c717e3ec11fef4`；
- `apple/ml-simplefold`：
  `c7a5570a6be9f5c695126e27c804e77567209934`；
- `repositories/esm/pixi.lock` 中的 Biohub Transformers ESMFold2 源码固定为
  `3a8956fb4d4ea16b0ec8e71deef2c2909b6a5cbf`，见
  [固定版本的 `pixi.lock`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/pixi.lock)。

旧 ESMFold 仅用于厘清名称与尺度差异，使用 Meta 官方归档仓库提交
`2b369911bb5b4b0dda914521b9475cad1656b2ac`。当前 Workbench 没有 Meta ESMFold v1
Module；它实现的是 ESM-3、ESMFold2 和 SimpleFold。

## 3. 四层尺度总表

| 方法 | 模型头/解码器 | 公开 SDK 或 wrapper | 研究快照中的 Workbench Score | 结构文件 |
| --- | --- | --- | --- | --- |
| ESM-3 | `0–1` | `ESMProtein.plddt`: `0–1` | `0–1` | 当前 ESM writer 乘 100 |
| ESMFold2 | per-atom `0–1`，聚合后的 per-token 仍为 `0–1` | `ESMProtein` / `MolecularComplexResult.plddt`: `0–1` | `0–1` | 当前 ESM writer 乘 100 |
| Meta ESMFold v1 | 未缩放期望值 `0–1` | `output["plddt"]`: `0–100` | 当前未集成 | PDB 直接写 `0–100` |
| SimpleFold | ConfidenceModule: `0–1` | `generate_structure()` / wrapper: `0–100` | `0–100` | PDB/mmCIF 直接写 `0–100` |

这些模型都使用离散 bin 中点的概率加权期望。对于 50 个 bin，数学上产生的值落在 bin
中心的凸包内；公共合同仍应使用包含端点的 `[0, 1]` 或 `[0, 100]` 做输入验证，而不把
`0.01–0.99` 等实现细节变成跨版本合同。

## 4. ESM-3

### 4.1 模型原生张量：`0–1`

ESM-3 结构解码器使用默认 `start=0, end=1` 的 `CategoricalMixture`，对 50 个 bin 的
中点求概率期望：

- [官方 `vqvae.py`：CategoricalMixture](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/models/vqvae.py#L114-L136)；
- [官方 `vqvae.py`：把期望值直接作为 `plddt` 返回](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/models/vqvae.py#L426-L435)；
- [官方 `decoding.py`：仅移除 BOS/EOS，不做尺度转换](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/decoding.py#L153-L169)。

因此 ESM-3 解码得到的逐残基 pLDDT 是 `0–1`。

### 4.2 SDK 公开结果：`0–1`

`ESMProtein.plddt` 保存上述张量；转成 `ProteinChain` 时又原样传入
`ProteinChain.confidence`，没有乘 100：

- [官方 `api.py`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/api.py#L148-L163)。

### 4.3 研究快照中的 Workbench Score：仍为 `0–1`

当前 Adapter 明确验证 provider pLDDT 必须位于 `[0, 1]`，随后计算平均值并原样写入
`Score.value` 和 `details.per_residue`。该旧单体 Adapter 已删除；当前转换由
[`modules/esm3/adapter.py`](../../modules/esm3/adapter.py) 拥有。

### 4.4 当前结构写出：`0–100`

当前 ESM 源码明确声明内部 confidence 使用 `0–1`，mmCIF/PDB B-factor 使用传统
`0–100`：

- [官方尺度常量与说明](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/structure/mmcif_parsing.py#L20-L22)；
- [PDB atom B-factor 乘 100](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/structure/protein_chain.py#L221-L237)；
- [mmCIF local QA metric 乘 100](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/structure/protein_chain.py#L366-L373)。

研究快照中的 ESM-3 结构路径调用 `esm_protein.to_pdb_string()`，所以“PDB 已是 0–100”
不能反推“Workbench Score 已是 0–100”。当前翻译见
[`modules/esm3/adapter.py`](../../modules/esm3/adapter.py)。

### 4.5 版本 caveat

“ESM writer 一直会恢复到 0–100”并非历史上始终成立。当前缩放逻辑来自后续的官方
`oss sync`；旧提交 `e2f7a1c...` 曾直接把 `0–1` confidence 写进 B-factor。仓库内
2026-07-21 的封存研究包也明确是历史证据，不能替代当前实现，见
[`biohub-api-reference/research/README.md`](../biohub-api-reference/research/README.md)。

因此 Adapter 和 manifest 必须记录 SDK/源码版本，不能把文件写出行为视为永恒不变。

## 5. ESMFold2

### 5.1 模型张量：`0–1`

当前 ESMFold2 confidence head：

1. 对 per-atom logits 调用 `_categorical_mean(..., start=0.0, end=1.0)`；
2. 再按 token 汇总有效原子，得到公开的 per-token `plddt`；
3. 返回时不乘 100。

证据：

- [Biohub Transformers：per-atom 和 per-token 计算](https://github.com/Biohub/transformers/blob/3a8956fb4d4ea16b0ec8e71deef2c2909b6a5cbf/src/transformers/models/esmfold2/modeling_esmfold2.py#L227-L249)；
- [Biohub Transformers：返回 `plddt` 与 `plddt_per_atom`](https://github.com/Biohub/transformers/blob/3a8956fb4d4ea16b0ec8e71deef2c2909b6a5cbf/src/transformers/models/esmfold2/modeling_esmfold2.py#L333-L339)。

ESM 的 processor 把 `output["plddt"]` 原样放入 `MolecularComplexResult.plddt`，见
[官方 `processor.py`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/models/esmfold2/processor.py#L270-L299)。

### 5.2 研究快照中的 Workbench Score：`0–1`

Workbench 当时从 `ESMProtein.plddt` 取值、求平均并原样写进 Score。该旧单体 Adapter
已经删除；当前一次性转换由
[`modules/folding/domain.py`](../../modules/folding/domain.py) 以及 remote/local ESMFold2
Adapters 使用。

### 5.3 结构写出：`0–100`

研究快照中的 Workbench 先把 `ESMProtein.plddt` 原样交给
`ProteinChain.confidence`，再使用 ESM writer。共享 writer 会乘以 100；
`MolecularComplex` 的 mmCIF 路径也执行同样转换：

- [官方 `molecular_complex.py`](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/utils/structure/molecular_complex.py#L1048-L1071)。

### 5.4 聚合语义

ESMFold2 同时具有：

- `plddt_per_atom`：逐原子；
- `plddt`：同一 token 内有效原子的平均；
- `complex_plddt`：全部有效原子的平坦平均。

它们不是同一粒度。Workbench 当前收到并平均的是公开 per-token `plddt`；不能改为直接使用
`complex_plddt`，否则会从“残基/token 等权平均”悄然变成“原子加权平均”，而且复合物还可能
包含非蛋白 token。

## 6. Meta ESMFold v1

这里的 ESMFold 指 Meta 归档仓库中的经典 ESMFold v1，不是 ESMFold2。

- 置信度头的 categorical mixture 原生输出 `0–1`：
  [官方 `categorical_mixture.py`](https://github.com/facebookresearch/esm/blob/2b369911bb5b4b0dda914521b9475cad1656b2ac/esm/esmfold/v1/categorical_mixture.py#L8-L43)。
- `forward()` 设置 `structure["plddt"]` 时明确乘 100：
  [官方 `esmfold.py`](https://github.com/facebookresearch/esm/blob/2b369911bb5b4b0dda914521b9475cad1656b2ac/esm/esmfold/v1/esmfold.py#L249-L256)。
- PDB writer 直接把该公开结果写入 `b_factors`，不再缩放：
  [官方 `misc.py`](https://github.com/facebookresearch/esm/blob/2b369911bb5b4b0dda914521b9475cad1656b2ac/esm/esmfold/v1/misc.py#L93-L116)。

下面的差异只解释历史名称混淆，不构成未来支持要求：

```text
Meta ESMFold v1 output["plddt"] -> identity
ESMFold2 result.plddt            -> multiply by 100
```

## 7. SimpleFold

### 7.1 置信度头：`0–1`

SimpleFold 的 Torch 和 MLX confidence module 都以 `end=1.0` 构造 bin 中点并返回概率加权
期望：

- [官方 Torch 实现](https://github.com/apple/ml-simplefold/blob/c7a5570a6be9f5c695126e27c804e77567209934/src/simplefold/model/torch/confidence_module.py#L10-L36)；
- [固定上游版本中的 MLX 实现](https://github.com/apple/ml-simplefold/blob/c7a5570a6be9f5c695126e27c804e77567209934/src/simplefold/model/mlx/confidence_module.py)
  （10–34 行）。

### 7.2 官方高层推理结果：`0–100`

官方 `generate_structure()` 和 `ModelWrapper.run_inference()` 都在返回前执行
`plddt_out_dict["plddt"] * 100.0`：

- [官方 `inference.py`](https://github.com/apple/ml-simplefold/blob/c7a5570a6be9f5c695126e27c804e77567209934/src/simplefold/inference.py#L245-L267)；
- [官方 `wrapper.py`](https://github.com/apple/ml-simplefold/blob/c7a5570a6be9f5c695126e27c804e77567209934/src/simplefold/wrapper.py#L329-L366)。

PDB 与 mmCIF writer 直接使用该数组，不再乘 100：

- [官方 PDB writer](https://github.com/apple/ml-simplefold/blob/c7a5570a6be9f5c695126e27c804e77567209934/src/simplefold/boltz_data_pipeline/write/pdb.py#L75-L94)；
- [官方 mmCIF writer](https://github.com/apple/ml-simplefold/blob/c7a5570a6be9f5c695126e27c804e77567209934/src/simplefold/boltz_data_pipeline/write/mmcif.py#L158-L199)。

### 7.3 研究快照中的 Workbench Score：已经是 `0–100`

Workbench 当时调用高层 `run_inference()`，随后把 `results["plddts"]` 的平均值原样写入
Score，Evaluate 路径则自行乘以 100。当前 folding 和 existing-structure confidence 路径分别
见 [`simplefold_adapter.py`](../../modules/folding/simplefold_adapter.py) 和
[`simplefold_confidence_adapter.py`](../../modules/folding/simplefold_confidence_adapter.py)。

### 7.4 method identity 的额外发现

SimpleFold 的 pLDDT 并不只由用户选择的 folding model 标识。官方 wrapper 固定加载：

- `plddt_module_1.6B.ckpt`；
- `simplefold_1.6B.ckpt` 作为 pLDDT latent module。

证据见
[官方 `wrapper.py`](https://github.com/apple/ml-simplefold/blob/c7a5570a6be9f5c695126e27c804e77567209934/src/simplefold/wrapper.py#L117-L196)。

研究快照中的 `simplefold.evaluate` 暴露过多个 model choice，但实际用于生成 pLDDT 的仍是
固定 1.6B latent + pLDDT head。当前合同已经将该身份固定在
[`simplefold_confidence.yaml`](../../modules/folding/definitions/simplefold_confidence.yaml) 和
folding Method declarations 中。

因此未来的 `method_id` 必须标识真实 confidence head/latent checkpoint，不能仅复用
`model_name` 参数。

## 8. 推荐的 Workbench v2 公共合同

### 8.1 分成两个明确指标

建议不要让一个标量 `score_id="plddt"` 同时暗指逐残基数组与它的平均值：

```yaml
metric_id: structure.plddt.per_residue
value_type: residue_series
canonical_range: [0, 100]
unit: dimensionless
direction: higher_is_better
granularity: protein_residue
```

```yaml
metric_id: structure.plddt.mean_residue
value_type: scalar
canonical_range: [0, 100]
unit: dimensionless
direction: higher_is_better
aggregation: arithmetic_mean_of_valid_protein_residues
```

`0–100` 是数值尺度，不应标成物理单位 `%`。平均值应由 canonical per-residue 数组重新计算：

- 只包含有效蛋白残基；
- 排除 padding、chain break、非蛋白 token 与 NaN；
- 每个残基等权；
- 不直接复用 atom-weighted `complex_plddt` 或旧 ESMFold 的 `mean_plddt`。

### 8.2 Adapter 静态转换表

| Adapter 接口 | native scale | canonical conversion |
| --- | ---: | --- |
| ESM-3 `ESMProtein.plddt` | `0–1` | `x * 100` |
| ESMFold2 `ESMProtein` / `MolecularComplexResult.plddt` | `0–1` | `x * 100` |
| SimpleFold high-level wrapper `plddts` | `0–100` | identity |
| SimpleFold direct `ConfidenceModule["plddt"]` | `0–1` | `x * 100` |

禁止：

```python
if max(plddt) <= 1:
    plddt *= 100
```

一个真实但极低的 `0–100` 结果也可能全部小于 1；启发式还会掩盖上游版本改变。每个
Adapter 应静态声明 `native_scale`，验证 native 值，只转换一次，并在 provenance 中记录：

- native scale；
- conversion；
- SDK、模型和 confidence-head 身份；
- canonical metric contract version。

### 8.3 序列化边界必须与评分边界分离

ESM writer 的输入 confidence 仍应保持 provider-native `0–1`。如果把已经 canonicalize
到 `0–100` 的 Workbench 数组写回 `ProteinChain.confidence`，当前 writer 会再次乘 100，
产生最高 10000 的 B-factor。

因此：

- provider 原始对象负责结构序列化；或
- 调用 writer 前明确转回它要求的 native scale；
- 不应从已经四舍五入的 PDB B-factor 反向构造 Workbench Score。

## 9. 历史下游影响与当前 resolution

这项变化当时不只是两个 Adapter 的局部修改。Filter 阈值必须从 `0.7` 改为 canonical
`70`；Weighted Rank 不能把 `0–100` pLDDT 与 `0–1` pTM 裸加。当前 Selection 实现和测试见
[`modules/selection/implementation.py`](../../modules/selection/implementation.py)、
[`tests/test_selection_v2.py`](../../tests/test_selection_v2.py) 和
[`tests/test_multi_objective_selection_v2.py`](../../tests/test_multi_objective_selection_v2.py)。
显式 Utility Transform 的当前裁决由
[ADR-0021](../adr/0021-weighted-rank-uses-explicit-utilities.md) 拥有。

禁止根据当前 Candidate 集合隐式 min-max，也禁止根据数值范围猜测转换。实际转换身份、
版本与参数必须持久化并进入 Run provenance。

### 9.1 哪些操作对正比例换算不敏感

- 单指标升降序排序不受 `×100` 影响；
- Pareto dominance 对每一维的正比例换算不变；
- 固定阈值、加权和、聚合输出、缓存内容和展示值会改变。

即使排序结果碰巧不变，manifest 中的值和 metric contract version 仍必须改变。

### 9.2 v2 不读取旧运行时产物

v2 是首次正式发布前的破坏性合同重置。旧 Workflow、缓存与 manifest 不迁移、不重写，
也不由 v2 读取；旧格式只产生结构化 `unsupported_schema_version`。仓库跟踪的示例、
seed Workflow 与测试 fixture 直接重写为 v2，历史研究和 ADR 仅保留为设计证据。

## 10. 已闭合的测试要求

当前合同测试覆盖下列要求；现行入口包括
[`tests/test_esm3_v2.py`](../../tests/test_esm3_v2.py)、
[`tests/test_folding_v2.py`](../../tests/test_folding_v2.py)、
[`tests/test_simplefold_confidence_v2.py`](../../tests/test_simplefold_confidence_v2.py) 和
[`tests/acceptance/test_simplefold_v2.py`](../../tests/acceptance/test_simplefold_v2.py)：

- 一个 native `0.8` 的 ESM-3/ESMFold2 provider 值公开为 `80`；
- 一个 SimpleFold wrapper 值 `80` 公开后仍为 `80`；
- per-residue 与 mean 同时处于 `[0,100]`，且 mean 由有效残基等权重算；
- pTM 保持 `[0,1]`，不会随 pLDDT 一起缩放；
- 结构文件 B-factor 与 canonical pLDDT 相符，但不会发生二次乘 100；
- filter 阈值与 Weighted Rank 的 Utility Transform 行为被固定测试覆盖。

## 11. 最终裁决

Workbench v2 已把 pLDDT 的公共尺度固定为 `0–100`。这项裁决不意味着把所有 provider
内部张量改成 `0–100`，而是确立一个清晰边界：

```text
provider-native result
-> method-specific Adapter validation and one-time normalization
-> canonical per-residue pLDDT [0,100]
-> canonical residue-equal mean pLDDT [0,100]
-> Score / Workflow / UI / manifest
```

结构 writer 继续遵循各自 SDK 的 native 输入合同。Metric Registry 声明科学量与 canonical
尺度；ModulePackage/Adapter 声明 method、model、native scale 和转换方式。这样才能同时满足
统一用户语义、零核心修改的模块扩展，以及可追溯的跨模型比较。
