# Protein Workbench v2 global corrective repair after independent review

**Status:** ready-for-agent

## Problem Statement

Protein Workbench v2 的 37 个 backend refactor Tickets 已完成并通过既有累计
verification，但独立审查证明，当前实现仍可在测试为绿的情况下产生错误科学结果、
错误 Candidate lineage、未经证明的 provider identity、不可恢复的 Run/Cache 状态和
无法独立验证的安装态证据。

对蛋白质工程师而言，当前实现可能把未绑定真实 PDB bytes 的坐标用于 TM-score，把
ProteinMPNN 约束移动到错误链或虚构残基位置，把多链序列和多记录 FASTA 静默解释成
新的单链蛋白，并丢失 ESM-3 paired generation 的 coordinate conditioning。DSSP、
ESM-3 PAE、ProteinPrompt 和 residue numbering 的合法科学值也可能被拒绝或错误改写。
这些行为违反 Candidate、Structure Alignment、Residue Track、Observation Context 和
Adapter 的既定科学语义。

对 Workflow 作者而言，Candidate value 在 extension seam 上仍可变，presentation-only
metadata 和无语义顺序会改变 Workflow Contract Lock，Selection Objectives 被跨
Workflow 全局校验，公共协议和 nominal Port Type 又没有完整执行自己声明的验证合同。
因此相同科学合同可能被无关展示变化破坏，而真正不合法的 Objective、evidence reference
或 Prompt 可能推迟到昂贵执行后才失败。

对运行维护者而言，取消与 Node Execution Attempt 启动之间存在竞态，Cache publication
与 Run Evidence Ledger 的 durable success 不能保持原子可恢复，required standalone
artifact 可能被错误 Cache replay，Derived Run 又依赖可变 Workflow revision。
WebSocket replay 还会在 Ledger 之外合成带 durable sequence/cursor 外观的 framing
events，使 Run Event Stream 不再是 Run Evidence Ledger 的一致 projection。

对扩展和验收维护者而言，Binding Readiness 可能依赖无关 sibling assets、重复扫描整棵
provider tree，或把 checker 刚生成的 proof 误判为未来时间。全局 token 猜测、参数名
黑名单和任意 JSON 关键词扫描又会拒绝合法科学值，同时不能替代 schema-scoped secret
处理。installed-package gates 可继承 source checkout 的绝对 `.pth`，缺少 installed
canonical 3GB1 与 installed zero-Core public journeys，部分 provider gate 还绕过 public
protocol。Ticket 37 bundle 内容虽自洽，却没有 tracked external anchor、独立 verifier
和实际 wheel/sdist bytes，因而不足以支持强意义的独立真实性声明。

用户需要的是一次本地执行的全局纠正性修复，而不是围绕某一张“第一工单”的局部补丁。
修复必须同时关闭实现缺陷、合同偏差、安装态证据缺口和具有功能伤害的过度防御，并保留
真正必要的 filesystem、process、identity、causality 和 secret-safety 不变量。

## Solution

实施一次 backend-only、发布前可破坏兼容的 v2 全局纠正。修复不按症状堆叠 guard，而是
将相关行为收敛到少数高杠杆 Module 和既有 Interface：

- canonical value 与 semantic identity 统一负责 Candidate immutability、contract
  semantic projection、canonical bytes、Result Identity 和 content identity；
- closed schema validation 统一执行 public protocol、Port Type、Metric、参数、
  ProteinPrompt 和引用合同，同时把 Method-specific policy 留在所属 Method；
- immutable Residue Layout 在公共值、Node Type implementation 与 Adapter 之间端到端
  保留，禁止按字典顺序、拼接字符串或连续编号假设重建科学语义；
- validated Structure Alignment evidence 精确绑定 subject/reference Candidate、
  canonical PDB bytes、residue mapping、coordinates、Method 和 normalization，评分
  Module 不再接收未闭合 evidence；
- Run admission/commit Module 统一协调 cancellation、Attempt claim、Run Evidence
  Ledger、typed outputs、Cache visibility 和 restart reconciliation；
- Binding-owned Readiness declarations 只证明该 Binding 的 exact asset closure，
  使用可注入 clock、明确 proof reuse/invalidation 和已认证 Adapter identity；
- installed backend public protocol 继续作为系统级主验收 seam，Contract Test Kit
  作为唯一 package seam，更低 seam 只用于 canonicalization、Port validation、
  Adapter translation 和危险 filesystem/process 行为的精确诊断。

合法且被 locked provider 与 Port contracts 表示的科学输入必须无损保留。若某个
Execution Binding 确实不能表示该输入，它必须在 provider execution 前以稳定 structured
error 拒绝；禁止 silent concatenation、chain flattening、renumbering、identity
substitution、coordinate dropping 或 heuristic normalization。

造成误拒绝的全局值形状脱敏、参数名黑名单、任意 JSON 文本扫描和 mutable Workflow
revision equality 将被删除。Readiness asset hashing、时间验证、Method policy 和 JUnit
redaction 将被缩窄到其真实 Interface。`O_NOFOLLOW`、owner/mode/nlink checks、symlink
resistance、staged write、`fsync`、atomic publish、Ledger no-replace、bounded
diagnostics、process cleanup 和 cleanup-error precedence 将保留，并集中在共享的内部
implementation 中。

修复完成后，对所有改变语义的 Port Type、Method、Execution Binding、behavior identity、
canonical descriptor 或 public protocol 进行纠正性 version increment，重新生成
canonical golden vectors 和 Contract Locks，并要求 persisted Workflows 显式 relock。
所有 provider-free、deterministic、security、provider-isolation 和 installed gates
稳定后，才生成一次 clean-source、source-bound 的 fresh remote canonical 3GB1 evidence。

## User Stories

1. 作为蛋白质工程师，我希望 TM-score 只能使用绑定 exact subject/reference PDB bytes 的 Structure Alignment，以便伪造坐标不能产生可信评分。
2. 作为蛋白质工程师，我希望 Structure Alignment 保留 exact Candidate identities、content digests、residue mapping 和 coordinates，以便下游 Metrics 可独立核验其输入。
3. 作为蛋白质工程师，我希望 pairwise Score Observation 固定 exact Method、reference Candidate、normalization 和 evidence identity，以便评分含义不会被任意 metadata 替代。
4. 作为蛋白质工程师，我希望 ProteinMPNN 固定位置和约束始终引用原始 Residue Layout，以便链顺序不会把约束移动到另一条链。
5. 作为蛋白质工程师，我希望 ProteinMPNN 正确保留不连续 residue numbers，以便编号缺口不会产生 phantom residues。
6. 作为蛋白质工程师，我希望 ProteinMPNN 的目标长度按真实设计残基计算，以便 provider 的正确输出不会因虚构位置被拒绝。
7. 作为蛋白质工程师，我希望 multi-chain ProteinSequence 要么被 Binding 完整保留，要么在 provider execution 前结构化拒绝，以便 Folding 不会冒充错误的单链 lineage。
8. 作为蛋白质工程师，我希望 multi-record FASTA 不被静默拼成一个新蛋白，以便输入记录身份和科学含义不被改变。
9. 作为蛋白质工程师，我希望 structure-to-sequence 遇到同一 residue identity 的冲突 residue names 时失败并报告歧义，以便系统不任意选择一个名称。
10. 作为蛋白质工程师，我希望 negative、gapped 和 multi-chain residue identifiers 在支持它们的合同中保持原样，以便公共类型不拒绝真实结构布局。
11. 作为蛋白质工程师，我希望 production prompt authoring 能构造其编辑合同已允许的 insertion layout，以便生产行为不依赖 test-only 注入。
12. 作为蛋白质工程师，我希望 ProteinPrompt 的所有 tracks 在没有 target layout 时仍执行完整 shape、symbol、mask 和 alignment validation，以便 malformed Prompt 不进入 content identity。
13. 作为蛋白质工程师，我希望 mkdssp 4.6.1 invocation 显式计算 accessibility，以便 SASA Residue Track 不是全缺失。
14. 作为蛋白质工程师，我希望真实 DSSP coil `.` 被解释为 coil 而不是 missing，以便 secondary-structure semantics 不被改写。
15. 作为蛋白质工程师，我希望真实 DSSP PPII `P` 被 annotation contract 表达，以便包含 PPII 的结构不会使整个 Node 失败。
16. 作为蛋白质工程师，我希望 ESM-3 接受合同允许的 31.75 Å PAE bin center，以便合法 provider 输出不被错误拒绝。
17. 作为蛋白质工程师，我希望 ESM-3 paired generation 保留 counterpart request 的 coordinates，以便 sequence 与 structure conditioning 不丢失。
18. 作为蛋白质工程师，我希望 injected test Adapter 不能声明 exact production Biohub ESMC identity，以便 provenance 只描述实际选择和证明的执行路径。
19. 作为蛋白质工程师，我希望 Candidate 和嵌套科学值在 extension seam 上不可变，以便 implementation 不能修改内容后沿用旧 identity。
20. 作为蛋白质工程师，我希望 Candidate identity 在跨 Run 和 Cache replay 时稳定且与 content/lineage 闭合，以便相同 ID 不会指向不同科学对象。
21. 作为蛋白质工程师，我希望 Metric decimal precision 被精确执行，以便超出声明精度的值不会伪装成合规 Observation。
22. 作为蛋白质工程师，我希望合法 scientific identifiers 不被 token-shape heuristics 改写，以便 Candidate、Method 和实体身份在 Ledger 中保持可验证。
23. 作为 Workflow 作者，我希望 presentation-only title、summary 和 workspace labels 不进入 Workflow Contract Lock，以便展示变化不会使科学 Workflow 失效。
24. 作为 Workflow 作者，我希望语义无序的 Produced Observations 不受 registration construction order 影响，以便等价 Catalog 产生相同 semantic identity。
25. 作为 Workflow 作者，我希望语义有序的 Ports 和 Tracks 继续保留顺序，以便 canonicalization 不会删除真正的科学差异。
26. 作为 Workflow 作者，我希望 public protocol 的 `uniqueItems`、`const` 和 closed-field constraints 被完整执行，以便公开合同不是仅供展示的 schema。
27. 作为 Workflow 作者，我希望 boolean 与 number 的 `const` 比较保持 JSON 类型差异，以便 `False` 不会冒充 `0`、`True` 不会冒充 `1`。
28. 作为 Workflow 作者，我希望 FrozenCatalog 只接受能够由 public Catalog schema 发布的 Port Type identifiers，以便 startup 成功的合同一定可以公开查询。
29. 作为 Workflow 作者，我希望 Utility Transform 的 Environment Configuration 仍在 trusted backend scope，以便 endpoint、path 和 credential 不进入 Selection Objective。
30. 作为 Workflow 作者，我希望参数验证依据所属 schema 和 scope，而不是参数名 token blacklist，以便 `path_length`、`host_organism` 和 `connection_radius` 等科学字段可合法使用。
31. 作为 Workflow 作者，我希望每个 consuming Node 独立验证自己的 Selection Objectives，以便不同合法 selection branches 不会互相污染。
32. 作为 Workflow 作者，我希望每个 consuming Node 至少拥有一个 positive effective weight，以便零总权重在 compile 阶段失败。
33. 作为 Workflow 作者，我希望 selected pairwise evidence reference 必须存在于 FrozenCatalog 并固定 exact Method/version/digest，以便 runtime 不接受虚构 reference。
34. 作为 Workflow 作者，我希望 normalization fields 由 exact Context 和 Method contract 验证，以便任意 normalization length 不会改变评分含义。
35. 作为 Workflow 作者，我希望 self-comparison、tied-position bias 等 Method policies 由所属 Method 验证，以便 nominal Port Types 不承担不属于数据形状的政策。
36. 作为 Workflow 作者，我希望显式 relock 是接受纠正性合同变化的唯一方式，以便 runtime 不静默修改 persisted Workflow。
37. 作为 Workflow 作者，我希望 Start Derived Run 绑定 immutable source Run 和其 Execution Plan/Contract Lock identity，以便当前 mutable Workflow revision 不会阻止语义相同的 derive。
38. 作为 Workflow 作者，我希望 correction 后的 stale Contract Lock 明确失败，以便无效旧行为不会通过 compatibility shim 继续执行。
39. 作为运行维护者，我希望 cancellation 与 Node Execution Attempt claim 是一个确定的状态转换，以便取消落盘后不会启动新的 Operation Attempt 或 Engine Invocation。
40. 作为运行维护者，我希望 completion/cancellation race 由 monotonic Ledger facts 决定，以便重复取消和并发终结具有幂等结果。
41. 作为运行维护者，我希望 required evidence durable persistence 先于 Node success 和 Cache visibility，以便没有证明的结果不能发布成功。
42. 作为运行维护者，我希望 Cache entry 只有在完整 typed output、Ledger closure 和 publication 全部成功后才可 replay，以便 provisional entry 不会永久污染 Result Identity。
43. 作为运行维护者，我希望 crash 或 rollback failure 后存在显式 reconciliation，以便 staged/provisional state 可被安全终结或回收。
44. 作为运行维护者，我希望 required standalone-artifact Binding 永远 non-cacheable，以便 Cache replay 不引用 Run-scoped artifact。
45. 作为运行维护者，我希望 WebSocket replay 只投影 durable Ledger facts，以便 sequence、cursor 和 timestamp 在重连时保持一致。
46. 作为后端客户端开发者，我希望 transport-only framing 不冒充 durable Run event，以便 replay control 与科学执行事实可区分。
47. 作为后端客户端开发者，我希望 replay/live handoff 不重复或遗漏 terminal event，以便 opaque cursor 可以安全重连。
48. 作为扩展维护者，我希望每个 Binding 声明并验证自己的 exact asset closure，以便一个 sibling 的模型缺失不会阻塞另一 Binding。
49. 作为扩展维护者，我希望 SoluProt full 与 no-TM 的 Readiness 独立，以便 no-TM 不依赖 full-only assets。
50. 作为扩展维护者，我希望 provider asset identity 在一个 point-in-time snapshot 中只计算必要次数，以便重复全树扫描不会造成无意义成本。
51. 作为扩展维护者，我希望 Readiness checker 使用可注入 clock，并在 checker 返回后验证 observation time，以便正常新 proof 不被误判为未来。
52. 作为扩展维护者，我希望 production provider identity 绑定 selected Binding、Readiness Attestation 和实际 Adapter，以便 fake client 不能产生生产身份。
53. 作为扩展维护者，我希望 Adapter 只翻译 provider/native 类型而不重建或简化科学语义，以便 Node Type 在不同执行路径上保持一致。
54. 作为安全维护者，我希望 secret redaction 依据 closed schema 中的敏感字段，以便合法科学值不因字符串形状被删除。
55. 作为安全维护者，我希望 public evidence validation 使用结构化 identity、causality 和 source binding，以便任意文本关键词扫描不再充当真实性证明。
56. 作为安全维护者，我希望 create/replace storage 使用一个共享内部 implementation，以便安全修复集中而不是复制约百行编排。
57. 作为安全维护者，我希望 storage consolidation 保留 no-follow、owner/mode/nlink、symlink resistance、staged write、fsync 和 atomic publish，以便删除重复不等于削弱安全。
58. 作为安全维护者，我希望 cleanup failure 不覆盖 primary execution failure，以便错误因果仍可审计。
59. 作为验收维护者，我希望 retained JUnit 保留 testcase name、failure type、message 和位置，以便失败证据可以定位。
60. 作为验收维护者，我希望 JUnit 和 diagnostics 只做结构化敏感字段脱敏，以便安全与可诊断性同时成立。
61. 作为验收维护者，我希望 installed test environment 不继承 source checkout 的绝对 `.pth`，以便 wheel/sdist 是唯一 production code 来源。
62. 作为验收维护者，我希望 installed process 核验完整 `sys.path` 和 provider distribution origin，以便间接 source leakage 不能绕过 isolation probe。
63. 作为验收维护者，我希望 installed canonical 3GB1 journey 通过 public protocol 完成，以便 source `create_app()` 不能代替安装态证明。
64. 作为验收维护者，我希望 installed zero-Core extension 完成 discovery、Catalog query、compile、execution 和 replay，以便 extension contract 不只证明默认 Catalog。
65. 作为验收维护者，我希望 installed local-provider gates 逐项经过 REST 和 Run Event Stream，以便内部 Run implementation 不能替代公开 Interface。
66. 作为验收维护者，我希望 Ticket 37 evidence 具有 tracked external digest anchor，以便 ignored local bundle 的内容可绑定到版本控制中的声明。
67. 作为验收维护者，我希望 retained wheel/sdist bytes 或其受控发布产物与 evidence 一起保存，以便 claimed build identity 可以复核。
68. 作为验收维护者，我希望 independent verifier 不导入或复用被测 implementation 的 lineage/proof code，以便 evidence 不是由同一生成器自证。
69. 作为验收维护者，我希望所有 provider-free、installed、security 和 provider-isolation gates 稳定后才调用 remote providers，以便调试不消耗配额或污染最终证据。
70. 作为验收维护者，我希望 fresh canonical 3GB1 evidence 绑定 clean current source、exact artifacts、Contract Locks、Execution Plan、Readiness、Ledger 和 Candidate lineage，以便最终证明覆盖本次纠正性修复。
71. 作为仓库维护者，我希望受影响合同和 behavior identities 获得纠正性 version increment，以便同一 ID/version 不代表两种行为。
72. 作为仓库维护者，我希望顶层 v2 spec 只在全局 gate 关闭后标记 completed，以便文档状态与真实验收一致。
73. 作为仓库维护者，我希望修复过程保持 backend-first 和串行拓扑执行，以便交叉语义在每个累计 gate 后保持可运行。
74. 作为仓库维护者，我希望本次工作只在本地 issue/spec surface 和本地 Git 中执行，以便不会未经授权同步 GitHub。

## Implementation Decisions

1. 本规格是一次全局纠正性 repair 的唯一范围合同，不以某一张首要工单或某个单文件
   patch 为中心。实现可以按依赖切片串行落地，但每个切片都必须服务于本规格的整体闭合。
2. 原 37 个 completed Tickets 和其 Controller evidence 保留为历史记录。新修复引用其被
   违反的合同，但不回写旧 Ticket 使历史证据看似从未失败。
3. 当前 v2 specification、领域词汇和 accepted ADRs 继续是规范 authority；独立审查
   findings 是已复现缺陷输入。若实现期间发现某一 finding 无法再次复现，必须记录 exact
   observation 并回到本规格裁决，不能静默省略。
4. 最高层系统 Interface 保持 installed backend 的版本化 public protocol。Catalog
   Snapshot、Workflow Compile、Start Run、Start Derived Run、Cancel Run、Run Event
   Stream、Run Projection 和 Artifact Retrieval 共同形成主要 acceptance journey。
5. Module Package 的唯一补充 seam 仍是 Contract Test Kit 对 production Module Package
   Registration 的 conformance。只有 public protocol 或 package seam 不能精确定位时，
   才直接测试 Port Type validation/canonicalization、Adapter translation、Metric math
   或危险 filesystem/process behavior。
6. 建立一个 canonical value/identity Module，集中负责 immutable public values、
   canonical semantic projection、I-JSON/JCS bytes、content digests、Candidate identity
   和 Result Identity。调用者不得分别重建 canonical payload。
7. Candidate 及其嵌套 collection、layout、lineage 和 provenance values 必须不可变。
   Extension implementation 接收值之前，executor 固定调用前 canonical snapshot；
   output publication 必须相对该 snapshot 验证，禁止用已被修改的引用与自身比较。
8. 区分 stable Catalog presentation identity 与 Workflow-compatible semantic contract
   identity。title、summary、category、workspace label 和其他 presentation-only metadata
   可以改变 Catalog presentation snapshot，但不进入 Contract Lock 或 Result Identity。
9. semantic descriptor 对语义无序 declaration 以 stable identity 排序，对 Ports、
   residue-aligned tracks 和其他语义有序值保留顺序。registration construction order、
   YAML key order、source path 和 installed path 不影响 semantic digest。
10. public protocol、Port Type、Metric、参数和 reference validation 使用一套 closed
    schema-validation Module。所有声明的 `uniqueItems`、closed fields、limits、formats、
    exact references 和 nested contracts 都由同一规则执行。
11. `const` 和 equality 使用 JSON 类型语义；boolean 与 number 不等价。decimal precision
    使用可精确表达的 canonical numeric validation，不依赖 binary-float 字符串偶然表现。
12. Port Type identifier 的长度、字符集和 canonical form 在 registration、FrozenCatalog、
    protocol bundle 和 Catalog Snapshot 上完全一致；不能公开发布的 identifier 使
    Catalog build 原子失败。
13. Environment Configuration 只由 trusted backend 按 Binding scope 注入。Utility
    Transform、Node 和 Binding parameters 只能包含其 closed scientific contract
    声明的字段，禁止用参数名 token blacklist 推断 configuration scope。
14. secret classification 由 schema/declaration 显式标记。redaction 发生在 Ledger public
    projection 与 diagnostics publication seam，不得按任意 value shape 猜测 secret；
    raw validated IDs、redacted public values 和 persisted evidence 保持分阶段处理。
15. Residue Layout 成为 ProteinSequence、ProteinStructure、ProteinPrompt、Structure
    Alignment 和相关 Candidate values 的不可变真相来源。Module 或 Adapter 不得从
    provider dictionary order、连续编号假设或裸 sequence length 重建 source layout。
16. 当前单记录 ProteinSequence import contract 遇到多个 FASTA records 时返回稳定
    structured ambiguity error。未来若支持多记录，必须使用显式 Candidate Collection
    contract，而不是复用单序列 import 的拼接行为。
17. 每个 Folding Binding 声明自己能够保留的 layout capability。可无损表示多链输入的
    Binding 必须保留 chain identity；不能表示的 Binding 在 provider execution 前拒绝，
    不得发送拼接裸字符串后发布单链结构。
18. structure-to-sequence 遇到同一 canonical residue identity 的冲突 residue names 时
    fail closed。negative、不连续和多链 residue identifiers 只按 Port/Method 的明确
    capability 处理，不使用全局禁止规则。
19. ProteinPrompt validation 无论 target layout 是否存在，都验证 tracks 的完整 shape、
    symbols、mask、missingness 和内部一致性。production prompt authoring 必须能够构造
    accepted editing contract 中的 insertion layout。
20. ProteinMPNN Adapter 保留 source Residue Layout，并通过 exact residue identities
    转换 fixed、tied、omit、bias 和 designable positions。provider output order 只用于
    解析 provider result，不得成为 source constraint truth。
21. structure-annotation Adapter 对 locked mkdssp invocation 启用 accessibility
    calculation。canonical annotation 区分真实 coil、missing 和 PPII；若某个下游
    consumer 不支持 PPII，必须通过显式 versioned conversion 或 structured rejection，
    不得在 annotation seam 静默丢失。
22. ESM-3 PAE validation 接受 declared maximum bin center 31.75 Å，并从 canonical Metric
    contract 取得范围。paired generation 必须保留 counterpart coordinates 和所有可表示
    tracks，不得构造一个语义更弱的新 request。
23. exact production provider identity 只能由 selected Binding 的已认证 Adapter 和
    passing Readiness Attestation 发布。test/fake Adapter 使用独立 identity，或在试图
    声明 production identity 时 fail closed。
24. Structure Alignment evidence 必须绑定 subject/reference Candidate identities、
    canonical PDB content digests、exact residue correspondence、coordinate payload、
    alignment Method 和 result-defining normalization。Scoring Module 只接受通过该
    validation 的 evidence。
25. Pairwise Observation Context validation 解析 exact Catalog Method/version/digest、
    reference Candidate identity/digest、pairing mode、normalization fields 和 source
    partition。仅匹配 ID 字符串或 CA count 不构成 evidence closure。
26. Selection Objective validation 以每个 consuming Node Instance 为 scope。每个
    consumer 独立验证 Candidate input、Score Collection partition、exact selectors、
    match cardinality、missing policy 和至少一个 positive weight；所有失败发生在
    provider execution 前。
27. nominal Port Type 只拥有数据形状、canonical validation、codec 和 content identity。
    self-comparison、tied-position 与 residue bias 组合等 Method-specific policy 移至
    相应 Method/Binding validation。
28. Run lifecycle 采用显式单调状态转换。Node Execution Attempt claim 必须原子确认
    Run 尚未取消且 Node 尚未终结；取消完成后不得产生新的 Operation Attempt 或 Engine
    Invocation。
29. 一个深的 Run commit Module 统一 required evidence persistence、typed output
    publication、Node Disposition、Cache eligibility/visibility 和 failure recovery。
    这些步骤的可见状态必须具有明确 durable ordering 和 crash reconciliation。
30. Cache entry 在完整 output validation、required Ledger facts 和 success publication
    全部成立前不可 replay。staged/provisional state 必须不可查询，并能在 restart 时
    被确定地完成、作废或回收；rollback failure 不能留下永久占用 Result Identity 的
    unusable entry。
31. required standalone-artifact results 继续明确 non-cacheable。Cache codec 只保存
    complete typed values，不保存 absolute、Run-relative 或隐式 artifact paths。
32. Start Derived Run 依赖 immutable source Run、source Execution Plan、Contract Lock
    identity 和显式 retry/force policy。当前 mutable Workflow revision 不是额外相等
    条件；若用户要求采用新 Workflow，必须先显式 compile/start 一个不同 Run。
33. Run Event Stream 只使用 Run Evidence Ledger 的 durable facts 分配 durable sequence
    和 opaque cursor。transport-only replay framing 必须没有 durable fact 外观；如果
    public protocol 要求其成为 Run event，则先把它作为 typed fact 持久化。
34. Readiness checker 接收可注入 clock。proof 的 observed time 由 checker 产生，freshness
    validation 使用 checker 返回后的 validation time 和声明的 clock-skew contract，
    禁止与调用前旧时间比较。
35. 每个 Binding 的 Readiness declaration 明确列出 exact asset closure。SoluProt full
    与 no-TM、各 ESMFold/ESM-3/SimpleFold Bindings 独立验证自己的 assets；无关 sibling
    不进入 readiness、Method identity 或 Invocation provenance。
36. 对昂贵 immutable assets 可以在一个有明确 scope、identity、age 和 invalidation 的
    point-in-time snapshot 内复用 digest；禁止重复全树扫描和 zero-argument
    process-global green cache。
37. fresh-evidence validation 依赖 structured source identity、Catalog/Plan/Lock digests、
    Ledger causality、Candidate lineage、artifact hashes 和 provider provenance。删除对
    arbitrary serialized JSON 的 forbidden-keyword 搜索。
38. retained JUnit summary 保留 testcase name、classname、duration、failure/error type、
    bounded message 和 location。只对显式 sensitive fields 和 private paths 执行结构化
    redaction。
39. create/replace storage orchestration 收敛为一个内部 deep Module。其 Interface 固定
    staged content、replace policy、expected scope 和 publication outcome；implementation
    统一保留 no-follow、owner/mode/nlink、symlink resistance、fsync、atomic publish、
    Ledger no-replace 和 cleanup-error precedence。
40. installed artifact verification 必须在 source checkout 外创建全新 environment，
    只安装本轮生成的 wheel/sdist 及其 declared dependencies。不得复制 ambient `.pth`
    或隐式继承 checkout paths。
41. installed process 记录和核验完整 import roots、`sys.path`、distribution origins、
    wheel/sdist digests 和 FrozenCatalog/protocol identities。repository provider sources
    只有作为已声明安装 dependency 才可出现。
42. 恢复 installed canonical 3GB1 与 installed zero-Core journeys。两者均通过 public
    protocol 完成 discovery、Catalog query、Workflow Compile、Run、replay/live Event
    Stream、Run Projection 和 Artifact Retrieval；不得直接构造 private Run
    implementation。
43. installed local-provider gates 同样通过 public protocol，并分别证明 selected Binding、
    Readiness、Invocation 和 exact provider/model identity。required gates zero skip。
44. 最终 evidence bundle 包含或绑定实际 wheel/sdist bytes、protocol/FrozenCatalog/Plan
    identities、Run evidence 和 artifacts。一个 tracked digest manifest 作为 local
    bundle 的 external anchor。
45. independent verifier 不导入 production package 的 verifier、lineage 或 proof
    implementation。它从公开 schemas 和 bundle bytes 独立重算 digests、Candidate
    lineage、Ledger closure、artifact binding 和 expected 3GB1 cardinality。
46. 任一被修复的 validator、codec、content identity、Method、Binding、Readiness、
    Adapter、observation propagation 或 public protocol behavior 都更新相应
    behavior/contract version。禁止同 ID/version 静默改变行为。
47. correction 不提供对 invalid v2 behavior 的 compatibility layer。旧 Contract Locks
    返回 structured mismatch；persisted Workflows 只有在 author 明确接受新 Catalog 后
    才 relock 并形成新 Workflow revision。
48. 实施保持 backend-first 和串行拓扑顺序。每个实现切片在本地先复现红测试，完成后跑
    focused 与累计 gates；git commit 保持 green。全局规格完成不要求一个单体 commit，
    但最终验收必须覆盖全部修复的交叉行为。
49. 顶层 v2 specification 只在 corrected versions、relocked fixtures、installed
    journeys、independent evidence 和 final source-bound acceptance 全部关闭后改为
    `completed`。
50. 本规格及后续实现只在本地工作区和本地 Git 中执行。不得创建、更新、关闭或同步
    GitHub repositories、Issues、Pull Requests 或远程 branches，除非用户之后另行明确
    授权。

## Testing Decisions

1. 好测试只断言可观察合同，不锁定 private class、helper、内部目录、call count 或
   transitional call graph。测试的默认 surface 是 public protocol 或 Module Package
   Contract Test Kit。
2. 每个确认缺陷必须先有一个在旧实现上真实失败的 focused regression。红状态在本地被
   观察和记录，修复后才提交；版本库提交不保留故意失败状态。
3. Candidate immutability tests 必须包含 extension 原地修改、嵌套 collection 修改、
   调用前后 canonical snapshot、冲突 content/lineage 和 Cache replay identity。
4. canonical identity differential tests 必须证明 presentation-only metadata、YAML key
   order、registration construction order、source/install path 和无序 Observation 重排
   不改变 semantic Lock identity；真正的 Method、Port、ordered Track 或 behavior
   变化必须改变 identity。
5. schema-validation tests 必须覆盖 `uniqueItems`、type-sensitive `const`、decimal
   precision、identifier limits、unknown fields、exact references、Environment
   Configuration exclusion 和完整 ProteinPrompt tracks。
6. scientific-ingress tests 必须覆盖 multi-record FASTA、multi-chain Folding、
   negative/gapped/multi-chain Residue Layout、contradictory atom residue names 和
   production insertion authoring。合法可表示输入必须 round-trip；不可表示输入必须在
   provider execution 前返回稳定 error。
7. ProteinMPNN differential tests 必须至少覆盖 source layout `B,A` 而 provider order
   `A,B`、固定 `B:1`、编号 `A:1/A:3`、真实 designable length、tied/omit/bias policies
   和 provider output mapping。
8. structure-annotation tests 使用 locked mkdssp behavior fixture，覆盖 accessibility
   flag、71/71 SASA、coil `.`, PPII `P`、missing value 和下游显式 conversion/rejection。
9. ESM-3 tests 覆盖 PAE `31.75`、paired coordinate conditioning、所有可表示 Prompt
   tracks，以及 fake client 不能产生 exact production ESMC identity。
10. Structure Alignment/TM-score tests 使用真实 subject coordinates 与相差 100 Å 的
    forged evidence，要求 validation 在 scorer 前失败；另覆盖 Candidate/PDB digest、
    residue correspondence、Method、normalization 和 source partition tampering。
11. Selection tests 构造两个合法独立 consumers，证明彼此 Objective 不冲突；另构造
    仅含 zero-weight Objective 的 consumer，要求 compile 在任何 upstream/provider
    execution 前失败。
12. lifecycle tests 使用确定性 barriers、injected scheduler/clock 和 storage
    failpoints，而不是 timing sleeps，覆盖 cancel-before-claim、cancel/complete race、
    evidence failure、Cache publication failure、rollback failure、restart 和 repeated
    reconciliation。
13. Cache tests 覆盖 provisional invisibility、restart recovery、identity conflict、
    complete typed publication、required standalone-artifact non-cacheability 和 current
    Run replay provenance。
14. Derived Run tests 证明 immutable source identity 足够，mutable Workflow revision
    变化不会无关阻断；不同 Contract Lock/Execution Plan 只能通过显式新 compile/Run。
15. Run Event Stream tests 从 public protocol 任意 cursor 断开并重连，覆盖 terminal
    event、replay/live handoff、backend restart、sequence uniqueness 和 transport-only
    framing 不占用 durable sequence。
16. Readiness tests 使用 injected clock 和 exact asset manifests，覆盖 proof 刚生成、
    stale proof、允许的 skew、scope/age/fingerprint/invalidation、sibling asset 删除和
    unrelated tree mutation。
17. overdefense regression 对每项修改使用三联测试：合法输入必须通过；真实危险输入仍
    必须失败；identity、causality、secret 和 filesystem safety invariants 不得退化。
18. redaction tests 使用 schema-marked secrets 与 token-shaped legitimate scientific
    IDs，证明前者不出现在公开 evidence，后者保持原值；禁止依靠任意文本关键词证明无
    mock/fixture。
19. storage tests 通过共享 storage Interface 覆盖 create/replace、no-follow、
    owner/mode/nlink、symlink swap、fsync/rename failure、no-replace 和 cleanup failure
    precedence，不再重复测试两套 private orchestration。
20. JUnit tests 必须证明 retained summary 在 bounded/redacted 后仍包含 testcase 和
    failure location，并在 secret/private path fixture 中不泄露敏感值。
21. installed isolation test 在 source checkout 外构建并安装 wheel/sdist，拒绝 ambient
    `.pth`、checkout path、undeclared editable install 和 provider origin leakage。
22. installed canonical 3GB1 和 zero-Core extension tests 只通过 public protocol
    client；测试进程不得导入 production internals，也不得直接构造 Run implementation。
23. installed local-provider gates 分别证明 public transport、selected Binding、
    Readiness 和 Invocation evidence，不能用 private construction 代替。
24. independent evidence tests 使用独立 verifier 重算 tracked anchor、wheel/sdist、
    public contract bundle、FrozenCatalog、Execution Plan、Ledger closure、Candidate
    lineage 和 15 个 71-residue PDB artifacts。
25. 每个实现切片先跑拥有行为的 focused tests，再运行 provider-free cumulative
    `routine`。canonical/scientific 修改还运行 `deterministic-acceptance` 和
    `scientific-repro`；Readiness/provider 修改运行 `provider-isolation`；storage、
    Ledger、redaction 和 verifier 修改运行 `security-failure`。
26. 所有局部修复完成后，依次通过 `routine`、`deterministic-acceptance`、
    `scientific-repro`、`local-esmfold2-v2-contract`、`provider-isolation`、
    `security-failure` 和 `installed-package`，并通过 dependency lock、installed
    package consistency、compileall、full-range diff check 和 clean-worktree checks。
27. required installed provider gates 必须 zero skip，并在所需 credentials/assets 已
    明确可用时运行；历史 passing transcript 不替代当前 corrected source。
28. fresh remote canonical 3GB1 是最后一个 source-bound gate，只在所有 provider-free、
    installed 和 local-provider gates 稳定后运行一次。调试阶段不得反复消费 remote
    quota。
29. 最终 code review 同时检查 Spec 与 Standards：逐项确认所有 independent-review
    findings 已由 observable regression 关闭，并重新审查所保留的防御是否仍有明确威胁
    模型。

## Out of Scope

- 当前 React/ReactFlow 前端、浏览器交互、`UI-001..UI-012` 和 `VER-008`。
- 新增独立科学能力、Metrics、providers、模型变体或不属于已接受 v2 contract 的输入。
- v1 runtime 恢复、v1 migrator、dual reader、silent conversion，以及对 invalid v2
  behavior、stale Contract Locks 或错误 identity 的 compatibility shim。
- 修改 vendored 或 external provider repositories；provider compatibility 修复属于
  Workbench Adapter。
- third-party plugin management、runtime hot loading、automatic dependency installation
  或新的 discovery mechanism。
- cross-Project physical Cache sharing、分布式 Cache、并行 Node execution 或多 backend
  process storage coordination。
- 自动删除 Projects、Workflows、Cache、Run records、ignored evidence 或 provider
  assets；任何 cleanup 都需要单独、精确授权。
- 为修复之外的性能优化重写系统；只处理已确认的无关 sibling hashing、重复全树扫描和
  重复 storage orchestration。
- 暴露 private Execution Plan、scheduler state 或 Run Evidence Ledger 的 physical
  storage shape。
- 在局部修复期间生成 remote 3GB1 evidence，或把历史 bundle 当作 corrected source 的
  最终证明。
- 创建或同步 GitHub Issue、Pull Request、remote branch、release 或其他远程状态。

## Further Notes

- 本规格综合独立审查对固定范围
  `21810a494fe66ed3d8cf7bb47c59a1c29d735dcf...fb9b79775ada74f21f389c632dba08e46d0db7d1`
  的复现结果。后续 planning-only commits 不改变该范围内的 production implementation。
- `ready-for-agent` 表示全局修复范围、Interface、scientific semantics 和 acceptance
  seams 已足以进入本地实现；不表示任何缺陷已经修复。
- 本规格是全局合同，不要求把实现压成一个单体 change。实现仍按依赖串行推进，并在每次
  累计 gate 后保持 repository runnable。
- corrective version increments 的具体版本号由实际改变的 contract kind 和现有版本决定，
  但“行为变化必须换 identity/version”已经确定，不留给 implementation 自行规避。
- canonical 3GB1 仍是不可替代的最终系统验收；其 remote rerun 不是定位局部 bug 的工具。
- provider/model availability、credentials 和大型 assets 是实时外部状态。routine tests
  不依赖它们，required gates 在 unavailable、skip 或缺少 Invocation evidence 时失败。
- 本规格仅落盘本地，不发布到项目的 GitHub issue tracker。后续是否 commit、建立本地
  implementation branch 或推送远程，均需要用户另行授权。
