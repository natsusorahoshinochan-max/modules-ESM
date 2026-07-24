# Biohub ESM3 generation output study

## 结论

本次在 `2026-07-21` 使用当前仓库固定的 ESM SDK `3.3.0`，对 Biohub 的
`esm3-open-2024-03` 与 `esm3-medium-2024-08` 各执行了一组最小真实调用。六个计划内
case 均一次成功；没有重试，也没有失败 case。

事实结论是：

1. `generate(track="sequence")` 的返回类型可以携带结构相关字段，但是否携带取决于
   Prompt。无坐标 Prompt 时，两个模型都只返回 sequence；`coordinates`、`pTM`、
   `pLDDT` 和 PAE 都为空。
2. 使用完整 1PGA 坐标作为条件时，两个模型都返回 sequence、`coordinates
   [56,37,3]`、标量 pTM 和 `pLDDT [56]`。这些坐标不是逐值 passthrough，但在刚体
   对齐后与输入骨架极为接近：Cα RMSD 为 `0.1403 Å` 和 `0.1466 Å`。结合请求只采样
   sequence track 这一事实，最有证据支持的分类是**输入结构的坐标条件重建/重解码**，
   而不是一次独立的新 structure-track generation。
3. 当前 Guided denoise 使用的单次 `forward_and_sample(sequence + structure)` 确实同时
   返回 sequence token 和 structure token；对无坐标 Prompt 再执行 `decode` 后，两个模型
   都产生新的 `coordinates [56,37,3]`、标量 pTM 和 `pLDDT [56]`。这里没有输入坐标可供
   passthrough，而且 structure track 被明确采样，因此这才是本次证据中可直接归类为
   **sampled structure output** 的情况。
4. 单次双轨 `forward_and_sample` 只是一个 denoised proposal，不等于完整 Guided loop。
   完整 Guided 还包括逐步 sequence-only unmask、每步多个 denoised proposal、评分与选择。
5. 当前项目的 Direct adapter 最终只保留 sequence；Guided 虽在 proposal state 中临时保存
   解码后的结构，但 terminal success 也只保留 sequence。因此两条路径当前都没有把
   generation-time structure 作为正式工作流输出持久化。

由此应当修正一句过宽的表述：**Direct 与 Guided 可以在未来拥有相同的公共输出类型，
但不能把当前 `Direct generate(track="sequence")` 返回的任何 coordinates 都自动解释成新生成
结构。** 输出合同必须同时记录结构来源与 lineage。

完整机器观测见 [`observations.json`](observations.json)，结构见同目录 PDB，文件摘要见
[`checksums.json`](checksums.json)。

## 研究边界与配置

### 固定环境

- 仓库提交：`d030204ed7cc67201d6b03e0fd3a21a3ec8ca927`。
- Biohub endpoint：`https://biohub.ai`，受控 endpoint ID 为 `biohub`。
- 模型：`esm3-open-2024-03`、`esm3-medium-2024-08`。
- SDK：`esm==3.3.0`。仓库的 [`vendor/manifest.json`](../../../../../vendor/manifest.json)
  记录固定 archive 及其 SHA-256 `12d0fef...699c`，[`requirements.lock`](../../../../../requirements.lock)
  直接从该 archive 安装。
- 凭据只通过仓库的 `scripts/verify/provider-authorization` 加载到进程环境；报告、JSON、PDB
  与命令输出均未保存 token、Authorization header、secret 文件路径或 provider traceback。
- 调用通过当前 deployment 所建立的受控 Forge client，且仓库明确把 SDK 外层 retry 设为
  `0`，见 [`deployment.py`](../../../../../src/workflow/v2/deployment.py#L242-L279)。

### Prompt

使用仓库中的 GB1 结构 [`resources/structures/1PGA.pdb`](../../../../../resources/structures/1PGA.pdb)，
chain A，长度 `56`。保存了一份自包含输入证据 [`input-1pga.pdb`](input-1pga.pdb)。

每个 Direct 模型各测试：

- `no_coordinates`：`sequence="_" * 56`，无 coordinates；
- `coordinate_conditioned`：相同全 mask sequence，加上 1PGA 的完整 atom37 coordinates。

Direct 为降低成本并隔离返回字段，使用：

```text
track=sequence
num_steps=1
temperature=0.0
schedule=linear
strategy=random
top_p=1.0
temperature_annealing=false
condition_on_coordinates_only=true
```

这不是生成质量基准，也不是项目默认 20-step 配置；它只研究一次合法 sequence-track
调用会返回什么。远端接口没有在本次调用中提供可冻结的 sampling seed，因此每个结果仅代表
一次 dated observation。

Guided 研究只隔离当前项目的 complete denoise 阶段：无坐标、全 mask sequence 先 `encode`，
然后执行一次：

```text
SamplingConfig
  sequence: temperature=0.0, top_p=1.0, invalid_ids=[]
  structure: temperature=0.0, top_p=1.0, invalid_ids=[]
```

再 `decode` sampled tensor。它没有运行前置的随机 partial-unmask、多个 sample、评分或 proposal
选择，因此不能被写成一次完整 Guided generation。

## Direct sequence-track 的 live 结果

### 无坐标 Prompt

| 模型 | sequence | coordinates | pTM | pLDDT | PAE | `structure` 属性 |
| --- | ---: | --- | --- | --- | --- | --- |
| `esm3-open-2024-03` | 56 aa | `None` | `None` | `None` | `None` | 不存在 |
| `esm3-medium-2024-08` | 56 aa | `None` | `None` | `None` | `None` | 不存在 |

两次调用拓扑均严格为一次公共 `generate`，对应 `POST /api/v1/generate`。这直接否定了
“当前 Direct 在没有结构条件时必然同时得到新结构”这一说法。对应 observation ID：

- `direct-esm3-open-2024-03-no_coordinates`
- `direct-esm3-medium-2024-08-no_coordinates`

### 坐标条件 Prompt

| 模型 | coordinates | pTM | pLDDT mean | Cα Kabsch RMSD | N/CA/C Kabsch RMSD | all-atom Kabsch RMSD |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `esm3-open-2024-03` | `[56,37,3]` | 0.873948 | 0.989569 | 0.1403 Å | 0.1490 Å | 0.8958 Å |
| `esm3-medium-2024-08` | `[56,37,3]` | 0.870138 | 0.989662 | 0.1466 Å | 0.1533 Å | 0.9109 Å |

这里的 pLDDT 是 SDK 原始 `0..1` 尺度，不是项目 Observation boundary 转换后的百分数。

输入与输出坐标 canonical hash 均不同，且坐标 frame 发生变化；未对齐的 Cα RMSD 约
`43.8 Å`。输出也改变了有限 atom37 覆盖：

| 模型 | 输入有限原子位 | 输出有限原子位 | 新变为有限 | 不再有限 | 双方均有限 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `esm3-open-2024-03` | 436 | 453 | 66 | 49 | 387 |
| `esm3-medium-2024-08` | 436 | 446 | 45 | 35 | 401 |

所以它们不是原始 tensor 的逐字节 passthrough。但是，刚体对齐后的全链 backbone RMSD 只有
约 `0.15 Å`，而且请求没有采样 structure track。有限原子覆盖的变化还会受到生成序列改变、
残基侧链原子集合不同和 structure decoder 补全的共同影响，不能用来证明产生了新的 backbone。

因此本报告采用以下窄结论：

> Biohub Direct sequence-track 在坐标条件下返回了 structure-bearing ESMProtein；返回坐标是
> 输入几何的非逐值重建，而不是独立 structure sampling 的证据。

服务端内部实现没有公开，因此“具体由哪一层完成坐标标准化、structure encoding 或 decoding”
仍为 unknown。本结论来自请求语义、字段事实和几何比较，而不是对服务端代码的推测。

PDB 证据：

- [`direct-esm3-open-2024-03-coordinate_conditioned.pdb`](direct-esm3-open-2024-03-coordinate_conditioned.pdb)
- [`direct-esm3-medium-2024-08-coordinate_conditioned.pdb`](direct-esm3-medium-2024-08-coordinate_conditioned.pdb)

## Guided complete denoise 的 live 结果

两个模型的调用拓扑都严格为：

```text
encode
→ forward_and_sample(sequence + structure)
→ decode
```

分别对应 `/api/v1/encode`、`/api/v1/forward_and_sample` 与 `/api/v1/decode`。原始
`ForwardAndSampleOutput` 不是解码后的结构对象：它返回 `protein_tensor.sequence [58]` 和
`protein_tensor.structure [58]`（包括 BOS/EOS），并同时返回两个轨道的 entropy、prob 和
logprob；coordinates 在这一步仍为空。随后 `decode` 才产生坐标与置信度。

| 模型 | sampled sequence tokens | sampled structure tokens | decoded coordinates | decoded pTM | decoded pLDDT mean | decoded PAE |
| --- | --- | --- | --- | ---: | ---: | --- |
| `esm3-open-2024-03` | `[58]` | `[58]` | `[56,37,3]` | 0.328573 | 0.474907 | `None` |
| `esm3-medium-2024-08` | `[58]` | `[58]` | `[56,37,3]` | 0.283856 | 0.425811 | `None` |

同样，pLDDT 是 SDK 原始尺度。这些数值来自一个刻意压缩的单步、temperature 0 研究调用，
不能用于比较模型质量或代表完整 Guided generation 的分布。

因为输入没有 coordinates，而 sampling config 明确启用了 structure，这两个 decoded structure
可以被事实性地归类为新 sampled structure。PDB 证据：

- [`guided-denoise-esm3-open-2024-03.pdb`](guided-denoise-esm3-open-2024-03.pdb)
- [`guided-denoise-esm3-medium-2024-08.pdb`](guided-denoise-esm3-medium-2024-08.pdb)

## 三种操作不能混为一谈

### 1. Direct sequence-track

```text
ESMProtein Prompt
→ generate(track="sequence")
→ ESMProtein
```

Biohub `generate` 的官方用途是“生成由输入条件约束的一个 output track”，本地固定 reference
见 [`generate.md`](../../v1/endpoints/generate.md#用途)。当前项目由
[`EsmSdkRuntime._generation_config()`](../../../../../src/workflow/v2/providers.py#L470-L488)
把计划编译为 `track="sequence"`，再执行恰好一次 public `generate`。

SDK `generate()` 的接口说明也把它定义为填充 `GenerationConfig.track` 指定轨道；官方源码见
[`esm/sdk/api.py`](https://github.com/Biohub/esm/blob/e2f7a1c1dfb97ade0a9cc8fc057bfbd59c719a5d/esm/sdk/api.py#L505-L561)。本地
iterative implementation 只写回目标 track，并在结束时恢复 input coordinates 和非目标 track，
见官方 [`esm/utils/generation.py`](https://github.com/Biohub/esm/blob/e2f7a1c1dfb97ade0a9cc8fc057bfbd59c719a5d/esm/utils/generation.py#L367-L526)。

Forge/Biohub response parser 会读取 server response 中的 coordinates、pLDDT 与 pTM，见官方
[`esm/sdk/forge.py`](https://github.com/Biohub/esm/blob/e2f7a1c1dfb97ade0a9cc8fc057bfbd59c719a5d/esm/sdk/forge.py#L550-L587)，
但字段存在不改变“本次只请求 sequence track”的科学 lineage。固定 Biohub reference 也没有发布
response schema，见 [`generate.md`](../../v1/endpoints/generate.md#响应)，因此本报告把 live JSON
作为 dated evidence，而不反向改写静态 reference。

### 2. 单次双轨 `forward_and_sample`

```text
ESMProteinTensor
→ forward_and_sample(sequence + structure)
→ sampled ESMProteinTensor + per-track sampling statistics
→ decode
→ ESMProtein coordinates/pTM/pLDDT
```

Biohub 将该 endpoint 定义为“一次 inference step 并采样 output tokens”，并允许 sequence 与
structure 分别拥有 SamplingTrackConfig，见 [`forward_and_sample.md`](../../v1/endpoints/forward_and_sample.md#用途)。
官方 `ForwardAndSampleOutput` 返回 token tensor 和 sampling statistics，而不是解码坐标，见
[`esm/sdk/api.py`](https://github.com/Biohub/esm/blob/e2f7a1c1dfb97ade0a9cc8fc057bfbd59c719a5d/esm/sdk/api.py#L486-L501)；Forge parser
见 [`esm/sdk/forge.py`](https://github.com/Biohub/esm/blob/e2f7a1c1dfb97ade0a9cc8fc057bfbd59c719a5d/esm/sdk/forge.py#L636-L685)。

当前项目的 `complete=True` 是内部 builder 语义：它明确同时构造 sequence 和 structure 两个
sampling config，随后 forward 并 decode，见
[`providers.py`](../../../../../src/workflow/v2/providers.py#L596-L622) 与
[`predict_denoised_once()`](../../../../../src/workflow/v2/providers.py#L689-L711)。

### 3. 完整 Guided loop

当前 Guided proposal topology 是：

```text
encode once
for each decoding step:
  for each sample:
    sequence-only forward_and_sample  # 只更新本步选择的 mask
    sequence+structure forward_and_sample
    decode
    evaluate/score proposal
  select one proposal and carry its partial sequence state forward
```

逐步 unmask 与 complete denoise 的两次调用见
[`EsmGuidedProposalBackend.propose()`](../../../../../src/workflow/v2/providers.py#L817-L895)。因此本研究的
single denoise observation 证明了 proposal 能产生结构，但不证明完整 Guided scoring、constraint、
selection 或 terminal admission 在这组最小 Prompt 上成功。

## 当前项目会保留什么、丢弃什么

Direct adapter 读取完整 `ESMProtein` 后只提取 `output.sequence`，并创建 sequence-only
`GeneratedCandidate`，见 [`providers.py`](../../../../../src/workflow/v2/providers.py#L745-L767) 和
[`execution.py`](../../../../../src/workflow/v2/execution.py#L53-L63)。因此坐标条件 Direct 的
coordinates、pTM 与 pLDDT 当前全部被丢弃。

Guided proposal 的 `EsmGuidedProposalState` 会临时携带 `denoised_protein` 供中间评分，见
[`providers.py`](../../../../../src/workflow/v2/providers.py#L770-L773)。但最终
[`GuidedSuccess`](../../../../../src/workflow/v2/guided.py#L37-L42) 仍只有 proposal ID 与 sequence。
所以 terminal selected structure 也没有成为正式 generation evidence。

官方普通 generation 教程本身采用“先 sequence generation，再单独 structure generation”的拓扑，
见 [`esm3_generate.ipynb`](../../../../esm-tutorials/esm3_generate.ipynb)。官方 GFP 教程进一步演示了
“生成 structure token → decode/筛选结构 → structure-conditioned sequence generation → 清除旧
structure 后 refold”的链路，见 [`gfp_design.ipynb`](../../../../esm-tutorials/gfp_design.ipynb)。
这为后续把结构作为可连接的中间产物提供了第一方科学先例，但不改变当前项目尚未持久化该产物的事实。

## 对后续模块化设计的直接约束

未来可以让 Direct 与 Guided 共享一个 `GenerationOutput`，但可选结构必须至少区分：

- `absent`：本次没有结构输出；
- `prompt_passthrough`：坐标逐值保留；
- `prompt_reconstruction`：输入结构经编码/解码或标准化后重建；
- `sampled_structure`：structure track 的 mask 被模型采样；
- `independent_fold`：独立折叠模块从 sequence 重新得到的结构。

本次 live case 的分类为：

| case | 结构分类 |
| --- | --- |
| Direct，无坐标 Prompt | `absent` |
| Direct，完整坐标 Prompt | `prompt_reconstruction` |
| Guided complete denoise，无坐标 Prompt | `sampled_structure` |

`prompt_reconstruction` 和 `sampled_structure` 都可以作为 generation-time evidence，但二者不能与
`independent_fold` 混用。只有保存独立结构 identity、结构来源、生成配置和父输入 lineage，后续才可
安全实现：

1. generation structure 与 refold structure 的 RMSD/TM-score；
2. 将 generation structure 送入 ProteinMPNN、ESM3 或未来 sequence generator；
3. 再折叠所得 sequence，并与原 generation structure 比较。

## 证据与复核

[`observations.json`](observations.json) 保存：

- 日期、commit、SDK、模型和 endpoint identity；
- 所有请求配置与一次性 public call topology；
- sequence、coordinates、pTM、pLDDT、PAE 和 structure 字段事实；
- tensor shape、有限覆盖、数值摘要与 canonical SHA-256；
- Direct 输入/输出 raw RMSD 与 proper-rotation Kabsch RMSD；
- Guided raw `ForwardAndSampleOutput` 的逐轨道 token/statistics 摘要。

坐标 canonical hash 定义为：shape JSON、finite mask 与按 6 位小数归一化的 little-endian float64
有限值按 C order 拼接后计算 SHA-256；NaN payload 不参与 identity。RMSD 使用相同 residue index
与 atom37 index 的双方有限坐标，并在质心化后执行 proper-rotation Kabsch alignment。完整算法元数据
也写在 JSON 中。

限制：每个 case 只有一个 56-aa 样本和一次调用；没有随机种子；没有测试 partial-coordinate Prompt；
没有测量重复采样方差；没有访问 Biohub 服务端实现。因此结果是 dated API/output evidence，不是模型质量
或统计泛化结论。
