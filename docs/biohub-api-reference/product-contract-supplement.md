# Biohub / ESM 当前产品合同

状态：当前规范性产品选择

日期：2026-08-20

## 1. 范围与事实 owner

本文只解释 Protein Workbench 当前如何选择和使用 Biohub / ESM 能力，不建立第二套
Provider、Catalog、Method 或科学合同。

相关事实由以下 owner 分别持有：

1. Biohub 官方 API specification 与仓库固定的官方 ESM SDK revision 定义 Provider
   request/response representation 和官方 operational outcomes；
2. active Catalog 中的 Method 与 Execution Binding 定义 Workbench 当前公开的 model、
   operation、固定配置、随机性和科学解释；
3. concrete Adapter 在 Provider seam 实现唯一的 Workbench value ↔ Provider representation
   翻译；
4. 带 Git revision 的真实 Provider Acceptance Evidence 只证明该 revision 按上述合同执行过，
   不扩大、缩小或覆盖官方 Provider contract 与 active Catalog。

不可变的 [`v1/`](v1/README.md) 快照保留其抓取时官方页面明确发布的 method、path 和
request wire 事实。快照未包含的 response schema 不从历史运行值反向推断；仓库固定 SDK、
active Method/Binding 和官方规范共同决定当前唯一翻译。

## 2. 当前远程模型与操作

当前 active Catalog 只公开以下 Biohub service model identities：

| Module Package | model ID | 当前操作 |
| --- | --- | --- |
| `esm3` | `esmc-600m-2024-12` | encode、logits |
| `esm3` | `esm3-medium-2024-08` | sequence、structure、paired generation |
| `esm3` | `esm3-open-2024-03` | sequence、structure、paired generation |
| `folding` | `esmfold2-fast-2026-05` | strict single-chain fold |

精确 Node Type、Port Type、Method、Execution Binding、parameter 和 output contracts 由
[`modules/esm3`](../../modules/esm3/package.py) 与
[`modules/folding`](../../modules/folding/package.py) 的 active registrations 拥有。本文的
表格帮助维护者定位当前产品选择，不允许独立于 active Catalog 增加 model 或 operation。

Availability 只描述 startup 时结构性 prerequisites；Readiness 只在 Cache miss 或 bypass
实际进入所选 Provider 前检查 exact Binding。二者都不自动选择另一个 model、route 或
operation。

## 3. Provider Adapter seam

Biohub Adapter 只执行以下职责：

1. 接收已经 admitted 的 provider-independent Workbench values；
2. 按官方规范和 exact Method 构造唯一 request；
3. 调用 Binding 固定的 endpoint、model 和 SDK；
4. 假定 conforming request 获得 conforming response，并执行文档规定的唯一确定性翻译；
5. 记录 exact Method、model、translation、randomness 和 Engine Invocation provenance；
6. 让官方 operational error 按当前 Run Evidence 合同正常传播和终止。

Adapter 不根据 observed value 猜测 schema，不为 hypothetical malformed response 建立
shape/type/range 兼容矩阵，不 cross-check Provider，不改写 response，不切换 endpoint、model
或 device，也不加入未由官方合同和 Method 明确拥有的 retry 或 fallback。

如果固定官方合同、固定 SDK 与当前翻译不再一致，这是需要 fail fast 并重新裁决合同的
Provider/Adapter 集成缺陷；不能通过同时接受多种猜测表示来掩盖。

## 4. 当前 ESMFold2 合同

`folding.fold.esmfold2_remote` 只调用 `esmfold2-fast-2026-05` 的官方 `/fold` operation。
当前 Method 固定完整 confidence 请求配置，包括：

- `include_pae=true`；
- `include_embeddings=false`；
- exact sampling steps、loops、dropout 与 mask percentage。

这些值是 Method identity，不是用户参数。Adapter 不调用 `/fold_all_atom`，不公开
distogram/embedding 选择，也不在 fold failure 时切换 model、endpoint 或配置。

pLDDT、pTM、PAE 与 prediction residue axis 的 canonical scientific semantics 服从
[ADR-0020](../adr/0020-canonical-plddt-contract.md) 和
[`structure_prediction` 两阶段 seam](../protein_workbench_architecture.md#101-结构预测置信度的两阶段-seam)。

## 5. 当前 ESM-3 generation 合同

每个 medium/open generation Binding 固定 exact model、operation、sampling configuration
和 randomness contract。公共 Node parameters 只表达 Node Type 声明的科学选择；SDK 的
`condition_on_coordinates_only`、`invalid_ids` 等 Method-fixed representation facts 不成为
额外用户控制项。

Generation output 的科学身份由 `esm3` Module Interface 拥有：

- structure-track sampling 产生的结构使用 `sampled_structure` classification；
- coordinate-conditioned sequence generation 返回的来源结构只使用
  `prompt_reconstruction` classification；
- 纯 sequence output 不补造 structure、Prediction Key 或 confidence fact；
- present structure 必须与 terminal sequence、Prediction Key、structure digest、prediction
  residue axis 和 exact Method 保持一一关联。

真实运行中观察到 coordinates、confidence 或其他字段，不能自行升级 classification、补造
Candidate、扩大当前 output contract，或替代独立 Folding Method。

## 6. 运行证据的职责

[真实运行观测](observed-runtime-overlay.md)和
[带日期研究包](research/README.md)是绑定日期、Git revision、SDK、model、device 与 request
组合的历史 Evidence。它们用于解释一次 acceptance 或集成调查，不定义 current capability。

新的运行结果若与当前合同不一致，应先作为 Provider/SDK 集成问题调查。只有官方合同或当前
产品科学选择确实改变时，才原子修改 active Method/Binding、Adapter、tests、examples 和当前
文档；不从一次成功或失败运行中生成 compatibility parser、expected-failure 产品分支或
fallback route。

当前真实 Provider gate、source-bound Workflow 与 Acceptance Campaign 定义见
[`backend-verification.md`](../backend-verification.md)。
