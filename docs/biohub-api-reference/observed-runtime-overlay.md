# Biohub / ESM 真实运行观测

状态：按历史 revision 冻结的非规范性运行 Evidence；不定义当前产品能力

初始观测日期：2026-07-20；最近补充：2026-07-23

运行边界：当时仓库锁定的 ESM SDK 3.3.0、当时 Biohub v1 部署和本地 MPS runtime

## 1. 如何使用本文件

本文件记录特定日期、Git revision、model、SDK 和 device 下实际观察到的行为，只用于解释
当时的 Acceptance Evidence 与 Provider/SDK 集成调查。它不能修改 Biohub 官方 Provider
contract、active Catalog、Method、Execution Binding 或 Adapter translation。当前规范性产品
选择见 [Biohub / ESM 当前产品合同](product-contract-supplement.md)。

不可变的 [`v1/`](v1/README.md) 快照仍用于证明其明确发布的 method/path、请求字段和默认值等
wire 事实。新的运行结果若与当前合同不一致，应先作为集成问题调查；不能根据一次成功或失败
加入兼容 parser、expected-failure 产品分支、retry、fallback，或暗中改变 Catalog capability。

## 2. ESMFold2 `/fold` 观测矩阵

对 `esmfold2-fast-2026-05` 和 `esmfold2-2026-05` 分别直接调用 `/fold`，两个模型的结果一致：

| 请求组合 | 当前结果 | 观察到的可选输出 |
| --- | --- | --- |
| none | 成功 | structure、pLDDT、pTM |
| PAE | 成功 | PAE，shape 为 `(L,L)` |
| embeddings | 成功 | `output_embedding_pair_pooled`，shape 为 `(L,256)` |
| PAE + embeddings | 成功 | PAE 与 `output_embedding_pair_pooled` 同时存在 |
| distogram | HTTP 422 | 当前模型明确未实现该请求能力 |

在两个模型的 embeddings 请求中，`output_embedding_sequence` 均未提供；观察值为 `None`。
因此，“embeddings”当前只能支持 pair-pooled embedding，不能扩展解释为 sequence embedding。

这组观测否定了旧产品设计中的两个推论：请求 schema 出现 `include_distogram` 不代表当前模型
实现 distogram；静态参考出现 `/fold_all_atom` 也不代表严格单链产品请求应路由到该端点。

### 2.1 SDK 3.3.0 的严格单链渲染缺陷

真实 embeddings 与 PAE + embeddings 请求中，Biohub `/fold` 已成功返回 coordinates 和
`output_embedding_pair_pooled`。但 SDK 3.3.0 同时把响应中的 `residue_index` 解码为浮点 tensor；
其 `ESMProtein.to_pdb_string()` 经过 complex renderer 时，会因 Biotite `res_id` 的整数/浮点
annotation 冲突抛出 `ValueError: Cannot cast 'res_id' ...`。这发生在成功响应的本地渲染阶段，
不能解释为 Biohub embeddings 能力缺失。

ESMFold2 产品合同是严格单链，因此 adapter 使用 SDK 自身的 `to_protein_chain()` 单链视图，
补全 oxygen 后再调用该 chain 的 PDB renderer。该路径不修改 coordinates、PAE 或 pair-pooled
embedding，不猜测未知 shape，也不引入 `/fold_all_atom` 或第二次 provider operation。

## 3. ESM3 structure 的 Biohub 观测

Biohub structure generation 的 6 个实测 case 都已完成 provider 调用并产生 structure 与 fold
outcome。旧验收结果中的 6 个 failure 发生在调用成功后的 diagnostics evidence comparison，
不是 Biohub structure 功能缺失。

误判来源是 SDK 为 structure generation 自动记录：

- `invalid_ids=()`；
- `condition_on_coordinates_only=true`。

这两个值不是本项目 structure Plan 公开拥有的控制项。旧 validator 仍将它们与 Plan 做严格
字段比较，因而把成功调用判为 evidence invalid。产品能力无需收窄；验收边界只需在 structure
track 中对这两个精确 no-op 默认值做正规化，非默认值仍视为证据不一致。

## 4. 本地 structure metric shape

在相同 SDK 3.3.0 的本地 ESM structure 路径中观察到：

- 原始 pTM shape 为 `(1,)`；
- 长度为 `L` 的目标序列对应原始 PAE shape `(1,L+2,L+2)`，额外位置来自 batch 轴和首尾特殊 token。

Biohub 边界已经提供产品所需的 pTM scalar 和 PAE `(L,L)`。为了让本地与远端遵守同一科学
合同，本地只需要执行 `(1,) -> scalar` 和 `(1,L+2,L+2) -> (L,L)` 两种精确正规化；该观测
不支持通用 squeeze 或对其他 shape 做猜测兼容。

## 5. 本地 MPS `cosine + entropy` 上游失败

下列精确组合在仓库锁定的 ESM SDK 3.3.0 中稳定进入上游采样器后失败：

| 维度 | 观测值 |
| --- | --- |
| endpoint / model | `local_open` / `esm3_sm_open_v1` |
| device | MPS |
| track | structure |
| schedule / strategy | `cosine` / `entropy` |
| 上游调用链末端 | entropy sampling mask 中的 `topk(...)` |
| 异常 | `RuntimeError: selected index k out of range` |

对照观测中，`linear + entropy` 和 `cosine + random` 均成功，因而问题被限定在上述精确组合，
而不是 entropy 或 cosine 的一般产品能力缺失。这是上游 SDK 任务：本项目不修改产品合同或运行
路径，只在真实 local-open 验收中运行该 case，并将匹配相同 SDK、设备、模型、track、配置和
异常签名的结果记录为 `expected_upstream_failure`。如果该 case 后续意外成功，登记应被视为过期。

## 6. 2026-07-21 Biohub 网络恢复后观测

更换本机网络后，ESM Direct、Guided、structure 与 ESMFold2 的正式 readiness 均恢复为
`ready`。随后在提交 `08319c0` 上进行了两次相互独立的 26-case Biohub profile，证据根分别为
`var/runs/v2-provider-regression/biohub/run_network_changed_20260721_SlP8zA` 和
`var/runs/v2-provider-regression/biohub/run_network_changed_retry2_20260721_0fHoyJ`：

| Track | 第一次 | 第二次 | 结论 |
| --- | ---: | ---: | --- |
| Direct | 6/6 | 6/6 | 两次全部成功 |
| Guided | 5/6 | 5/6 | 两次各有一个不同 case 在 provider generation 阶段失败 |
| Structure | 6/6 | 6/6 | 两次全部成功 |
| ESMFold2 | 8/8 | 8/8 | 两模型、四种报告组合全部成功且使用单次 `/fold` |

第一次失败的是 `esm3-medium-2024-08` Guided 默认控制 case；第二次失败的是
`esm3-open-2024-03` Guided `linear + random` case。两次均在 Candidate admission 与 Folding
之前形成 `generation_provider_failed` / `GuidedProviderFailure`，持久化层正确保存终态和安全
诊断，没有产生替代 Candidate、重试 Folding 或 fallback。两个失败 case 各自在随后精确、
隔离的单 case 重跑中成功。

两个精确重跑成功都是交互式诊断观测，没有 durable official root，不能与上述 profile
拼接成通过证据。失败位置漂移且精确重跑成功，支持“远端 Guided generation 瞬时失败”，不支持收窄任一
model/schedule/strategy 的产品能力。本项目不为这些 case 增加 fallback，也不把它们登记为
`expected_upstream_failure`；该登记仍只适用于第 5 节的本地 MPS 精确组合。

## 7. 2026-07-23 当前实现的 Biohub-only 观测

更换网络环境后，在当前模块化实现提交
`1972d38f2b69b950cc9b89718b9d245c372f1264`、tree
`25b6b9c4f251f3239401db02357f21a5a5b6227a` 上进行了仅包含 Biohub 的直接验收。
本次没有使用会先运行 `tests/unit/v2` 的 `official-regression biohub` 包装命令，而是直接执行
`tests/acceptance/live/test_biohub_smoke.py` 中构成正式 Biohub profile 的七个精确 selector；
因此没有触发 unit、local 或 local-open。

运行前 readiness 中四条必需远端分支均为 `ready`：

| 必需分支 | 结果 |
| --- | --- |
| `esm_direct` | ready |
| `esm_guided` | ready |
| `esmfold2` | ready |
| `esm_fold` | ready |

26 个参数化远端 case 的结果为：

| Track | 通过数 | 结论 |
| --- | ---: | --- |
| Direct | 6/6 | 两个 ESM3 模型的矩阵和默认控制全部成功 |
| Guided | 6/6 | 两个 ESM3 模型的矩阵和默认控制全部成功 |
| Structure | 6/6 | 两个 ESM3 模型的矩阵和默认控制全部成功 |
| ESMFold2 | 8/8 | 两模型、四种报告组合全部成功 |

Pytest 最终报告为 `26 passed, 32 warnings in 2095.02s`，无 failure、error 或 skip。证据根为
`var/runs/v2-provider-regression/biohub/biohub_only_network_changed_20260723_x0sCzJ`，其中
`run-identity.json`、`readiness.json` 和 `pytest-results.xml` 均为持久化证据；JUnit 可独立证明
26 tests、零 failure/error/skip。`32 warnings` 汇总以及使用本机 Biohub 与 Hugging Face 密钥
原始字节完成的无泄漏扫描属于交互式终端观测，该直接运行根没有 command transcript 或
`secret-scan.log`，不得把这两项提升为 durable official evidence。

这次结果同时覆盖了 2026-07-21 两次 profile 中各自瞬时失败的 Guided case。结合换网前
`authorization_probe_unavailable`、换网后 readiness 全绿及完整 `26/26`，旧失败最符合网络环境
或远端瞬时条件，而不是产品能力缺失；但仅凭这些观测不能排除恰好同时发生的 provider 恢复。

## 8. 证据限制

以上结果只支持列出的日期、模型、SDK、设备、请求组合和输出字段。它们不能证明未执行的组合，
也不能替代一个新 Git tree 自己的 fresh official regression。旧的 partial run、单独 profile 或
精确重跑都不能组合成 `completion_eligible=true` 的发布证据。

提交 `816f31b` 的 `run_20260720_171825_18288` 曾在其自身 tree 上取得 local-open `12 + 1`、
Biohub `26/26` 与 `completion_eligible=true`；它现在只是不同行为基线的历史证据。当前实现
提交 `1972d38` 已取得直接 Biohub-only `26/26`，项目负责人也已接受现有离线、local、
local-open 与 Biohub 证据，并决定不再运行长时间的组合 `all`。这是一项项目收尾判定，不会把
不同根目录拼装为发布证据，也不声称存在新的 current-identity
`completion_eligible=true` summary；该治理决定显式覆盖已退休项目书的单一 fresh-root
项目完成门，不表示历史门本身已经通过。当前验证状态和严格发布规则见
[`backend-verification.md`](../backend-verification.md)。
