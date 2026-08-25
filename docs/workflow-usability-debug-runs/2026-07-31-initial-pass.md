# Workflow usability debug：2026-07-31 首轮正式测试

状态：首轮正式测试完成；只记录缺口，未实施修复。

## 1. 执行边界与快照

- 初始 Git HEAD：`e4173bb7884ade54021bc5170e4b9eacd28a1a0e`；正式测试开始时工作树干净；
- FrozenCatalog contract digest：
  `sha256:f2c91338b2679d2c06f3b6d68a1c576cef6e2d2fec3ab8fb86aa8850518b95e9`；
- public protocol digest：
  `sha256:a74aaac7f7b6c6b08b72110d69f349e005fc9785512b563091a273162f977297`；
- 当前 React 前端按用户在正式测试开始后的澄清排除在测试范围外；本轮唯一验收
  surface 为 public v2 REST/WebSocket protocol；
- 未安装依赖、未下载或替换模型、未修改 credential、环境变量或 device；
- 不使用私有 Python 对象、外部序列转换、外部评分或 Binding fallback 补齐 Workflow。

## 2. 结果总览

| 顺序 | 输入 | Phase 1 | Phase 2 | 顶层状态 | 最早缺口 |
|---:|---|---|---|---|---|
| 1 | `1PGA-75-gen1_0690.pdb` | compile structured rejection | blocked | `SAFELY_BLOCKED` | `composition_gap` |
| 2 | `2EMO.pdb` | authoring structured rejection | blocked | `SAFELY_BLOCKED` | `contract_gap` |
| 3 | `5G53.pdb` | authoring structured rejection | blocked | `SAFELY_BLOCKED` | `contract_gap` |

## 3. Finding `WFDBG-1PGA-001`

- 输入：`1PGA-75-gen1_0690.pdb`；
- Project ID：`daaca40f-8232-4c20-90e1-a45c324f450b`；
- Workflow revision：save 后为 `1`，relock 后为 `2`；
- Run ID：未创建；compile 前结构化阻断；
- 预期理论合同：从输入 PDB 在 Workflow 内提取准确的 75-aa sequence，保持
  structure-to-sequence lineage，并把同一个 sequence Candidate 分别交给
  `folding.fold.esmfold2_remote@2.1.0` 与
  `folding.fold.simplefold_local@2.1.0`；
- 实际观察：`structure_transform.extract_sequence.direct@2.1.0` 输出 nominal
  `protein.sequence@2.1.0`，而 `folding.fold@2.1.0` 的必需输入
  `sequence_candidates` 要求 `candidate.collection@2.1.0`。当前 Catalog 没有已锁定的
  lineage-preserving bridge；
- 最早失效 seam：Workflow compile，edge index `1`，目标 Node
  `fold-esmfold2`；
- public error：`compile_rejected` / `port_type_mismatch`，消息为
  `Connected Ports do not share one exact nominal Port Type`；
- 分类：`composition_gap`；
- 顶层状态：`SAFELY_BLOCKED`；
- Phase 2：blocked；没有 confidence、TM-score、RMSD 或 three-way consistency
  结论；
- provider 影响：未创建 Run，ESMFold2 和 SimpleFold Engine Invocation 均为 `0`；
- 科学解释影响：无法在 Workbench 内证明两个 folding Method 使用的是由该 PDB 派生且
  lineage 完整的同一个 75-aa sequence；导出并重新上传 FASTA 会切断本轮要求的 lineage，
  因而没有采用；
- 可复现性：同一 Project、revision 和 Workflow 的 public compile 会稳定返回同一
  `port_type_mismatch`；
- Evidence：
  `.local/verification-results/workflow-usability-debug/2026-07-31/1pga-75/maximal-prefix.workflow.json`
  以及同目录 `authoring-receipts.json`、`compile-response.json`。原始 relocked Workflow
  保持在该 Project 的 durable storage 中。

## 4. Finding `WFDBG-2EMO-001`

- 输入：`2EMO.pdb`；
- Project ID：`188d4eb6-8625-46fa-9bf1-2d676855d2df`；
- Workflow revision：未创建；public save 在准确参数合同检查时结构化阻断；
- Run ID：未创建；
- 预期理论合同：以 `prompt_authoring.prompt_from_structure.direct@2.1.0` 产生的准确
  residue layout 为权威，把合同锁定的固定集合 `A:42`、`A:44`、……、`A:222` 映射到
  ProteinMPNN 所需的零基位置，同时保持 CSH A:66 的身份语义和 layout provenance；
- 实际观察：`proteinmpnn.constraints@2.1.0` 的 `fixed_positions` 只接受零基 integer，
  public authoring surface 没有把 identity-addressed residue 集合解析到上游 runtime layout
  的合同或 preview/expression 能力。将第一个准确 residue identity `A:42` 写入参数时，服务
  返回 `compile_rejected` / `invalid_parameter`，消息为
  `node_parameters.fixed_positions.0 must be integer`；
- 最早失效 seam：public Workflow save 的准确参数合同检查，Node
  `author-constraints`；
- 分类：`contract_gap`；
- 顶层状态：`SAFELY_BLOCKED`；
- Phase 2：blocked；没有 TM-score、RMSD、pLDDT 或 Protein-Sol filter 结论；
- provider 影响：未创建 Run，ProteinMPNN、ESMFold2 和 Protein-Sol Engine Invocation
  均为 `0`；
- 科学解释影响：不能在 public Workbench interface 内证明固定位置来自该 PDB 的准确
  residue layout。手工把 PDB residue number 换算为零基索引会绕过本轮要求的显式 mapping，
  因而没有采用；
- 可复现性：同一请求连续两次稳定返回同一 Node、参数路径和 `invalid_parameter`；
- Evidence：
  `.local/verification-results/workflow-usability-debug/2026-07-31/2emo/maximal-prefix.workflow.json`
  与同目录 `authoring-response.json`。

## 5. Finding `WFDBG-5G53-001`

- 输入：`5G53.pdb`；
- Project ID：`467dec3a-e805-49f8-a629-274e17205fa4`；
- Workflow revision：未创建；public save 在准确参数合同检查时结构化阻断；
- Run ID：未创建；
- 预期理论合同：从 chain A 的 283 个 modeled standard residues 出发，保留
  `A:146→A:159` 为未解决的非目标 discontinuity，并为 `A:211→A:224` 建立三个准确的
  target layouts：8-residue shorter、12-residue numbering-implied 和 16-residue longer；
- 实际观察：`prompt_authoring.build_residue_layout@2.1.0` 只接受每条 chain 的
  `chain_id + length`，由实现构造连续编号身份，不能声明准确 target residue identity。
  shorter 分支需要的 `A:gap211_224.short.01` 至 `.08` 通过 `residue_ids` 表达时，服务返回
  `compile_rejected` / `invalid_parameter`，消息为
  `node_parameters.chains.0.residue_ids is not an allowed field`；
- 最早失效 seam：public Workflow save 的准确参数合同检查，Node
  `build-shorter-layout`；
- 分类：`contract_gap`；
- 顶层状态：`SAFELY_BLOCKED`；
- Phase 2：blocked；没有 resolved-core comparison、counterpart comparison、junction、
  clash 或 confidence 结论；
- provider 影响：未创建 Run，ESM-3 和 ESMFold2 Engine Invocation 均为 `0`；
- 科学解释影响：只提交 target length 会生成另一套连续编号身份，不能证明目标 gap、
  非目标 gap 和三个分支插入 residue 的 lineage，因此没有采用；
- 可复现性：同一请求连续两次稳定返回同一 Node、参数路径和 `invalid_parameter`；
- Evidence：
  `.local/verification-results/workflow-usability-debug/2026-07-31/5g53/maximal-prefix.workflow.json`
  与同目录 `authoring-response.json`。

## 6. 首轮结论

三个理论 Workflow 均在 public v2 interface 上得到结构化、可解释且可稳定复现的最早阻断，
因此没有 `OPAQUE_FAILURE` 或 `UNSAFE_SUCCESS`：

1. 1PGA-75 缺少 structure-derived `protein.sequence` 到 sequence
   `candidate.collection` 的 lineage-preserving composition seam；
2. 2EMO 缺少把 identity-addressed residue constraints 解析到 runtime residue layout 的
   public parameter/expression contract；
3. 5G53 缺少构建任意 identity-complete target residue layout 的 public contract。

三个 Workflow 的 Phase 2 均未开始，不能作任何 folding、设计质量、结构一致性或 loop
质量结论。因为所有阻断都发生在 Run 创建前，远程请求预算和本地模型执行预算均未消耗，
也没有触发 confirmation Run 条件。

preflight 曾确认所有锁定 Binding 均存在且 startup Availability 为 green；默认空
Environment Configuration 下的 provider/model Readiness 不通过，但本轮三个 Workflow
都没有越过更早的 authoring/compile 缺口，因此 Readiness 只保留为 preflight observation，
不升级为本轮 Workflow finding。

## 7. 2026-08-01 修复 addendum

本节只记录后续修复状态，不改写上述首轮 Evidence 的历史事实。首轮 5G53 payload 是有效的
负向 schema probe，但只列出了 8 个新增 identities，并未完整表达正确的 291-position target；
后续验收使用完整 target identity 序列。因此，`WFDBG-5G53-001` 的首轮分类仍是
`contract_gap` / `SAFELY_BLOCKED`，但不再把该 payload 描述成完整 target layout。

本次修复增加了以下 public v2 scientific seams：

1. Candidate-aware structure-to-sequence 与 chain-selection transforms、FASTA singleton root
   Candidate，以及按共同父 Candidate 创建 sibling pairing 的 producer；
2. CSH 到 `SER-HIS-GLY` parent span 的显式、类型化 atom mapping；未归一化 CSH 仍在
   structure-to-Prompt 边界 fail closed；
3. ProteinMPNN identity-addressed constraints 与唯一 Adapter
   `ResidueIdentity → provider one-based position` 映射，并把完整映射保留在 Candidate
   provenance；
4. identity-addressed deterministic whole-Prompt insertion，保持所有 283 个 5G53 chain A
   modeled identities 与原始 tracks，并生成 291/295/299 三个目标；
5. ProteinMPNN scientific call seed 只绑定配置 seed、结构 content digest 与稳定 parent
   slot，不再受 Candidate Result Identity 影响。

对应 public Workflow 回归已经断言：2EMO Prompt 恢复为 224 residues，包含
`A:65/A:66/A:67`；5G53 三个 target 均保留 `A:292–A:312`、保留
`A:146→A:159` 非目标 discontinuity、只在 `A:211→A:224` 插入 8/12/16 个 identities，
且 ResidueMap 为 283 matches、零 deletes 与准确 insertion 数。

真实 ProteinMPNN `v_48_020`（锁定 source revision `8907e667` 与 checkpoint SHA-256）
验收使用规范化后的实际 `examples/v2/structures/2EMO.pdb`，返回一条完整 224-aa sequence 与一个有限 native
score；`A:65/A:66/A:67` 固定 parent span 保持为 `SHG`。验收同时确认 provider 的几何
有效 mask 不再被误用作输出 sequence layout mask：缺少完整 backbone 的固定 residue 会按
输入身份保留，而同一位置若被声明为 designable 则明确 fail closed。
