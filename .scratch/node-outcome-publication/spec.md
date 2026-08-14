# Atomic Node Outcome Publication and Typed Value Persistence

**Status:** ready-for-agent

## Problem Statement

Protein Workbench 的合法 Typed Output 已经可以大于 Run Evidence Ledger 当前允许的
单 fact 4 MiB。使用真实注册 ESM-3 Port codecs、291 residues、2 samples 的
provider-free reproduction 中，必需 outputs 为 3,365,804 bytes，加入 reconstruction
后为 3,582,657 bytes，而 reconstruction 与两组含 PAE 的 confidence collections 为
6,721,503 bytes。最后一种合法科学输出在写入任何 output fact 之前失败，并以
`evidence_unavailable` 结束。

这不只是容量问题。当前 Node Outcome Publication 把 Operation terminal、Artifact
facts、Typed Outputs、Node terminal 和 Node disposition 分成多次独立 durable writes。
worker 可以已经结束，Run 却继续公开为 `running`；重启会把 Operation 未完成、Operation
成功但 publication 未完成、Node 已成功但 Run Closure 未写入等不同 durable prefixes
统一压成 `interrupted`。Artifact bytes 还可能先于其 Ledger evidence 落盘，形成没有
公开所有者的文件。Result Cache 同时复制 base64 canonical values，并承担它不应承担的
Result Identity 权威角色。

对科学用户而言，这意味着一个完全合法、科学语义完整的 ESM-3 结果可能因为 evidence
表示方式而丢失；一个已经完成的 Run 可能显示错误状态；重启、取消和 Cache replay 可能
无法忠实说明真正发生了什么。不能通过删除 PAE、删除 reconstruction、降低 sample 数、
把 Typed Output 冒充 Artifact 或提高单 fact 上限来规避这些问题。

原始 5G53 Provider exception 没有被 durable evidence 记录。因此上述 6,721,503-byte
reproduction 是已确认的充分触发条件和历史现象的最高可信解释，但不是该历史 Provider
response 确实包含两组 PAE 的法证证明。

## Solution

Protein Workbench 将把 admitted canonical Port values 先写入 Project-scoped immutable
content-addressed objects，再通过一次物理 Run Evidence Ledger transaction 原子发布一个
Node 的全部 logical facts。Run Projection 只公开小型 Typed Output descriptors；客户端按
需通过 Run-scoped route 获取单个 canonical value。Artifact 继续拥有独立的 nominal Port
语义和 public retrieval contract，只与 Typed Output 共享物理 immutable byte store。

Operation Attempt 只描述 implementation、Engine Invocation、documented provider
translation、normalization、output admission 和 artifact contract processing。以上完成后
Operation 可以是 `succeeded`；object persistence、Result Identity comparison 或 publication
失败时，Node Execution Attempt 可以独立失败，而不能倒写 Operation 结果。Node
publication、Run Closure、restart reconciliation 和 cancellation 都从 durable prefix 推导
真实状态。

整个实现遵守仓库的信任模型。每个 contract-owning boundary 只验证一次，Core 内部随后
信任 admitted values 和已解析 contracts。Adapter 信任官方 Provider contract，不猜 schema、
不修复 response、不交叉验证 Provider、不增加 fallback。持久层只保留 durable write、
content identity、causal evidence 和防止意外数据丢失所需的检查。当前代内部不变量违反时
fail fast；不加入重复检查、宽泛 catches、catch-and-continue、静默降级、隐藏 retry、
authentication、authorization、sandboxing 或 adversarial hardening。

## User Stories

1. 作为科学用户，我希望合法的大型 Typed Output 能完整发布，以便科学结果不受 Ledger fact 大小影响。
2. 作为 ESM-3 用户，我希望 reconstruction、两组 confidence collections 和全部 PAE 同时保留，以便 publication 不改变科学合同。
3. 作为 Workflow 作者，我希望声明的 `num_samples=100` 仍可执行，以便存储表示不会暗中缩小 Node 参数合同。
4. 作为科学用户，我希望 Candidate、Prediction Key、Prediction Confidence Fact、lineage、Method 和 Port digest 原样保留，以便重构不改变解释。
5. 作为科学用户，我希望一个成功 Node 的所有 Typed Outputs 和 Artifacts 同时可见，以便不会观察到部分 publication。
6. 作为科学用户，我希望一个失败 Node 不公开任何 output，以便 downstream Node 不会消费半发布结果。
7. 作为科学用户，我希望 Engine Invocation 成功后发生的 decode 或 admission 失败仍被解释为 Operation 失败，以便 evidence 保留真实因果。
8. 作为科学用户，我希望 Operation 已完成而 object publication 失败时 Operation 仍为 `succeeded`，以便 publication failure 不伪装成 scientific execution failure。
9. 作为科学用户，我希望 Result Identity conflict 与 Cache storage failure 分开，以便科学身份不依赖优化层。
10. 作为科学用户，我希望同一 Result Identity 只能对应同一 canonical result manifests，以便可重复结果不会静默分叉。
11. 作为科学用户，我希望相同 canonical result 可以在不同 Runs 中再次发布，以便重复执行和 replay 保留同一科学身份。
12. 作为科学用户，我希望 Cache 缺失只损失性能而不改变 Node outcome，以便 evidence 不依赖 Cache availability。
13. 作为科学用户，我希望 Cache replay 保留原 producer provenance 和当前 Run materialization，以便来源与本次可见性都可审计。
14. 作为科学用户，我希望 Cache replay 不制造 Operation Attempt 或 Engine Invocation，以便 evidence 不声称不存在的执行。
15. 作为科学用户，我希望 Cache index 只引用 immutable objects，而不再复制 base64 values，以便容量和身份表示一致。
16. 作为前端用户，我希望 Run Projection 在大型 outputs 下仍保持有界，以便打开 Run 不会重新传输全部科学值。
17. 作为前端用户，我希望看到每个 Typed Output 的 Port Type、aggregate digest、value count、Result Identity 和 provenance，以便先理解结果再选择 materialization。
18. 作为前端用户，我希望按 Node、output Port 和 value index 获取一个 exact canonical value，以便只加载当前要检查的数据。
19. 作为前端用户，我希望 retrieval 返回 canonical bytes、size 和 digest，以便客户端能准确保存或解释该值。
20. 作为前端用户，我希望 Typed Output retrieval 和 Artifact retrieval 保持不同接口，以便 nominal Port 语义不会混淆。
21. 作为前端用户，我希望 WebSocket 只传 lifecycle facts，以便大型 PAE 或 Candidate collections 不进入事件流。
22. 作为前端用户，我希望 logical facts 保留连续序号，以便 transaction 化不会破坏 cursor 和 replay 语义。
23. 作为前端用户，我希望一个 transaction 的 public events 只在整组 durable 后出现，以便 live stream 不暴露中间态。
24. 作为前端用户，我希望 worker 已结束但 evidence 无法写入时收到 `evidence_unavailable`，以便界面不永久显示 `running`。
25. 作为前端用户，我希望 Cancel Run 能区分活跃 worker 与已结束但未闭合的 worker，以便 cancellation receipt 真实。
26. 作为前端用户，我希望 restart 后完整成功的 Run 恢复为 `succeeded`，以便 restart 本身不会污染科学结果。
27. 作为前端用户，我希望真正未完成的 Engine Invocation 在 restart 后成为 `outcome_unknown`，以便系统不猜远端 outcome。
28. 作为前端用户，我希望从依赖 disposition 推导 blocked 或 interrupted Nodes，以便 recovery 反映 durable causality。
29. 作为前端用户，我希望所有 Node 成功且无需 Selection 时 Run 能正常 closure，以便缺失旧 Run terminal 不会强制 `interrupted`。
30. 作为前端用户，我希望所需 Selection conclusions 可由 committed values 重建，以便 Run Closure 写入失败后仍可诚实恢复。
31. 作为前端用户，我希望 Selection failure 与 Run failure 原子出现，以便不会看到 terminal Run 缺少 Selection 结论。
32. 作为前端用户，我希望 `restart_reconciliation_started` 只表示 audit event，以便它不决定 Run status。
33. 作为运维者，我希望 immutable objects 在 Ledger commit 前 durable，以便 committed descriptors 永远不会指向尚未发布的 staging bytes。
34. 作为运维者，我希望 object presence 不产生 public visibility，以便未提交对象没有歧义。
35. 作为运维者，我希望无引用对象可安全回收，以便 publication failure 不永久占用磁盘。
36. 作为运维者，我希望共享 content-addressed object 不因一个 Run cancellation 被删除，以便其他 committed Runs 不受影响。
37. 作为运维者，我希望 GC roots 只来自 committed Ledgers、valid Cache indexes 和 active staging ownership，以便磁盘所有权可以解释。
38. 作为运维者，我希望 projection failure 不改写已 committed outcome，以便派生文件不会成为第二证据源。
39. 作为运维者，我希望 Cache publication failure 不触发 rollback Node success，以便优化故障不会破坏 evidence。
40. 作为运维者，我希望无法确认 Ledger commit outcome 时系统停止声称新状态，以便 restart 可以从磁盘事实消除歧义。
41. 作为运维者，我希望 current-generation storage invariant violation fail fast，以便系统不会猜测、修复或静默继续。
42. 作为运维者，我希望不存在 undocumented retries，以便一次操作对应一次可解释的 durable attempt。
43. 作为仓库维护者，我希望 execution orchestrator 只调用一个 Node finalization interface，以便 publication state machine 收进一个 deep Module。
44. 作为仓库维护者，我希望 object store 只拥有 immutable bytes、digest、size 和 durability，以便它不理解科学类型。
45. 作为仓库维护者，我希望 Run Evidence Ledger 只拥有 transaction、fact schema、causal reduction 和 sequence，以便证据规则集中。
46. 作为仓库维护者，我希望 Node finalizer 拥有 Typed Output、Artifact、Result Identity 和 Cache order，以便执行器不再协调多套 rollback。
47. 作为仓库维护者，我希望 public protocol 只有 descriptor/retrieval 路径，以便没有 embedded/reference 双实现。
48. 作为仓库维护者，我希望所有 current producers、consumers、fixtures、examples 和 frontend 一起切换，以便没有 compatibility shim。
49. 作为仓库维护者，我希望旧 Ledger、Cache 和 public schemas 明确 unsupported，以便无需 legacy parser 或 migration。
50. 作为仓库维护者，我希望 Result Identity hashing namespace 不因 storage representation 改变，以便科学身份保持稳定。
51. 作为仓库维护者，我希望 `cache_identity_conflict` 被 `result_identity_conflict` 替代，以便错误名称反映权威拥有者。
52. 作为仓库维护者，我希望 Node failure 标明 `operation`、`publication` 或 `result_identity` origin，以便 causal reducer 不依赖错误字符串猜测。
53. 作为 Module Package 作者，我希望 operation 继续接收已 admitted provider-independent values，以便 Core storage 不进入 scientific operation seam。
54. 作为 Adapter 作者，我希望官方 Provider response 按文档直接翻译，以便不添加假设性 malformed-response 处理。
55. 作为 Adapter 作者，我希望 publication redesign 不改变 Provider calls，以便完整 Provider 与 source-bound Workflow acceptance 验证的是存储边界而不是新的 Provider 行为。
56. 作为测试维护者，我希望用真实注册 Port codecs 构造 lawful large outputs，以便 regression 证明科学合同而不是 mock shape。
57. 作为测试维护者，我希望 fault injection 覆盖 object write、Ledger transaction、projection、Cache 和 Run Closure，以便每个 durable boundary 可验证。
58. 作为测试维护者，我希望 fault tests 通过 Node finalization seam 观察结果，以便测试不绑定私有写入步骤。
59. 作为测试维护者，我希望 public-protocol journey 验证 projection、retrieval、events、cancel 和 restart，以便最高行为 seam 是主要验收面。
60. 作为测试维护者，我希望 Provider-free cases 覆盖事务 mechanics，以便不重复消耗真实 Provider。
61. 作为测试维护者，我希望在一个冻结 generation 中执行完整 installed Provider matrix 和 1PGA、2EMO、3GB1、5G53 acceptance，以便同时确认 Provider、Adapter、publication 和科学证据链。
62. 作为测试维护者，我希望 malformed hypothetical Provider responses 不成为测试范围，以便测试信任官方 API contract。
63. 作为测试维护者，我希望 absence、declared non-success 和 invariant violation 各自有精确 outcome，以便没有 catch-and-continue expectations。
64. 作为维护者，我希望本次变更不增加 authentication、authorization 或 multi-tenancy，以便 trusted loopback architecture 保持明确。
65. 作为维护者，我希望所有保留检查都能指向科学合同、public boundary、durable write、accidental data loss 或 credential hygiene，以便没有无主的防御性代码。
66. 作为测试维护者，我希望每张 ticket 完成前重跑整个 current-generation provider-free repository gate matrix，以便后续实现不会破坏早先完成的行为。
67. 作为测试维护者，我希望所有已声明的 installed Provider gates 在同一冻结 revision 上以 zero-skip 通过，以便公开验收不会把缺少的真实能力当成成功。
68. 作为科学用户，我希望 fresh 1PGA acceptance 完整比较输入结构、ESMFold2 与 SimpleFold，以便得到有明确 confidence、pairing 和分类证据的 three-way structural-consistency 结论。
69. 作为科学用户，我希望 fresh 2EMO acceptance 从准确 CSH parent-span normalization 开始，完成 ProteinMPNN、ESMFold2、confidence、structure comparison 和 Protein-Sol 证据链，以便四个已锁定科学 filters 都可解释。
70. 作为科学用户，我希望 fresh canonical 3GB1 acceptance 保留现有的 ESM-3、ProteinMPNN、folding、15 个最终 Artifacts 和完整 provenance 合同，以便 publication 重构不会降低基准 Workflow 的科学证明力。
71. 作为科学用户，我希望 fresh 5G53 acceptance 完整发布 6 对 Candidates、reconstruction、两组 PAE、resolved-core、counterpart、loop confidence、junction 与 clash 证据，以便大型 publication 与科学筛选同时得到验证。
72. 作为有限内存机器的运维者，我希望所有本地模型验证串行，且任何时刻只有一个验证进程和一个驻留模型实例，以便不会因并发加载或重复实例耗尽资源。
73. 作为证据审查者，我希望全部 Provider 和 1PGA、2EMO、3GB1、5G53 验收证据绑定同一冻结 source revision、installed artifact、Catalog 和 public protocol，以便验收是一个整体而不是跨版本拼接。

## Implementation Decisions

1. 信任模型是强制约束。Port Type owner、public protocol owner、Workflow compiler、Adapter
   和 persistence owner 在各自边界验证一次；通过后，内部组件必须信任值，不重复 decode、
   cross-check 或验证同一科学不变量。
2. 官方 Biohub 和其他已声明 Provider contracts 是 authoritative。Adapter 只按文档翻译并
   记录 provenance；不猜测替代 schema、不修复 response、不跨 endpoint 比对、不增加
   fallback，也不为 hypothetical malformed response 建分支。
3. 本地 invariant violation fail fast。禁止 broad catch、silent coercion、guessed default、
   catch-and-continue 和 undocumented retry。Cache entry 缺失是 miss；current-generation
   Cache entry 违反自身合同是 invariant failure，不得静默改成 miss。
4. durable storage owner 可以检查 content digest、byte size、atomic publication、fsync 和
   causal continuity，因为这些检查直接保护 evidence 与 accidental data loss。检查完成后，
   consumers 信任返回的 immutable object 或 Ledger prefix。
5. Operation Attempt 边界结束于 documented Provider translation、normalization、Candidate
   identity normalization、output Port admission 和 artifact contract processing。以上任何
   失败都属于 Operation；object persistence 与 publication 不属于 Operation。
6. Node Execution Attempt 比 Operation 多一个 publication outcome。executed Operation
   `succeeded` 后，object publication 可使 Node 以 `publication` 失败；Result Identity
   mismatch 可使 Node 以 `result_identity` 失败。不得倒写 Operation terminal。
7. `node_attempt_terminal` 对 failed outcome 使用 closed `failure_origin`：`operation`、
   `publication` 或 `result_identity`。Cancellation、interruption 与 `outcome_unknown` 保留
   自身 terminal statuses，不借用该字段。
8. execution orchestrator 只有一个 Node completion seam：`NodeAttemptFinalizer` 接收一个
   closed finalization intent 并返回 committed disposition。它不暴露 staging path、fact
   assembly、Cache order 或 rollback callback。
9. finalization intents 只包括 executed success、executed non-success、Cache replay success、
   cancellation 和 interruption。新 intent 必须对应新的领域 outcome，不得作为便于测试的
   任意扩展点。
10. `ProjectObjectStore` 是 Project-scoped immutable content-addressed byte store。它拥有
    canonical digest、size、staging、atomic no-replace publication、fsync、verified durable
    reads 和 GC；它不理解 Port Type、Candidate、Artifact、Run 或 Provider。
11. `PROTEIN_WORKBENCH_OUTPUT_ROOT` 继续拥有输出 bytes。每个 Project 使用共享 immutable
    object namespace 和 active staging namespace，不再以随机 Run-scoped files 作为
    Artifact 的权威物理表示。
12. 每个 admitted output Port 产生一个 ordered Port Value Manifest。Manifest 保留 exact
    Port Type、multiplicity、aggregate Port digest、value count，以及每个 canonical value
    的 index、digest、size 和 object reference。
13. 一个 canonical Node Result Manifest 包含 Result Identity、compiler-owned result contract
    metadata 和每个实际 output Port 的 value-manifest reference。它覆盖 ordinary 和
    artifact-capable Ports，是 Result Identity equality 的完整比较面。
14. Artifact bytes 与 Typed Output values 可以共享 object store，但 Artifact descriptor、
    artifact intent、media type、filename provenance、Candidate association 和 public route
    保持独立。物理复用不改变 nominal Port semantics。
15. Run Evidence Ledger 升级为一次 physical transaction 包含多条 typed logical facts。
    transaction 自身不是新的 lifecycle event；logical facts 继续拥有独立连续 sequences。
16. 所有 Ledger writes 都走同一个 transaction interface。单 fact append 是单 fact
    transaction，不保留第二套 sequential file writer。
17. commit 在持有 Run ordering lock 时一次完成 schema admission、causal reduction、sequence
    allocation、canonical transaction write、fsync、atomic publish 和 in-memory state advance。
18. executed success transaction 包含 Operation terminal、Node Result Manifest/Typed Output
    publication、Artifact publication、Node terminal 和 Node disposition。Cache replay success
    transaction 不包含 Operation 或 Engine Invocation facts。
19. operation non-success transaction 包含匹配的 Operation terminal、Node terminal 和
    disposition，不包含任何 output publication。
20. publication 或 Result Identity failure transaction 保留 executed Operation `succeeded`，
    写入 failed Node terminal 与 disposition，不写 output publication。
21. final-name publication 前失败表示 transaction 未提交。rename 开始后但 durability 无法
    确认时，不补偿、不删除、不写相反 terminal；当前进程公开 `evidence_unavailable`，restart
    只依据 contiguous canonical Ledger prefix 决定该 transaction 是否存在。
22. Result Identity authority 是由 committed current-generation Ledger publications 重建的
    Project-scoped index。Project publication lock 覆盖 equality comparison、Run transaction
    commit 和 index advance，使支持的单 backend process 内并发 Runs 不会发布冲突 claims。
23. Result Identity 保留 `protein-workbench-cache/v3` scientific hashing namespace。Ledger
    升级为 `4.0.0`，Cache entry 升级为 `v4`，public bundle 升级为 `2.2.0`，value manifest
    与 Node Result Manifest 使用各自新的 `v1` current-generation namespaces。
24. Result Cache 在 Node Ledger success 后发布 optional replay index。它只引用 Node Result
    Manifest 和 immutable objects，不嵌入 canonical values，不 base64 复制，不返回 rollback。
25. Cache publication failure 只损失 replay optimization。Result Identity conflict 与 Cache
    是否存在无关，public code 使用 `result_identity_conflict`，删除
    `cache_identity_conflict`。
26. Run Projection 只包含 bounded Typed Output descriptors。每个 descriptor 保留 Node、Port、
    Port Type、aggregate digest、value count、value-manifest reference、Result Identity、
    materialization 和 producer provenance；删除 embedded `values`。
27. public protocol 增加 Run-scoped single-value retrieval。它按 Project、Run、Node、output
    Port 和 zero-based value index 返回 exact canonical bytes，并公开 exact size、individual
    digest、aggregate Port digest、Port Type 和 manifest identity。
28. public protocol 不提供 embedded/reference dual path、不提供一次返回所有 values 的兼容
    query，也不在 WebSocket 传科学值。
29. public errors 增加 `node_publication_failed`、`result_identity_conflict`、
    `typed_output_not_found` 和 `typed_value_integrity_mismatch`，保留
    `evidence_unavailable`。Details 只包含 bounded domain identifiers、expected digest/size 和
    publication stage，不包含 paths、canonical values 或 raw exceptions。
30. projection 是 Ledger-derived view。Ledger commit 后 projection materialization 失败不改变
    outcome；系统不做隐藏 retry。下一次明确 projection read 或 startup rebuild 从已验证
    Ledger state 派生当前 view。
31. background worker 无法提交 required evidence 时，active Run record 同时保留 finished 与
    sticky `evidence_unavailable`。Projection 和 Cancel Run 不再返回 `running`；WebSocket 不
    发明 terminal event；Cache 不发布未确认 result。
32. cancellation request 与 Node finalization 使用同一 Run ordering lock。先 committed 的
    decision 获胜；success commit 后 cancellation 不得重写它，cancellation 先 committed 时
    outputs 不得发布。
33. Run Closure 是独立 atomic transaction。所有 Node dispositions durable 后，required
    Selection terminals 与 Run terminal 一起提交。Run status 按 failed、interrupted、
    cancelled、succeeded 的既定 precedence 推导。
34. restart reconciliation 只关闭 durable prefix 中真正 open 的 attempts，推导从未启动
    Nodes 的 dispositions，并在需要时从 committed values 重建 Selection。restart audit fact
    不参与 status 决策。
35. committed successful Node 不因 object、projection 或 Cache read problem 被改写为
    `interrupted`。如果 required durable evidence 不可用，公开 evidence failure 并 fail fast，
    不伪造新的 scientific outcome。
36. GC roots 只来自 committed Ledger object references、current valid Cache indexes 和 active
    staging ownership。Unreferenced objects 没有 public meaning。GC failure 可观测，但不能
    删除 referenced object 或改变 scientific outcomes。
37. 所有 current backend、public protocol、frontend、Contract Test Kit、fixtures、examples、
    docs 和 generated artifacts 一次切换。旧 schemas 和 storage artifacts unsupported；不建
    migration、legacy reader、alias、shim、deprecation layer 或 dual path。
38. 仓库提供四个 current-Catalog、source-bound public acceptance workflows：1PGA、
    2EMO、canonical 3GB1 和 5G53。它们是 current-generation acceptance contracts，
    不从历史 Run JSON、Cache 或 Artifact 复制结果。
39. 1PGA、2EMO 和 5G53 acceptance 需要的 candidate-associated normalization、
    explicit pairing、residue-scoped comparison、confidence、junction 与 clash evidence 必须由
    当前科学 Port/Node contracts 表达。如果当前能力不足，则在调用真实
    Provider 前通过 provider-free lawful fixtures 补齐；不在 test harness 外计算或手工拼接。
40. verification controller 对 local-model tiers 实施全局串行调度：禁止
    pytest-xdist、并发 verifier、并发 Workflow 和嵌套模型进程；同一 gate 中对
    同一模型的多个 calls 复用一个已加载实例，不按 sample 或 Candidate 重复
    加载。切换到另一本地模型前，上一模型的进程必须终止并释放。
41. 真实验收只在所有 provider-free contracts 和 test harnesses 完成后开始。
    从第一个 installed Provider gate 起冻结 source revision、installed artifact、Catalog、
    Provider assets/configuration 和 public protocol；验收期间任何变更都使受影响的
    evidence generation 失效并从冻结点重跑。
42. 真实验收顺序固定为：installed Provider matrix → 1PGA → 2EMO →
    canonical 3GB1 → 5G53。顺序只管理资源、证据 generation 和阻塞边，
    不改变任何 Method 或科学结论。

## Testing Decisions

1. 主要验收 seam 是完整 public Run journey，而不是 private helper：Start Run、Run
   Projection、single-value retrieval、Artifact retrieval、event replay/live WebSocket、Cancel
   Run 和 restart recovery 必须共同证明 observable behavior。
2. 唯一新增的内部行为 seam 是 `NodeAttemptFinalizer`。Fault-injection tests 通过 finalization
   intent 驱动真实 causal reducer，并观察 committed facts、public projection、objects、Cache
   和 restart outcome；不直接断言私有 staging names 或函数调用顺序。
3. `ProjectObjectStore` 和 `RunEvidenceLedger` 各有 production filesystem adapter 与明确的
   fault-injecting test adapter。Adapter 只用于控制 durable failure point，不 mock scientific
   values、Port codecs 或 causal expectations。
4. 大型 output regression 使用真实注册 ESM-3 Port codecs 和合法 domain values，不使用
   hand-written JSON shape 代替 admission。291 residues、2 samples、reconstruction 和两组 PAE
   是精确必测 fixture。
5. Regression 必须证明每个 retrieved canonical value 与 admission bytes 完全相同，并闭合
   per-value digest、aggregate Port digest、value count、Candidate identities、lineage、
   Prediction Keys、confidence facts 和 PAE shapes。
6. declared `num_samples=100` 使用 lawful provider-free canonical fixtures，证明 Ledger
   transaction size 只随 descriptor metadata 增长，不随 scientific value bytes 增长。
7. fault matrix 覆盖 typed-value object staging/write/fsync/publish、Artifact object
   publication、Result Identity comparison、Ledger transaction write/fsync/rename、in-memory
   advance、projection materialization、Cache index publication 和 Run Closure。
8. 每个 fault point 必须从外部证明 Operation terminal、Node terminal、failure origin、public
   visibility、Result Identity authority、Cache state、object reachability、same-process API 和
   restart result。任何 committed transaction 都不能暴露 logical-fact 子集。
9. rename 后 outcome-unacknowledged case 必须证明同一进程不补偿，restart 对完整 contiguous
   transaction 接受、对不存在 transaction 保持旧 prefix，并且两种情况都不产生冲突 facts。
10. projection failure test 证明 committed outputs 仍由 Ledger 可见，并证明没有自动 retry
    loop 或 outcome rewrite。
11. Cache failure test 证明 Node 和 Run outcome 不变；Cache absence 是 miss；违反
    current-generation Cache contract 的 fixture 必须 fail fast，而不是被当作 miss。
12. cancellation race tests 覆盖 cancellation-first、publication-first、worker-finished-with-
    evidence-unavailable 和 shared-object ownership。
13. restart tests 覆盖 open Engine Invocation、open Operation、unstarted Node、all-success Node
    dispositions、required Selection 可重建、无 Selection、selection failure 和 missing Run
    terminal。
14. public protocol tests 证明 Run Projection 不含 `values`，descriptor 有界，single-value
    route 严格 Run-scoped，Artifact route 保持独立，WebSocket 不含 scientific payload。
15. Result Identity tests 在 Cache directory 缺失时仍检测 committed conflict，并证明 storage
    schema cutover 不改变 `protein-workbench-cache/v3` hashing identity。
16. trust-model tests 只覆盖 declared contracts 和 documented outcomes。不构造 hypothetical
    malformed Provider responses，不期待 Adapter repair/fallback，不把重复 validation 当成质量。
17. prior art 使用现有 Run execution、public protocol、Result Cache、Artifact、cancellation/
    restart、ESM-3、deterministic acceptance 和 Contract Test Kit suites；新 tests 扩展这些
    highest seams，而不是为每个新 helper 建孤立 unit suite。
18. 每个 ticket 在标记完成前，必须先通过当前改动的 focused tests，再重跑从第一张 ticket
    到当前 ticket 的全部累计 public journeys、fault regressions 和 acceptance criteria。
    后续 ticket 仅有自身 focused tests 通过不足以完成；任何先前已完成行为
    发生回归时，当前 ticket 必须保持未完成。
19. 每张 implementation 或 acceptance-preparation ticket 的整体门禁包含
    `routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、
    `local-esmfold2-v2-contract`、`installed-package`、`provider-isolation` 和
    `security-failure`，再加 frontend Oxlint 与 TypeScript/build。这些 gates 必须在当前
    checkout 全部通过，不能以旧 ticket 的历史结果代替。
20. core transaction、fault、cancellation、restart 和 GC mechanics 仅使用 provider-free
    lawful values 验证。真实 Provider 用于完整 Provider gates 与四个 source-bound scientific
    Workflows，不用于替代这些 deterministic fault tests。
21. 全部 installed Provider tiers 都是必须的 zero-skip gates：Biohub ESMC、
    Biohub ESM-3、Biohub ESMFold2、local ESM-3、local ESMFold2、mkdssp、
    ProteinMPNN、SimpleFold folding、SimpleFold confidence、SoluProt 和 Protein-Sol。
    Mocks、未安装、skip 或 readiness gap 都不计作完成。
22. 本地模型 tiers 和 source-bound Workflows 严格串行；任何时刻最多一个
    verifier/Workflow 进程和一个 resident local-model instance。同一 gate 内的同模型
    calls 必须复用该实例，禁止按 sample/Candidate 重复加载；切换模型前必须
    确认上一模型进程退出并释放。禁止 pytest-xdist 和任何并发 gate。
23. 1PGA acceptance 使用固化的 75-residue input，SHA-256 为
    `d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30`。它必须通过
    public REST/WebSocket journey 证明 exact structure-to-sequence lineage、同一 sequence parent
    的 ESMFold2/SimpleFold sibling pairing、3 条 explicit alignment/TM/RMSD edges、分开的
    Method confidence 和已锁定的 three-way classification。ESMFold2 使用
    `effective_seed=1075001` 和 1 sample；SimpleFold 使用
    `effective_seed=1075002`、1 sample 和 `num_steps=50`。输入 B-factor 不得解释为
    pLDDT。
24. 2EMO acceptance 使用固化 input，SHA-256 为
    `6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700`。它必须通过
    public journey 证明 A:66 到 A:65–A:67 的 exact CSH parent-span normalization、224-aa
    Candidate 的 fixed `SHG`、ProteinMPNN 生成、candidate-associated 结构 normalization、
    ESMFold2、confidence、explicit residue correspondence 和 Protein-Sol，并准确应用
    TM-score `>=0.80`、Cα RMSD `<=2.50 Å`、mean pLDDT `>=70` 与
    Protein-Sol scaled `>=0.446` 四个 filters。零个 Candidate 通过是允许的
    scientific result，但缺失执行或 Evidence 不是。
25. canonical 3GB1 acceptance 使用固化 input，SHA-256 为
    `ee623d3d9fd77a131895dc367c31ac8d7266b1d4f241b56325170e5f62ed7811`。它继续要求
    10 个 paired ESM-3 Candidates、top 3 selection、每个 selected parent 的 5 个
    ProteinMPNN designs（3×5，共 15 个）、15 个最终 folds/Artifacts 以及 exact
    science、lineage、provenance 和 public evidence。
26. 5G53 acceptance 使用固化四链 input，SHA-256 为
    `a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537`。它必须保留
    chain A 的 283 个 resolved residues 和 A:146→A:159 discontinuity，仅在
    A:211→A:224 建立 8/12/16-residue branches，产生 6 对 exact counterparts 以及全部
    reconstruction、confidence 和 PAE。完整科学门禁包含 resolved-core
    TM-score `>=0.75`、RMSD `<=3.00 Å`，counterpart TM-score `>=0.70`、
    RMSD `<=3.50 Å`，resolved-core mean pLDDT `>=70`、单独 loop pLDDT、
    两个 junction C–N distance `1.15–1.55 Å` 和排除共价相邻 atom 后无
    `<2.00 Å` loop/core nonbonded heavy-atom clash。零个 Candidate 通过是允许的
    scientific result，但 evidence gap 不是。
27. 四个 source-bound acceptances 都使用 current official Provider contracts、current Catalog
    exact versions 和 installed public REST/WebSocket surface；不使用历史 Cache、历史 Artifacts、
    mock 或 Workbench 外部计算。历史 workflow version 不是 authority。
28. 最终 acceptance generation 必须在同一冻结 revision 上依次通过全部 installed
    Provider tiers、1PGA、2EMO、canonical 3GB1 和 5G53，并在最后重跑第 19 条
    的完整 provider-free/frontend matrix。任何 source、contract、generated artifact、
    Provider asset/configuration 或 test harness 变更都使受影响证据失效，不得拼接。

## Out of Scope

- 修改任何 ESM-3 Node Type、Execution Binding、Method、Adapter request 或 Provider endpoint。
- 删除或压缩 PAE、reconstruction、confidence collections、Candidates 或合法 samples。
- 改变 Candidate、Prediction Key、Prediction Confidence Fact、Score、Metric、Method、lineage、
  provenance、Port digest、multiplicity、units、shapes、residue mappings、masking 或 randomness。
- 把 ordinary Typed Output 改成 artifact-capable Port，或合并 Typed Output 与 Artifact public
  semantics。
- authentication、authorization、multi-tenancy、sandboxing、hosted-service hardening、
  adversarial input handling 或 distributed locking。
- multi-process backend coordination；Project publication lock 只保证当前 trusted single backend
  process 的并发 Runs。
- 猜测、修复、cross-check 或 fallback Provider responses。
- malformed hypothetical Provider、network adversary 或 malicious local user 测试。
- 旧 Ledger、Cache、projection 或 public payload 的 migration、compatibility reader、shim、
  alias、deprecation 或 dual-path support。
- 将 Result Cache 提升为 evidence source，或让 projection/object enumeration 成为 visibility
  authority。
- 反复调用真实 Provider 验证 object、Ledger、projection、Cache、cancellation 或 restart
  mechanics。
- 在 test harness 或 Workbench 之外修复、补算、筛选或拼接 1PGA、2EMO、3GB1 或
  5G53 的科学值。
- frontend visual redesign；本 spec 只要求现有和重写后的 frontend 消费新 descriptor 与
  retrieval contract。

## Further Notes

- ADR-0039 是 architecture decision authority；本 spec 将其转换为可交给 agent 的用户、
  implementation 和 testing contract。
- 已接受的唯一内部 completion seam 是 `NodeAttemptFinalizer`；最高验收 seam 是完整 public
  Run journey。无需在实现前再次选择 seam。
- “必须信任”不表示跳过科学或 persistence contracts，而是明确执行 validate once, trust
  thereafter。任何新增 check 都必须能归属于 scientific correctness、explicit contract、
  durable write、accidental data loss 或 credential hygiene；否则不应存在。
- 本 spec 明确解决早期设计笔记中可能被误读为防御性编程的表述：只有 Cache absence 是
  recoverable miss；current-generation invariant violation fail fast。Projection 不自动 retry；
  Provider response 不做 hypothetical malformed handling。
- `WFRET-5G53-001` 的 provider-free reproduction 已足以驱动 core implementation 和 fault
  matrix。最终 real-provider generation 扩展为全部 installed Provider gates 以及
  1PGA、2EMO、canonical 3GB1、5G53 四条 source-bound Workflows；它们验证生产 seam
  和完整科学证据，不用于补做历史法证。
- `ready-for-agent` 表示需求、trust boundary、architecture seam、public contract 与 testing
  contract 已闭合；它不表示 implementation 已完成。
- 每张 implementation ticket 的完成门禁都是累计门禁，而不是局部门禁。完成状态声明必须基于
  当前 checkout 的整体 provider-free 证据，并重新证明所有先前 tickets 的已交付行为。
  真实验收开始后另外要求同一冻结 generation 的全部先行 Provider/Workflow
  evidence；后续代码变更会使该证据失效，而不是被历史结果覆盖。
