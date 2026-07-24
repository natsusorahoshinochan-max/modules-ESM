# Biohub / ESM 产品合同补充

状态：已接受的规范性产品补充

日期：2026-07-21

## 1. 范围与权威

本文记录固定 Biohub v1 快照没有表达、但本产品已经接受的 ESM 模型身份、
catalog 边界和当前能力裁决。它是由
[`target-contract-index.md`](../../target-contract-index.md) 路由的
provider-specific 规范性补充，服从该索引分配给各目标合同的权威边界。

Biohub 相关事实按下列三层解释，不得混用：

1. 带日期的[真实运行观测](observed-runtime-overlay.md)决定当前 Biohub 模型事实上支持什么；
2. 目标合同与本文决定本项目公开、规划和验收什么；产品合同不得承诺当前真实运行观测已经否定的能力；
3. 不可变的 [`v1/`](v1/README.md) 快照只证明其明确发布的 endpoint 和请求 wire
   事实，不能单独证明某个当前模型已经实现相应能力或会返回某个响应字段。

若旧产品设计、静态请求 schema 与当前真实运行观测冲突，以当前真实运行观测为事实依据，
并同步修改本地产品合同、实现和测试。带日期的观测本身不是长期产品合同；观测变化时，必须先
更新 dated evidence 并重新裁决目标合同，不能由 adapter 暗中扩大或缩小产品能力。

## 2. 产品模型身份

初始 ESM3 产品模型集合为：

| 规范 endpoint | model ID | 产品身份 |
| --- | --- | --- |
| `biohub` | `esm3-medium-2024-08` | 公开 Biohub 产品模型 |
| `biohub` | `esm3-open-2024-03` | 公开 Biohub 产品模型 |
| `local_open` | `esm3_sm_open_v1` | 本地 open-weight 产品模型 |

Biohub ESMFold2 的严格单链折叠模型集合为：

- `esmfold2-fast-2026-05`；
- `esmfold2-2026-05`。

这里的“公开 Biohub 产品模型”是产品可支持性裁决，不等于某次部署当前已经 ready。Biohub 的
实际可用性仍取决于规范 endpoint 的授权与 readiness；本地模型的实际可用性仍取决于受控
runtime 与 readiness。`esm3-medium-2024-08` 不建立 private-entitlement 产品分支。

## 3. ESMFold2 严格单链产品合同

两个 ESMFold2 产品模型采用同一份严格单链合同：

- 每个合法请求恰好执行一次 Biohub `/fold`；
- 可选公共控制只有 `include_pae` 和 `include_embeddings`；
- `include_embeddings=true` 只承诺 `embedding_pair_pooled`；
- 合法报告组合只有 none、PAE、embeddings、PAE + embeddings；
- 不公开 distogram，也不承诺 `embedding_sequence`；
- 不把 `/fold_all_atom` 作为严格单链产品路由、fallback 或重试目标。

`/fold_all_atom` 出现在固定 v1 快照中，只能证明该端点及其请求 wire 被 Biohub 文档发布过；
这不自动把它变成本项目当前产品能力。相同地，`/fold` 请求 schema 中出现
`include_distogram`，也不能推导当前两个 ESMFold2 模型已经实现 distogram。当前裁决的实测
依据见[真实运行观测](observed-runtime-overlay.md#2-esmfold2-fold-观测矩阵)。

## 4. ESM3 structure 与本地上游风险

Biohub ESM3 structure generation 的产品能力不因旧验收器误判而收窄。SDK 自动带入的
`invalid_ids=()` 和 `condition_on_coordinates_only=true` 是 structure track 的默认 no-op
evidence，不是本项目公开拥有的 structure 控制项；验收器只应在值精确等于这些默认值时进行
边界正规化。非默认值仍必须保留并导致 evidence mismatch。

本地 open-weight ESM3 的 structure track 中，`cosine + entropy` 与其他合法采样组合具有完全
相同的 Capabilities、Intent、Preview、Plan 和运行时调用路径。针对固定 SDK 3.3.0 与 MPS 的
已知上游采样失败，只能在验收证据中精确登记为 `expected_upstream_failure`；产品实现不得为它
增加 fallback、替换采样策略、切换设备、重试或专用功能分支。若后续上游版本使该组合成功，
验收应要求删除过期登记，而不是继续掩盖成功。

### 4.1 ESM3 generation output lineage

带日期的
[`2026-07-21 ESM3 generation output study`](research/2026-07-21-esm3-generation-outputs/report.md)
对 `esm3-open-2024-03` 与 `esm3-medium-2024-08` 冻结了以下 Provider 事实：

| live operation | Prompt | response structure fact | 产品 classification 上限 |
| --- | --- | --- | --- |
| Direct `generate(track="sequence")` | 无 coordinates | coordinates、pTM、pLDDT、PAE 均缺席 | `absent` |
| Direct `generate(track="sequence")` | 完整 1PGA coordinates | 返回 coordinates/pTM/pLDDT；对齐后 backbone 与输入极近，且未采样 structure track | `prompt_reconstruction`，不能声称独立 structure sampling |
| 单次 Guided complete denoise `forward_and_sample(sequence + structure) -> decode` | 无 coordinates | 明确采样 sequence/structure tokens，decode 后产生新 coordinates | `sampled_structure` evidence；但单次 denoise 不等于完整 Guided loop |

因此，公共 Generation Result 可以为 Direct/Guided 使用相同的 optional StructureData 类型，
但必须同时携带来源 classification 与 parent lineage：

- Direct 无坐标 Prompt 固定为 structure absent，不得因 SDK response type 能容纳 coordinates 而
  补造结构；
- coordinate-conditioned Direct present structure 只按 Source Structure + Prompt binding +
  terminal sequence 的 `prompt_reconstruction` 发布；坐标 hash 改变、frame 改变或 atom coverage
  改变都不足以升级为 `sampled_structure`；
- Guided 只有完整产品循环实际选中的 terminal denoise 结构才可按 `sampled_structure` 发布；
  未选 proposal 和本研究的孤立 denoise 本身都不能伪装成最终公共 Candidate evidence；
- `prompt_passthrough` 只属于研究期分类词汇，当前公共 Generation Structure Evidence 不公开
  该 classification，也不能用于这六个 live cases；
- `independent_fold` 只属于 Folding Backend 的 FoldOutcome，不属于 generation classification。

任何 present generation structure 都必须与 terminal sequence/ResidueAxis 一致，并使用独立于
FoldOutcome 的 `canonical-pdb-v1` data identity、operation/model/endpoint provenance 与 Artifact
role。它不替代每个 admitted sequence 的独立 Folding，也不在 Fold failure 时构成 fallback。

本节的 dated fact 只直接覆盖上述两个 Biohub model。`local_open` 或新增 model 要公开同类结构
输出，必须通过同一分类合同和对应 Provider/Adapter conformance evidence；共享 output type
不能替代真实能力证据。

## 5. structure metric 边界

公共科学合同中的 pTM 是无量纲 scalar，PAE 是与目标序列残基一一对应的 `(L,L)` 矩阵。
adapter 只允许以下精确正规化：

- 本地 SDK pTM `(1,)` 转为 scalar；
- 本地 SDK PAE `(1,L+2,L+2)` 去除 batch 轴及首尾特殊 token，转为 `(L,L)`；
- 已经是 scalar 或 `(L,L)` 的结果原样保留。

不得使用通用 `squeeze`，也不得猜测转换 `(1,1)`、`(1,L,L)`、`(L+2,L+2)` 或其他未知 shape；
这些结果必须 fail closed。这里保留的是产品科学边界上的窄正规化，不是泛化的本地/远端兼容层。

## 6. Catalog 与可扩展性边界

公共请求中的 `model` 是非空字符串，不冻结为只含上述模型的封闭 enum；但这不表示调用者可以
提交任意模型。当前部署可选择的 endpoint、model 与 operation 组合只来自后端发布的
Capabilities 和同一份 transport-neutral catalog。

Catalog 必须显式声明：

- model ID；
- 支持的 transport / endpoint；
- 支持的 operation 与控制合同。

新增模型需要增加受控 catalog 条目以及相应的离线合同和真实 provider 验收证据；只有新增
transport 时才需要新的 transport adapter。不得按 model ID 前缀猜测 transport，不得因 schema
使用字符串就接受 Capabilities 未声明的模型，也不得为每个新模型复制 runner、adapter 或公共
请求类型。Catalog 的可扩展性是服务端受控扩展边界，不是用户可编排的动态 provider/plugin
系统。

## 7. Biohub v1 快照边界

[`v1/`](v1/README.md) 是不可变的上游参考快照。不得为了表达本产品的新增裁决而修改其抓取
内容、manifest、机器可读定义或 endpoint 文档。

该快照只在其明确覆盖的请求 wire 范围内作为证据，包括 method/path、鉴权与媒体类型、请求
字段、枚举、范围和默认值。快照没有发布响应 body schema，因此不能据此推断响应字段、shape
或解析合同。本文补充产品模型身份、ESMFold2 能力与 catalog 裁决，但不把这些裁决伪装成 v1
快照的原始发布内容，也不扩大快照的证据范围。
