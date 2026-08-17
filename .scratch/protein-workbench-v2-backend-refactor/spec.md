# Protein Workbench v2 backend architecture refactor

**Status:** historical completion record; superseded; do not implement

Current authority: `CONTEXT.md`, `docs/codebase-redesign.md`,
`docs/redesign-switch-1.md`, and the accepted ADRs. Cache conflict, restart
reconciliation, and filesystem/security requirements below are historical.

## Problem Statement

Protein Workbench 已完成 v1 后端在科学正确性、运行隔离、provider evidence、安装态和
canonical 3GB1 acceptance 方面的修复，但真实 runtime 仍由 legacy v1 合同驱动。当前
45 个 Node Types 分布在 43 个一级目录中，生产发现依赖分散的注册函数和逐目录导入；
Definition metadata、runtime factory 与 provider readiness 由平行映射分别维护；Port
Type 会从未知字符串隐式产生；同一 Definition 还可能在启动和 implementation 构造时
重复加载。已接受的 `ModulePackage`、`FrozenCatalog`、Execution Binding、Method、
Metric Definition、Observation Context 和 Result Identity 尚未进入运行代码。

对于仓库维护者，这意味着新增或扩展科学能力仍可能需要同时理解并修改发现、Definition、
factory、provider probing、参数、evidence、Cache 和测试等多条路径。本地 ESMFold2、
本地 ESM-3、SoluProt 或 Protein-Sol 尚不能只通过一个内聚 Module Package、一个统一
registration interface 与一套 Contract Test Kit 完成，也不能证明新增能力确实做到零
Core 修改。“能够方便地自定义节点”的原始目标因此仍未由真实后端实现。

对于蛋白质工程师，legacy 合同也不能稳定区分 Node Type 的科学操作、Method 的模型或
算法身份、Execution Binding 的执行路径、startup Availability、每个 Run 的 Readiness
以及实际 Engine Invocation。旧式 `score_id + value` 不能可靠表达同一 Metric 的不同
Methods、reference-based observation 或一个 Method 产生多个 Metrics；旧 Cache identity
和多路 evidence 写入也不能为精确重现、Cache replay 与科学审计提供一个事实来源。

现有 v2 决策还需要闭合几项跨 Module 的公开 interface：Workflow 只有 ID/version 而
没有作者接受的可达合同闭包锁；`contract digest` 尚无跨 source checkout 与 installed
artifact 一致的 canonical bytes；Binding 没有声明其实际产出的 Score Observations；
pairwise Context selector、v2 public protocol、每个 Execution Plan Node 的终态以及
SimpleFold confidence 的实际资产闭包也尚未精确定义。若这些内容留给各 implementation
自行决定，最高层验收、跨 checkout 重现和零 Core 修改扩展仍会产生互不兼容的合同。

项目尚未投入生产，没有必要保留这些 accidental v1 contracts。当前 React 前端是冻结的
toy implementation，也不应成为后端合同来源。需要先完成一次 backend-only、发布前的
破坏性 v2 重构，使后端具备稳定、可扩展、可审计且可独立验收的合同，再另行设计和重写
前端。

## Solution

将后端重构为由 11 个内聚 Module Packages 提供科学能力的 v2 runtime。仓库维护者通过
新增或扩展 Module Package，提供显式 Node/Metric Definitions、Methods、Execution
Bindings、Port Type Definitions、Utility Transforms、lazy implementation/Adapter
factories，以及 Availability 和 Readiness declarations。每个包只提交一个 immutable
typed Module Package Registration；Registry 在启动时原子解析全部合同，并且只在所有
验证成功后发布一个 immutable FrozenCatalog。

Workflow v2 的每个 Node Instance 显式固定 exact Node Type 与 Execution Binding 的 ID
和 version，分别保存 Node parameters 与 Binding parameters，并携带只覆盖该 Workflow
可达合同闭包的 Contract Lock。Method 由 Binding 唯一派生；Environment Configuration
不进入 Workflow 参数。所有合同通过同一 canonical descriptor/digest 规则获得稳定身份。
Compiler 使用同一 FrozenCatalog 验证 Contract Lock 和静态语义并产生 immutable
Execution Plan；每个 Run 在任何 Cache lookup 之前为全部 distinct selected Bindings
获得 point-in-time Readiness Attestations。

使用显式、版本化的 nominal Port Types 管理 Node 连接；使用
Candidate、Metric、Method、Observation Context 和 Value 的完整关系表达 Score
Observations。Binding 通过闭合的 Produced Observation Interface 声明可由其输出 Port
保证产生的 Metrics、Context profiles 和 multiplicity；Selection Objective 绑定明确的
Score Collection scope，并显式拥有 Utility Transform、weight 和 missing-value policy。
Workbench 对外统一使用 `[0, 100]` pLDDT Metrics，并固定 SimpleFold confidence
evaluation 的真实 Method 和实际参与计算的资产闭包，而不是允许自由切换 `model_name`。

执行事实统一写入 Run Evidence Ledger，并明确区分 Node Execution Attempt、Operation
Attempt 与 Engine Invocation；每个 Execution Plan Node 另有且仅有一个终态 Node
Disposition，以覆盖 blocked、调度前 cancellation 和 restart reconciliation。Manifest、
JSONL lifecycle stream 和 WebSocket events 都是 Ledger projections。使用 canonical
Result Identity 驱动 Project-scoped v2 Cache，并保持 Candidate identity 在跨 Run 与
Cache replay 之间稳定。

系统级主验收 seam 是安装态 backend 的版本化 public protocol。该 interface 由唯一、
机器可读的 protocol contract bundle 固定 Catalog、compile、Run、cancel、event replay、
projection、artifact 和 structured-error schemas；验收客户端不导入内部实现。Module
Package 的唯一补充 seam 是统一 Contract Test Kit。迁移完成后，以本地 ESMFold2、本地
ESM-3、SoluProt 和 Protein-Sol 验收 repository-owned extension，以 canonical 3GB1
Workflow 重新验收完整科学和执行行为。v2 直接重写 repository-owned examples、seed
Workflows 和 fixtures，不提供 v1 兼容路径。

## User Stories

1. 作为仓库维护者，我希望通过新增或扩展一个 Module Package 提供新科学能力，以便不修改 Core。
2. 作为仓库维护者，我希望一个内聚 Module Package 可以提供多个相关 Node Types，以便共享科学语义、依赖、Adapter 和测试资产。
3. 作为仓库维护者，我希望每个 Node Type 恰好拥有一份独立 Node Definition，以便公共合同只有一个真相来源。
4. 作为仓库维护者，我希望 Node Definition 只声明公共科学语义，以便不会混入 factory、凭据、设备、路径或 provider probe。
5. 作为仓库维护者，我希望多个 Node Types 可以共享内聚 implementation、Adapter、资源和测试夹具，以便消除机械的一节点一套脚手架。
6. 作为仓库维护者，我希望 Node Type 的科学身份不随部署方式改变，以便本地和远程 Bindings 共享相同 Workflow 语义。
7. 作为仓库维护者，我希望 Method 固定准确的算法、模型、checkpoint、featurization、source 和 scale contract，以便科学结果可解释且可复现。
8. 作为仓库维护者，我希望每个 Execution Binding 固定一个 Method 和 direct implementation 或 Adapter，以便执行时不会隐式切换科学方法。
9. 作为仓库维护者，我希望 Adapter 只翻译 provider 或 runtime 与 Workbench 合同，以便不改变 Node Type 的科学含义。
10. 作为仓库维护者，我希望简单科学操作可以使用 direct implementation，以便不必创建没有翻译职责的 Adapter。
11. 作为仓库维护者，我希望跨所有 Bindings 科学意义相同的参数属于 Node Definition，以便 Workflow 作者看到一致的科学合同。
12. 作为仓库维护者，我希望 Method/Adapter 特有且仍可调的参数属于 Execution Binding，以便不会伪装成所有 Bindings 都支持的参数。
13. 作为仓库维护者，我希望模型身份由 Method 和 Binding 固定，以便自由文本 `model_name` 不会偷偷切换科学方法。
14. 作为仓库维护者，我希望凭据、设备、endpoint 和 runtime path 属于 Environment Configuration，以便不会污染 Workflow 科学参数。
15. 作为仓库维护者，我希望 secret 通过 opaque handle 注入，以便 Workflow、Result Identity 和公开 evidence 都不保存 secret。
16. 作为仓库维护者，我希望每个 Module Package 只有一个 production registration，以便启动发现只有一个入口。
17. 作为仓库维护者，我希望 registration 显式列出 Definitions、Methods、Bindings、Port Types 和 Utility Transforms，以便生产内容不依赖目录猜测。
18. 作为仓库维护者，我希望生产发现禁止 glob、递归扫描、helper enumeration 和 import side effect，以便文件重命名不会静默改变 Catalog。
19. 作为仓库维护者，我希望可选 provider 依赖只由 lazy factory 加载，以便缺少一个 provider 不会阻止其他包被发现。
20. 作为仓库维护者，我希望未知 schema、未知字段、不完整合同和悬空引用使启动失败，以便合同漂移不会被接受。
21. 作为仓库维护者，我希望同一 ID/version 对应不同 digest 时启动失败，以便不会按导入顺序随机选择合同。
22. 作为仓库维护者，我希望 Registry 完成全部临时解析后再发布 FrozenCatalog，以便不存在部分启动成功。
23. 作为仓库维护者，我希望 FrozenCatalog 发布后不可变，以便 Compiler、Run admission、executor 和查询 interface 观察同一合同集合。
24. 作为仓库维护者，我希望 Core 不再维护平行的 Definition Registry、factory map 或 provider map，以便扩展只修改所属 Module Package。
25. 作为仓库维护者，我希望所有合同引用使用 exact ID、version 和 contract digest，以便禁止 `latest`、version range 和环境相关升级。
26. 作为仓库维护者，我希望 unavailable Binding 仍保留在 FrozenCatalog，以便缺失依赖不会隐藏 Node Type 或影响 sibling Binding。
27. 作为仓库维护者，我希望 Contract Test Kit 直接消费 production registration，以便测试与启动发现验证同一合同。
28. 作为仓库维护者，我希望 Contract Test Kit 统一验证 registration、Port Type、参数、Readiness、provenance 和 Result Identity，以便新增节点不再发明测试框架。
29. 作为仓库维护者，我希望 package-local tests 与 implementation 保持 locality 但不进入 production artifact，以便测试资产不成为运行合同。
30. 作为仓库维护者，我希望 Module Package 可以注册新 Port Type Definition，以便领域数据类型不需要修改 Core。
31. 作为仓库维护者，我希望 Module Package 可以声明 Metric Definition 与 Observation Context schema，以便新评分不必压成任意 `score_id`。
32. 作为仓库维护者，我希望 Module Package 可以注册受控、版本化的 Utility Transform，以便新选择目标不执行任意用户代码。
33. 作为仓库维护者，我希望现有 Nodes 按科学能力归并为 11 个内聚 Module Packages，以便共享逻辑留在具有 locality 的 module 内。
34. 作为仓库维护者，我希望迁移删除重复 Definition loading、registration、provider probing、Adapter glue、provenance 和测试样板，以便目录归并真正降低复杂度。
35. 作为仓库维护者，我希望只在确有资源或多个内聚实现时增加子目录，以便不重新形成浅层目录森林。
36. 作为仓库维护者，我希望测试用 echo Node 不进入生产 FrozenCatalog，以便测试支撑不成为公开科学能力。
37. 作为仓库维护者，我希望源码 checkout 与 installed artifact 发现同一个 FrozenCatalog，以便打包方式不改变能力。
38. 作为仓库维护者，我希望本地 ESMFold2 作为 folding 包的新 Binding 加入，以便不复制折叠 Node Definition 或修改 Core。
39. 作为仓库维护者，我希望本地 ESM-3 Bindings 复用 esm3 包的多个 generation Node Types，以便本地部署扩展保持内聚。
40. 作为仓库维护者，我希望 SoluProt 和 Protein-Sol 组成 solubility Module Package，以便共享序列输入、评分输出、Readiness 和测试合同。
41. 作为 Workflow 作者，我希望 Workflow 明确声明 v2 schema version，以便后端无需猜测文档格式。
42. 作为 Workflow 作者，我希望每个 Node Instance 固定 exact Node Type ID/version，以便科学操作不随 Catalog 更新而改变。
43. 作为 Workflow 作者，我希望每个 Node Instance 固定 exact Binding ID/version，以便部署路径、Method 和 Adapter 不由环境自动选择。
44. 作为 Workflow 作者，我希望 Method 由 Binding 唯一派生，以便 Workflow 不保存两个可能矛盾的 Method 选择。
45. 作为 Workflow 作者，我希望 version range、`latest`、自动 Binding 选择和 silent fallback 被拒绝，以便不同环境不会改变科学方法。
46. 作为 Workflow 作者，我希望 Node parameters 与 Binding parameters 分开保存，以便公共科学参数和 route-specific 参数不会混淆。
47. 作为 Workflow 作者，我希望 Environment Configuration 不出现在 Workflow 参数中，以便同一 Workflow 可安全地在不同 trusted environment 运行。
48. 作为 Workflow 作者，我希望每个 Port 精确引用一个 Port Type ID/version，以便连接兼容性具有可审查的 nominal contract。
49. 作为 Workflow 作者，我希望只有相同 Port Type ID/version 才能直接连接，以便结构相似的数据不会被误当成科学等价。
50. 作为 Workflow 作者，我希望转换由显式 Node Type 表达，以便转换的科学意义、参数和 provenance 可见。
51. 作为 Workflow 作者，我希望 Compiler 在执行前验证 schema、DAG、Ports、参数、Binding ownership 和合同引用，以便无效 Workflow 不进入昂贵执行。
52. 作为 Workflow 作者，我希望悬空 Metric、Method、Observation Context、Utility Transform 或 Port Type 引用产生编译错误，以便错误不推迟到 runtime。
53. 作为 Workflow 作者，我希望 Compiler 解析 exact Selection Objective 和 Utility Transform，以便排序含义不会在运行时隐式决定。
54. 作为 Workflow 作者，我希望成功编译产生 immutable Execution Plan，以便一个 Run 的身份、参数和合同在准入前固定。
55. 作为 Workflow 作者，我希望 Execution Plan 保留 resolved contract digests，以便执行能证明与编译时 Catalog 一致。
56. 作为 Workflow 作者，我希望 Compiler 只断言 static Availability，以便编译成功不会被误解为 provider 当前可调用。
57. 作为 Workflow 作者，我希望每个 Run 在首次 Cache lookup 前取得全部 selected Bindings 的 Readiness，以便 Cache 不能绕过当前运行条件。
58. 作为 Workflow 作者，我希望任何 selected Binding 的 Readiness 失败都在执行前拒绝 Run，以便不会产生部分运行。
59. 作为 Workflow 作者，我希望同一 exact Binding 的多个 Node Instances 可共享一次 Run attestation，以便避免重复检查。
60. 作为 Workflow 作者，我希望 proof 只有在声明 scope、age、configuration identity 和 invalidation 时复用，以便陈旧检查不会被信任。
61. 作为 Workflow 作者，我希望 volatile prerequisites 每个 Run 重新观察，以便环境变化在执行前被发现。
62. 作为 Workflow 作者，我希望 stochastic Node 固定 effective randomness，以便重复运行和 Result Identity 有确定含义。
63. 作为 Workflow 作者，我希望 Score selector 精确指定 Metric、Method 和 Observation Context，以便不会从同名评分中任意选择。
64. 作为 Workflow 作者，我希望 intrinsic 与 pairwise Context 使用 typed schema，以便 reference Candidate 角色不藏在字符串后缀中。
65. 作为 Workflow 作者，我希望 Selection Objective 显式固定 Utility Transform、weight 和 missing policy，以便任务偏好属于 Workflow。
66. 作为 Workflow 作者，我希望 weights finite、非负且至少一个为正，以便加权结果有明确数学含义。
67. 作为 Workflow 作者，我希望记录 declared 与 effective weights，以便选择结果可审计。
68. 作为 Workflow 作者，我希望缺失 observation 默认失败，以便不完整评分不会静默改变排名。
69. 作为 Workflow 作者，我希望不同 Metrics 的 raw values 不直接相加，以便不同单位和量纲不被错误混合。
70. 作为 Workflow 作者，我希望 v1 Workflow 返回 `unsupported_schema_version`，以便旧合同不会被猜测或重解释。
71. 作为蛋白质工程师，我希望通过可连接 Node Types 组合设计、折叠、评价、转换和选择，以便表达完整科学过程。
72. 作为蛋白质工程师，我希望 Candidate 具有稳定、run-independent identity，以便同一科学对象不因 Run UUID 改变身份。
73. 作为蛋白质工程师，我希望 Candidate identity 保留 producer、output、sample、parents 和 content identity，以便区分相同内容的不同 lineage。
74. 作为蛋白质工程师，我希望 Cache replay 保留 Candidate identity 和 lineage，以便复用结果不会伪装成新对象。
75. 作为蛋白质工程师，我希望 Score Observation 使用 Candidate、Metric、Method 和 Observation Context，以便每个值都能正确解释。
76. 作为蛋白质工程师，我希望 pairwise observation 记录 reference Candidate role、identity、digest 和 normalization，以便结构比较不丢参照。
77. 作为蛋白质工程师，我希望相同 observation identity 和 value 可以去重，以便 Score Collection 不制造无意义重复。
78. 作为蛋白质工程师，我希望相同 observation identity 的冲突 value fail closed，以便系统不任意保留一个评分。
79. 作为蛋白质工程师，我希望一个 Method 可以产生多个 Metrics，以便多头输出不压缩成含糊 score。
80. 作为蛋白质工程师，我希望 Metric Definition 声明 shape、unit、direction、range、granularity 和 aggregation，以便消费者正确解释评分。
81. 作为蛋白质工程师，我希望逐残基和 mean-residue pLDDT 对外统一为 `[0, 100]`，以便不同 Methods 可比较。
82. 作为蛋白质工程师，我希望 mean pLDDT 是有效蛋白残基的等权平均，以便 padding、chain break 和 NaN 不扭曲结果。
83. 作为蛋白质工程师，我希望 pLDDT conversion 由 Adapter 静态合同决定，以便系统不根据 observed values 猜尺度。
84. 作为蛋白质工程师，我希望 SimpleFold folding 与 existing-structure confidence 是不同 Node Types，以便评价已有结构不重新折叠。
85. 作为蛋白质工程师，我希望 SimpleFold confidence Method 固定真实 checkpoints、encoder、featurization、source 和 scale，以便评分身份准确。
86. 作为蛋白质工程师，我希望 SimpleFold evaluation 不加载未参与计算的 folding checkpoint，以便 Readiness 和 provenance 不夸大依赖。
87. 作为蛋白质工程师，我希望 SimpleFold 结果相关资产变化建立新 Method/Binding，以便新 pipeline 不冒用旧身份。
88. 作为蛋白质工程师，我希望 SoluProt full 与 no-TM 是不同 Methods/Bindings，以便模型变体不隐藏在参数中。
89. 作为蛋白质工程师，我希望 Protein-Sol percent-sol、scaled-sol 和 pI 是独立 Metrics，以便不同科学量不压成一个 score。
90. 作为蛋白质工程师，我希望 population-sol 是 baseline/calibration Context，以便总体参考不被误当作 Candidate score。
91. 作为蛋白质工程师，我希望 Result Identity 包含全部 result-affecting contracts、inputs、parameters、randomness 和 implementation identities，以便 Cache 不复用科学含义不同的结果。
92. 作为蛋白质工程师，我希望 Project、Run、Node Instance、timestamp 和 UI metadata 不进入 Result Identity，以便相同科学计算可在同一 Project 跨 Run 复用。
93. 作为蛋白质工程师，我希望缺少任何 result-affecting identity 时禁用 cross-Run Cache，以便不完整 key 不污染结果。
94. 作为蛋白质工程师，我希望 Cache 只保存完整、成功、validated、cache-eligible typed values，以便 partial 或失败输出不会被复用。
95. 作为蛋白质工程师，我希望 Cache 不保存 absolute 或 Run-relative paths，以便 replay 不指向其他 Run 的临时文件。
96. 作为蛋白质工程师，我希望相同 Result Identity 对应不同 output digest 时产生 `cache_identity_conflict`，以便错误 identity 不采用 first-write-wins。
97. 作为蛋白质工程师，我希望 Cache hit 仍要求当前 Run Readiness，以便系统不暗中提供未承诺的 offline mode。
98. 作为蛋白质工程师，我希望 physical Cache 保持 Project-scoped，以便其他 Project 的结果不会未经设计进入当前研究。
99. 作为后端客户端开发者，我希望查询 FrozenCatalog 的 Node Types、Ports、Methods 和 Bindings，以便未来界面由唯一后端合同构建。
100. 作为后端客户端开发者，我希望 unavailable Binding 仍可查询并具有 structured reason，以便能力缺失不会表现为节点消失。
101. 作为后端客户端开发者，我希望 compile 与 Run admission failure 使用稳定结构化诊断，以便区分 Workflow invalid、Availability 和 Readiness。
102. 作为后端客户端开发者，我希望 manifest、JSONL 和 WebSocket 都投影自一个 Run Evidence Ledger，以便不同读取方式不互相矛盾。
103. 作为后端客户端开发者，我希望 Run facts 具有 monotonic sequence，以便延迟或重连不会破坏因果顺序。
104. 作为后端客户端开发者，我希望 Attempt 与 Invocation 使用不同 typed facts，以便客户端不从自由文本猜生命周期。
105. 作为后端客户端开发者，我希望每个已开始的 Operation Attempt 和 Engine Invocation 恰有一个 terminal，以便进度不会永久悬空。
106. 作为后端客户端开发者，我希望 terminal status 区分 success、failure、cancellation、interruption 和 unknown outcome，以便恢复动作正确。
107. 作为后端客户端开发者，我希望 Cache hit 明确表示 replay 且不声称发生 Invocation，以便界面不误导用户。
108. 作为后端客户端开发者，我希望公开错误、facts 和 projections 在持久化前安全 redaction，以便 UI 不泄露 secret 或 private path。
109. 作为运行维护者，我希望 required evidence 持久化失败时 Node 不能成功或写 Cache，以便成功结果不会缺少证明。
110. 作为运行维护者，我希望 worker loss 记录 interruption 或 unknown outcome，以便系统不会臆造远端结果。
111. 作为运行维护者，我希望 retry 使用新的 Attempt 和 Invocation identities，以便重试不覆盖原故障证据。
112. 作为运行维护者，我希望开发状态清理是独立显式操作，以便架构重构不会自动删除本地数据。
113. 作为运行维护者，我希望 routine verification 不调用 remote provider 或加载大型模型，以便日常测试快速且无外部成本。
114. 作为运行维护者，我希望 required provider gate 在 unavailable、skip 或无 Invocation evidence 时失败，以便 Readiness 不冒充科学验证。
115. 作为验收维护者，我希望最高层验收只通过 backend public protocol，以便 Catalog、Compiler、Readiness、Cache 和 Ledger 作为整体被验证。
116. 作为验收维护者，我希望窄层 seam 只诊断主验收无法定位的合同，以便测试 seam 数量保持最少。
117. 作为验收维护者，我希望 acceptance 检查 Ledger closure 和 causal relationships，以便不固定历史调用条数。
118. 作为验收维护者，我希望 evidence 绑定当前 source、FrozenCatalog、Execution Plan、Readiness、Cache 与 Invocations，以便旧证据不能替代当前实现。
119. 作为验收维护者，我希望 canonical 3GB1 重新证明科学 track、top-three、3×5 lineage 和 15 个 run-bound PDB，以便 v2 没有退化已完成行为。
120. 作为验收维护者，我希望四个扩展案例均做到零 Core 修改并通过 Contract Test Kit，以便“方便自定义节点”成为可执行合同。
121. 作为 Workflow 作者，我希望 Workflow 保存其可达合同闭包的 expected digests，以便另一 checkout 不能用相同 ID/version 静默替换我接受的合同。
122. 作为仓库维护者，我希望 contract digest 具有与 Python 对象和安装路径无关的 canonical byte contract，以便 source checkout 与 installed artifact 产生相同身份。
123. 作为 Workflow 作者，我希望 Compiler 知道 selected Binding 的每个评分输出能够保证产生哪些 Observations，以便不可满足的 Selection Objective 在执行前失败。
124. 作为蛋白质工程师，我希望 pairwise Context selector 可以在限定 Score Collection 中为每个 subject 匹配其 exact counterpart，以便动态 reference identities 不退化为自由字符串或 lineage 猜测。
125. 作为后端客户端开发者，我希望 REST、WebSocket 和 structured errors 由一个版本化、机器可读的 public protocol contract 驱动，以便最高层验收与未来前端共享同一 interface。
126. 作为运行维护者，我希望 Execution Plan 中每个 Node 最终都有一个权威 Node Disposition，并在 coordinator restart 后安全闭合，以便 blocked 或未调度 Node 不从 Ledger 消失。
127. 作为蛋白质工程师，我希望 SimpleFold confidence 只声明和加载真正影响该计算的 featurization 与模型资产，以便 Readiness、Method identity 和 provenance 既不遗漏也不夸大依赖。

## Implementation Decisions

1. v2 是发布前破坏性合同重置，也是完成后唯一受支持的 backend runtime；不建设 v1
   Workflow migrator、dual reader、Score alias、old Cache/manifest replay 或 pLDDT
   scale guessing。
2. v1 已修复的科学和执行行为是必须重新证明的功能基线；v1 目录、registration、
   scoring、Cache 和 evidence shapes 不是兼容要求。
3. 后端继续串行拓扑执行；Node failure 只阻塞依赖分支，无关分支继续。
4. Module Package 是唯一 repository-owned extension module。一个包可贡献多个 Node
   Types，并共享 implementation、Adapter、资源和 tests。
5. 每个包只提供一个 immutable typed Module Package Registration，显式列出
   Node/Metric resources、Methods、Bindings、Port Types、Utility Transforms、lazy
   factories、Availability 与 Readiness declarations。
6. Contract Test Kit cases、fixtures 与 source-local tests 不属于 production
   registration，也不进入 production artifact。
7. 启动只发现一级 Module Packages 和固定 registration；禁止 recursive Definition
   search、glob、helper enumeration、per-Node `register()` 与 import side effect。
8. 可选 provider dependency 不在 package import 时 eager load；缺失条件由
   Binding Availability 表达。
9. Catalog Builder 接收 registrations，完成 resource parsing、reference closure、
   ownership、version、digest、conflict 与 Availability validation，返回完整
   FrozenCatalog 或结构化 startup failure。
10. Catalog Builder 在临时状态中完整解析，全部成功后原子发布 immutable
    FrozenCatalog；不得暴露 partial Catalog。
11. FrozenCatalog 是 Node Types、Methods、Bindings、Metrics、Port Types、Utility
    Transforms 和 Binding Availability 的唯一运行时查询 interface。
12. Compiler、Run admission、executor、project persistence 和 public catalog query
    使用同一个 FrozenCatalog；删除平行 Definition Registry、factory map、provider map
    和 implicit Type Registry。
13. 每个 Node Type 恰好有一份 Node Definition YAML，只声明 identity、display
    metadata、Ports/groups 和 cross-Binding Node parameters。公共字段包括
    `schema_version`、`node_type_id`、`version`、`title`、`summary`、`category`、
    `inputs`、`outputs`、`parameter_groups` 和 `node_parameters`；每个 Port 声明
    name、Port Type ID/version、required、multiplicity 与 scientific meaning。
14. Metric Definition YAML 只声明 identity、shape、unit、direction、range、
    granularity、aggregation、validity/masking 与 Observation Context schema。公共字段
    包括 `schema_version`、`metric_id`、`version`、`title`、`description`、
    `value_shape`、`unit`、`direction`、`canonical_range`、`granularity`、
    `aggregation_semantics`、`observation_context_schema` 和 `validation_contract`。
15. Method、Binding、Port Type、Utility Transform、factory、Availability 和
    Readiness 使用 immutable typed registrations。每个 Binding 固定 `binding_id`、
    version、所属 Node Type ID/version、Method ID/version、Binding parameter contract、
    lazy implementation/Adapter factory、Availability/Readiness declarations、
    determinism/cacheability、result-affecting implementation identity，以及闭合的
    Produced Observation Interface。每项 Produced Observation 声明 exact output
    Port、Metric reference、canonical Context profile、subject grain/source role 和
    guaranteed multiplicity；Method 由 Binding 派生，不重复 Metric Definition 已拥有的
    shape、unit、range 或 Context schema。
16. YAML 不包含 factory、provider probe、credentials、device、path、Environment
    Configuration 或 test cases；unknown field/schema 和 incomplete contract fail
    closed。
17. Definition 在 Catalog build 时只加载一次；implementation 不得再次解析或独立持有
    第二份 Definition。
18. 每个 contract 使用 exact ID、version 与 contract digest；禁止 version range、
    `latest`、automatic upgrade 和 silent fallback。Binding digest 包含 immutable
    Availability/Readiness declarations、Produced Observation Interface 和 observation
    propagation declarations，但不包含 startup 或 Run 的 observed conclusions。
19. Node Type 表达科学操作；Method 固定算法、模型、checkpoint、featurization 与
    scientific source；Binding 固定 Node Type、Method、execution route 与 result-affecting
    implementation identity。
20. Binding 关联 direct implementation 或 required Adapter；registration 持有对应
    lazy factory，factory 不冒充 Adapter。
21. Node parameters 只容纳跨 Bindings 科学意义相同的参数；Method/Adapter-specific
    parameters 属于 Binding parameters。
22. Environment Configuration 由 trusted backend 按 Binding scope 注入；credentials、
    device、endpoint 和 runtime path 不进入 Workflow。
23. result-affecting environment identity 进入 Method、Binding 或 Result Identity；
    performance-only environment choice 不进入 Result Identity。
24. Port Type 是显式、版本化 nominal contract，包含 validator、canonical codec 与
    content-digest procedure。
25. Port compatibility 只接受 exact type ID/version；unknown string 不产生类型，
    structural similarity、subtyping、implicit coercion 和 version range 不兼容。
26. 科学转换由显式 Node Type 表达；Port Type validator/codec 同时服务 input
    validation、output publication、Result Identity 和 Cache serialization。
27. Workflow 顶层保存 `schema_version`；Node Instance 保存 `node_id`、
    `node_type_id`、`node_type_version`、`binding_id`、`binding_version`、
    `node_parameters` 和 `binding_parameters`；Method 只由 Binding 派生。Workflow
    还保存一个去重的 Contract Lock，逐项固定其可达 Node Type、Binding、Method、
    Metric、Port Type 和 Utility Transform 的 kind、exact ID/version 与 expected
    contract digest，而不锁定整个 FrozenCatalog。
28. Workflow Compiler 一次完成 schema、DAG、Binding ownership、Port、parameter、
    Availability、Metric、Method、Context、Selection Objective、Utility Transform 和
    contract digest resolution。它必须先从当前 FrozenCatalog 重新求出 Workflow 可达
    合同闭包并验证 Contract Lock；缺失、重复、不完整、陈旧额外或不相等的 entry 都在
    Availability evaluation、provider probe 或 implementation construction 前以
    `contract_digest_mismatch` fail closed，不可达合同变化不得使 Workflow 失效。
29. Compiler 成功返回 immutable Execution Plan；executor 不接收 unresolved Workflow，
    也不重新查询 mutable registry。Execution Plan、Manifest 与 Ledger provenance 保留
    Workflow revision、Contract Lock identity 和逐项相等的 resolved contract digests；
    只有显式 authoring/rebind/relock 才能产生新 Workflow revision，load、save、compile
    和 Run 不得自动刷新 Lock。
30. Availability 是 startup Binding snapshot，Readiness Attestation 是 Run-scoped
    point-in-time conclusion，Engine Invocation 是实际进入 scientific engine seam；
    三者不能互相替代。
31. Run admission 在任何 Cache lookup 或 implementation construction 前，为全部
    distinct selected Bindings 获得 passing Readiness。
32. Cache hit 不绕过 Readiness；v2 不提供 provider unavailable 时的 implicit offline
    replay。
33. volatile prerequisites 每个 Run 重新观察；expensive immutable proof 仅按声明的
    identity、scope、age、configuration fingerprint 和 invalidation contract 复用。
    每份 attestation 记录 exact Binding、Readiness contract digest、safe environment
    fingerprint、observation time、conclusion 与 proof source，但不记录 secret、
    secret-derived hash 或 unsafe diagnostics。
34. 禁止 zero-argument process-global Readiness cache；Readiness 从 resolved Binding
    declaration 推导，不从 legacy module ID、provider alias 或 mutable `model_name` 推导。
35. provider/model/runtime-specific Availability 和 Readiness knowledge 归所属 Module
    Package，不归 Core static map。
36. Executor 只消费 Execution Plan、FrozenCatalog、Run-scoped Environment
    Configuration 和 project run resources，并通过 Binding lazy factory 构造执行对象。
37. Node input/output 均通过 Port Type validators；只有 complete、valid、canonically
    encoded output 才能发布成功或进入 Cache。
38. Run Evidence Ledger 是 typed run facts 的唯一 durable writer。
39. 每个 scheduled Node Instance 产生 Node Execution Attempt；每个 admitted
    Execution Plan 中的 Node Instance 最终另有且仅有一个 immutable Node Disposition。
    Cache miss/bypass 后 implementation 实际运行才产生 Operation Attempt；实际跨
    engine seam 才产生 Engine Invocation。
40. Cache hit 不产生 Operation Attempt 或 Engine Invocation；一个 Operation Attempt
    可以包含零个、一个或多个具有 parent-child role 的 Invocations。
41. 每个 started Node Execution Attempt、Operation Attempt 与 Engine Invocation 恰有
    一个 terminal：succeeded、failed、cancelled、interrupted 或 outcome_unknown；下层
    outcome_unknown 不得被提升为 Node success。
42. engine 成功后发生 decode、normalization、validation 或 post-processing failure
    时，Invocation 保持 succeeded，外层 Operation/Node failed。
43. worker 或 coordinator loss 使用 interrupted 或 outcome_unknown；reconciliation
    只能追加事实，不能改写或臆造 success。retry 使用新的 Run、attempt 和 invocation
    identities，不在原 Run 中隐式续跑。
44. fact 在 projection/publication 前完成 schema/causal validation、redaction、durable
    persistence 和 monotonic sequence allocation。
45. manifest、JSONL 和 WebSocket 是 Ledger projections；projection failure 不改写
    persisted fact，evidence commit failure 阻止 Node success 与 Cache write。
46. Result Identity 使用 `protein-workbench-cache/v2` namespace，并包含全部
    result-affecting Node、Port、Binding、Method、Adapter、implementation、model、
    checkpoint、source、input、parameter、randomness、Metric、Context 和 Utility
    contracts。
47. Project ID、Run ID、Node Instance ID、credentials、private paths、timestamp、
    presentation metadata 和 performance-only choices 不进入 Result Identity。
48. result-affecting identity 无法可靠解析时禁用 cross-Run caching。
49. physical Cache 保持 Project-scoped；只存经 Port Type codec 编码的 complete、
    successful、validated、cache-eligible typed values，不存 paths。
50. failed、cancelled、interrupted、outcome_unknown、partial、uncontrolled stochastic、
    insufficiently identified remote 和 required standalone-artifact results 不缓存。
51. 同一 Result Identity 出现不同 output 或 contract metadata 时返回
    `cache_identity_conflict`，禁止 overwrite 或 first-write-wins。
52. Cache replay 记录 current-Run materialization 与 producer provenance，不复制旧
    Availability、Readiness、Operation Attempts 或 Engine Invocations。
53. Candidate identity 从 producer Result Identity、output/sample slot、parent
    Candidate identities 和 content digest 稳定派生；不使用 Run UUID，也不只用 digest。
54. Score Observation identity 是 Candidate、Metric、Method 和 typed Observation
    Context；Value 不属于 identity。
55. intrinsic Context 固定；pairwise/reference Context 使用 typed roles、reference
    Candidate identity/digest、pairing mode 和 result-defining normalization。公开
    subject 始终是被评分 Candidate；Adapter 隐藏底层 reference/mobile 调用顺序。
56. 同一 observation identity/value 可去重；同 identity 的冲突 value 或 undeclared
    multiplicity fail closed，除非显式 aggregation Node 规定处理。
57. Selection Objective 由 Workflow 拥有，固定一个明确的 Score Collection
    input/source partition、Candidate input、Metric、Method、canonical Context profile、
    per-subject match cardinality、Utility Transform ID/version/parameters、weight 和
    missing policy。Context selector descriptor 本身 exact 且 canonical，但不预先枚举
    Run 时才产生的 Candidate identities；每个 subject 的零匹配或多匹配默认 fail
    closed。
58. Utility Transform 是 FrozenCatalog 中受控、版本化的 `[0, 1]` mapping；Workflow
    不提供 arbitrary Python。
59. weights finite、non-negative 且至少一个 positive；执行时归一化并记录 declared 与
    effective weights。禁止 negative weight、implicit direction reversal、dataset
    min-max、range guessing 和 raw Metric addition。
60. public pLDDT 固定为 `structure.plddt.per_residue` 与
    `structure.plddt.mean_residue` 两个 `[0, 100]` Metrics；mean 是 valid protein
    residues 的 equal-weight average。ESM-3 与 ESMFold2 native `[0, 1]` 值乘以
    100，SimpleFold high-level `[0, 100]` 保持不变，direct confidence-head
    `[0, 1]` 值乘以 100。
61. SimpleFold folding 与 existing-structure confidence 是不同 Node Types；confidence
    Method 固定 `simplefold_1.6B.ckpt` latent checkpoint、
    `plddt_module_1.6B.ckpt` output head、`esm2_t36_3B_UR50D.pt` encoder，以及
    版本化 structure-featurization descriptor、`ccd.pkl` immutable content digest、
    upstream source、Adapter 和 native-to-canonical scale identities。`ccd.pkl` 参与
    residue reference features，因此其 declared digest 进入 Method/contract identity，
    resolved digest 进入 Binding Readiness、Result Identity 与 Invocation provenance。
62. SimpleFold confidence 使用 ESM2 representation-only 路径，不加载或探测
    `esm2_t36_3B_UR50D-contact-regression.pt`，也不加载或探测 `boltz1_conf.ckpt`；
    二者不得出现在该 Method identity、Readiness prerequisite 或 Invocation provenance。
    未来实际使用 contact prediction 或 Boltz confidence 必须建立新 Method/Binding。
    结果相关 pipeline 变化同样建立新 Method/Binding。
63. 生产能力归并为 `prompt_authoring`、`esm3`、`folding`、`proteinmpnn`、
    `structure_annotation`、`structure_comparison`、`structure_transform`、
    `protein_io`、`selection`、`collection_ops` 和 `solubility`。
64. ESMFold2 与 SimpleFold folding 是同一 folding Node Type 的不同 Bindings；
    SimpleFold confidence 保持独立 Node Type。
65. 重复 structure annotation glue 收敛；ambiguous cross-Metric confidence
    aggregation 不原样迁移；echo 只保留为 Contract Test Kit fixture。
66. SoluProt full/no-TM 是不同 Methods/Bindings；Protein-Sol percent-sol、
    scaled-sol 和 pI 是不同 Metrics；population-sol 是 baseline/calibration Context。
67. 迁移采用 replace-don't-layer：新 interface 的最高 seam tests 通过后删除旧
    registration、double Definition load、factory/provider maps、implicit types、legacy
    Workflow、pickle Cache、path outputs、parallel evidence writers 和 old score model。
68. 具体实施依赖顺序为 Port Types 与 Catalog、Workflow Compiler、Environment/
    Readiness、Evidence Ledger、Result/Candidate identity 与 Cache、Metric/Utility、
    11 个 Module Packages、examples/fixtures 和最终 acceptance。
69. Private Run workspace 的物理抽取是内部选择，但现有 path containment、no-follow、
    owner/mode、symlink resistance 和 cleanup failure 不覆盖 primary failure 的不变量
    必须保留。
70. existing REST/WebSocket route names 和 v1 payloads 非规范。v2 public protocol
    使用 `protein-workbench-public/v2` schema namespace，并由一个版本化、机器可读、
    closed-field contract bundle 作为唯一 interface 真相；同一 source 定义驱动 backend
    models、REST schema、WebSocket event/error schema 和 acceptance client，禁止另写一套
    手工 payload 真相。bundle identity 使用同一 I-JSON、RFC 8785、UTF-8 与 SHA-256
    canonical byte rules。
71. public protocol 只暴露高杠杆操作：Catalog Snapshot、Project/Workflow Snapshot、
    Workflow Compile、Start Run、Start Derived Run、Cancel Run、Run Projection、Run
    Event Stream 和 Artifact Retrieval。Compile 返回 compact receipt 与结构化 issues，
    不公开 private Execution Plan；Run Projection 聚合 terminal state、Node
    Dispositions、Ledger cursor、typed outputs 与 artifact index，不机械复制内部 Ledger
    或 v1 的平行状态 stores。
72. protocol bundle 固定每个 REST operation 的 method、route、request/response 和
    status mapping，以及 WebSocket envelope、event union、cursor/replay、close/error
    semantics。Run Event Stream 使用 opaque `after_sequence` cursor，从 durable replay
    切换到 live 时不得遗漏或重复 public event，并可在 backend restart 后从 Ledger
    重建。所有 transport 共享一个版本化 structured-error vocabulary；details 有闭合
    schema、大小限制和 redaction。
73. Catalog Snapshot 返回 stable Catalog contract identity、公开 contracts，以及具有独立
    observation identity/time 的 Binding Availability snapshot；observed Availability
    不进入 stable Catalog contract identity。
    Workflow Compile 验证 Contract Lock 并返回 Workflow/Catalog/Execution Plan digests；
    Start Run 绑定 exact Project、Workflow revision 与 compile identity；Start Derived
    Run 引用 immutable source Run、声明 retry/force policy 并创建全新 Run identities，
    不原地续跑或改写 source evidence。Cancel 的重复调用、已终结 Run 和 completion race
    由 Ledger sequence 给出确定结果。Artifact Retrieval 只接受 Run Projection 声明的
    opaque reference，并重新验证 Project/Run scope、Port、Candidate/standalone kind、
    media type、size 和 digest。
74. 所有 contract digests 使用 descriptor namespace
    `protein-workbench-contract/v2`。每个 contract kind 具有 closed canonical
    descriptor schema：Node Type 覆盖 scientific Ports 与 Node parameter contracts；
    Metric 覆盖 value、unit、direction、range、granularity、aggregation、validity 和
    Context schema；Method 覆盖 algorithm/model/checkpoint/featurization/source/scale；
    Binding 覆盖 Node/Method references、Binding parameters、behavior identities、
    Availability/Readiness、determinism/cacheability、implementation identity 与 Produced
    Observations；Port Type 覆盖 validator/codec/content identity；Utility Transform 覆盖
    compatible input contract、parameters、behavior identity 和 `[0, 1]` output contract。
    每个 descriptor 还包含 kind、exact ID/version、materialized defaults、owned
    declarations 和 external reference 的 exact ID/version/digest，但不包含自身 digest。
    语义有序集合保留顺序，语义无序集合按稳定 identity 排序；presentation-only metadata
    不进入 Workflow Contract Lock 或 Result Identity，但进入 stable Catalog contract
    identity。observed Availability/Readiness 不进入任何 stable contract identity。
    digest reference graph 必须 acyclic；cycle 是 malformed contract。
75. canonical descriptor 只允许 I-JSON values，按 RFC 8785 JSON Canonicalization
    Scheme 生成 canonical JSON，再编码为 UTF-8 bytes 并使用 SHA-256。公开 digest 格式
    固定为 `sha256:` 加 64 位小写十六进制；Unicode strings 按 validated input 原样保留，
    不做隐式 normalization。negative zero、NaN、Infinity、duplicate keys 或不可规范化
    value 使 Catalog build 原子失败。改变 descriptor schema、canonicalization 或 hash
    algorithm 必须使用新 namespace。
76. Python callable、object repr/address、import/source/install path、source text、
    bytecode 和 code object 不进入 contract descriptor。validator、codec、content-digest
    procedure、factory、Adapter、Availability/Readiness checker、observation propagation
    和 Utility callable 必须注册显式稳定的 behavior ID/version 与 immutable declaration
    parameters；行为变化必须更新 identity/version。实际 source、binary、model、
    checkpoint 和 provider artifact identities 仍进入 Method、Result Identity 与
    Invocation provenance。
77. Workflow Contract Lock 只锁定 Workflow 可达合同闭包，不锁定整个 FrozenCatalog；
    observed Availability/Readiness、Environment Configuration、credentials、private
    paths 和 diagnostics 不进入 Lock。Lock entries 按 contract kind、ID、version 稳定
    排序，Lock identity 使用同一 canonical byte/digest rules。显式 relock 必须基于一个
    已验证 Catalog 并形成新 Workflow revision；runtime 不得静默修复 mismatch。
78. fixed score producers 声明闭合 Produced Observation sets；Score Collection
    transform Nodes 声明受控、版本化的 pass-through/union/filter propagation contract，
    保留 source partitions，不执行 arbitrary query code。Compiler 由此计算每个 output
    Port 的精确 observation capability；若 selected objective 不可满足或 source scope
    仍歧义，则在 provider call 前失败。
79. Node Disposition outcome 固定为 succeeded、failed、blocked、cancelled 或
    interrupted；成功另记录 executed 或 cache_replayed resolution。blocked 引用使
    required inputs 不可满足的直接 upstream dispositions，且不产生 Attempt/Invocation；
    调度前 cancellation 同样只有 Disposition。Run terminal 只能在每个 Plan Node 有且
    仅有一个 Disposition、每个 started Attempt/Invocation 有且仅有一个 terminal 且因果
    引用闭合后提交。coordinator restart reconciliation 必须幂等追加 interrupted、
    outcome_unknown、blocked 或 cancelled facts，禁止发布未证明的 output/Cache，并使
    原 Run 终结为 interrupted。
80. 本规格不自动删除 development Projects、Cache 或 Run records；实际 cutover cleanup
    需要单独、精确授权。

## Testing Decisions

1. 测试只断言可观察合同，不锁定 private class、helper、内部目录、Ledger 物理格式或
   transitional call graph。
2. 主系统 seam 是一个从 installed artifact 启动的真实 backend process。首个 public
   contract test 先要求版本化 protocol bundle 存在且闭合；其后测试客户端只使用 bundle
   声明的 REST、Run Event Stream、Run Projection 和 Artifact Retrieval，并据此校验所有
   payload/event/error，不导入 production internals，也不依赖前端。
3. 唯一补充 package seam 是 Contract Test Kit 对 production Module Package
   Registration 的 conformance 测试；它接收 registration 与独立 cases，建立隔离的
   temporary FrozenCatalog，编译最小 Workflow，并通过统一 execution interface 验证
   外部合同。新增包和迁移包都必须通过同一套工具。
4. 更低 seam 只在主系统 seam 不能精确定位时使用，限于 Port Type validator/codec、
   Adapter boundary、Metric/Utility math、Result Identity canonicalization 和危险
   filesystem/process behavior。
5. 沿用现有 verification prior art：routine regression、deterministic backend
   acceptance、installed-package、local-provider、heavy-model、live-provider 和 fresh
   canonical 3GB1 tiers，但将它们的断言迁移到 v2 contracts。
6. Routine tier 必须 deterministic、isolated，并排除 remote provider、large model 和
   credential use；required provider tiers 必须 zero skip。
7. Catalog tests 必须覆盖 successful atomic publish、malformed package、unknown field/
   schema、duplicate identity、digest conflict、dangling/cyclic reference、lazy optional
   dependency、unavailable sibling Binding 和绝无 partial FrozenCatalog。Node、Metric、
   Method、Binding、Port Type、Utility Transform 与 Availability/Readiness declaration
   都必须具有 canonical descriptor bytes 和 SHA-256 golden vectors。
8. Installed-artifact tests 必须从 source checkout 外启动，确认 source 与 artifact
   解析出相同 FrozenCatalog、canonical descriptor bytes、contract digests 和 public
   protocol bundle digest，Definitions/resources 完整且 package-local tests 未打包。
9. 零 Core 修改扩展 test 必须添加一个 conforming test Module Package，通过 startup
   discovery、Catalog query、Workflow compile、execution 和 Contract Test Kit，而不改
   Core dispatch。
10. Port tests 必须覆盖 exact ID/version compatibility、unknown type failure、contract
    digest conflict、canonical codec round trip/content digest，以及只能通过显式 conversion
    Node 连接不兼容类型。
11. Workflow tests 必须覆盖 v2 schema、exact Node/Binding versions、separate parameters、
    Binding ownership、no latest/range/fallback、objective references、immutable Execution
    Plan 和 structured `unsupported_schema_version`。在 Catalog A 锁定后，Catalog B
    以相同 ID/version 改变任一可达 Node、Binding、Method、Metric、Port Type 或 Utility
    contract 时，必须在 Availability/probe 前返回 `contract_digest_mismatch`；Lock
    缺失、重复、不完整、陈旧额外 entry 同样失败，而不可达 Catalog 变化不影响编译。
12. Readiness tests 必须证明每个 Run 在首次 Cache lookup 前评估全部 distinct selected
    Bindings，同 Binding 多 Node 可共享 attestation，不同 Bindings 即使共享 provider
    仍各有 attestation。
13. Readiness mutation regression 必须在首次通过后替换 credential、binary、model file、
    directory 或 configuration fingerprint，确认后续 Run 不接受 stale green。
14. proof reuse tests 必须覆盖 declared scope/age/fingerprint/invalidation，并证明
    zero-argument process-global cache 不存在。
15. evidence tests 必须覆盖 Cache hit 无 Invocation、Operation 内零/一/多 Invocations、
    Node Disposition coverage、terminal uniqueness、retry identities、post-processing
    failure、worker/coordinator loss、cancellation 和 evidence persistence failure。
    Cache replay 的 Disposition 是 succeeded/cache_replayed；blocked 和调度前 cancelled
    Node 没有 Attempt/Invocation。
16. Ledger tests 断言 causal closure、monotonic ordering、projection equivalence 和
    restart reconciliation。真实 backend 在 Node/Operation/Invocation 已 started 未
    terminal 时被终止并以同一 storage 重启后，必须幂等补齐安全 terminal 和每个 Node
    Disposition，禁止伪造 success、发布 output 或写 Cache；再次重启不得产生第二个
    terminal。不得把历史固定 89 calls 作为 v2 invariant。
17. Cache tests 必须覆盖 canonical Result Identity、excluded runtime/UI fields、
    unresolved identity disables caching、Project isolation、typed codec storage、path
    rejection、including outcome_unknown 的 non-cacheable outcomes、replay provenance
    和 `cache_identity_conflict`。
18. Candidate tests 必须证明 identity run-independent，正确纳入 producer/output/sample/
    parents/content，并在 Cache replay 后保持不变；冲突 content 或 lineage fail closed。
19. scoring tests 必须覆盖 Produced Observation Interface、fixed/propagated capability
    sets、完整 observation identity、intrinsic/pairwise Context、一个 Method 多 Metrics、
    一个 Metric 多 Methods、duplicate/conflict、Utility resolution、non-negative
    normalized weights 和 explicit missing policy。selected Binding 不保证目标
    observation、source partition 歧义、Context role/profile 不符或每个 subject 的匹配数
    不是声明 cardinality 时都必须 fail closed。
20. pLDDT differential tests 必须以 provider-native fixture 验证静态 normalization 到
    `[0, 100]`、valid-residue mean 和绝无 range guessing。
21. SimpleFold heavy-model test 必须证明 confidence Binding 的 model/data artifact
    closure 恰好包含
    `simplefold_1.6B.ckpt`、`plddt_module_1.6B.ckpt`、
    `esm2_t36_3B_UR50D.pt` 与 `ccd.pkl`，并在 Readiness/Invocation 中记录精确 digests。
    `ccd.pkl` 缺失或不匹配时不得 ready；contact-regression、`boltz1_conf.ckpt` 和未使用
    的其他 SimpleFold model checkpoints 即使不存在仍应成功，任何 open/stage/probe 都使
    测试失败；source/Adapter identities 另按 Method 和 Binding contract 验证。pipeline
    identity 变化产生新 Method/Binding。
22. extension acceptance 必须覆盖本地 ESMFold2、本地 ESM-3、SoluProt 和 Protein-Sol，
    并证明它们通过统一 package seam、无需 Core special case。
    - 本地/远程 ESMFold2 必须是同一 folding Node Type 的显式 Bindings，测试不得允许
      Availability-driven fallback。
    - 本地 ESM-3 必须复用同一 esm3 Package 的 sequence、structure 和 paired
      generation contracts，model/path/device 不得从 Workflow 注入。
    - SoluProt full 与 no-TM 必须分别验证 Method identity 与独立 Readiness；full 的
      外部依赖缺失不得阻止 no-TM Binding。
    - Protein-Sol golden cases 必须分别保留 percent-sol、scaled-sol、pI 和 population
      baseline/calibration semantics；不得按字段名猜范围、silent clamp 或压成一个
      `score_id`。
23. canonical 3GB1 deterministic acceptance 必须重新证明 track fidelity、ten paired
    ESM-3 Candidates、两个彼此隔离的 TM-score objective scopes、weighted top three、
    3 ProteinMPNN parents × 5 children、complete lineage、15 final folds 与 15 run-bound
    PDB hashes。fixed-3GB1 objective 对所有 subjects 使用同一 participant；paired-ESM3
    objective 对每个 folded subject 恰好匹配一个不同的 exact counterpart，二者不得
    交叉匹配或依赖 collection order/lineage guessing。
24. canonical 3GB1 fresh acceptance 必须绑定 clean current source、FrozenCatalog contract
    digests、Execution Plan、effective seeds、Readiness、Cache decisions、Ledger closure、
    Candidate lineage、Invocations 与 artifacts；历史 v1 bundle 不能满足 v2 gate。
25. acceptance 检查 actual engine seams 和 causal closure，不固定历史调用总数；数据相关
    nested/tie-break Invocation 必须按真实 parent-child relationship 出现。
26. failure acceptance 必须覆盖 invalid Workflow 在 provider call 前失败、Readiness
    failure 在 Cache 前失败、Node failure 只阻塞 downstream、unrelated branch 继续、
    real cancellation、Project/Run isolation、cross-scope read rejection 和 safe errors。
    每个 terminal Run 的全部 Plan Nodes 必须恰有一个 Disposition，blocked Disposition
    必须引用直接 causal upstream facts。
27. security tests 必须继续覆盖 path containment、no-follow、ownership/mode、symlink
    resistance、secret redaction、bounded diagnostics、process cleanup 和 cleanup failure
    不覆盖 primary failure。
    已知的 secondary-structure layout shift、cross-Run export path reuse、SimpleFold
    staging collision、readiness/evidence omission 和 ESM-3 legal-symbol mutation 必须转为
    ordinary non-regression tests，而不是继续保留 intentionally-red gate。
28. cutover tests 必须证明旧 Workflow、Manifest 和 Cache schema 返回
    `unsupported_schema_version`，且 runtime 不执行 migrator、dual reader 或 silent
    conversion。
29. migration completion 不以保留旧 45 Node ID 或旧目录数为目标；测试 capability
    coverage、accepted scientific meaning 和 11 个 Module Packages。
30. 每个实现单元先建立 focused failing contract test，再通过 cumulative routine 与
    deterministic gates；provider-bearing或 storage/evidence 变更最终必须生成自己的
    source-bound acceptance。
31. contract digest differential tests 必须证明 YAML comments/key order、registration
    construction order、source/wheel path、Python object address 和等价 defaults 不改变
    canonical bytes；无序集合重排不变而语义有序 Ports 重排会改变。任一 included field、
    owned declaration、behavior identity/version 或 immutable parameter 变化必须改变
    digest；negative zero、NaN、Infinity、duplicate keys、缺失 behavior identity 和
    不可 canonicalize values 必须使 startup 原子失败。
32. public protocol acceptance journey 固定为 Catalog Snapshot → Project/Workflow
    Snapshot → Workflow Compile → Start Run → replay/live Event Stream → Run Projection
    → Artifact Retrieval，并另验 Start Derived Run。测试在任意 public sequence 断开并以
    opaque cursor 重连，覆盖 backend restart、compile/Lock rejection、Readiness
    rejection、cancel/completion race、cross-scope read、artifact integrity failure 和
    统一 error envelope；v1 route/payload 不得作为 fallback。
33. Contract Lock tests 必须证明显式 relock 形成新 Workflow revision，runtime 不自动
    刷新旧 Lock，Execution Plan、Manifest 与 Ledger projection 中的 resolved digests
    与 Lock 完全相等；observed Availability/Readiness 变化不产生 digest mismatch。

## Out of Scope

- 当前 React/ReactFlow 前端的修补、迁移或重写；前端在 backend v2 稳定后另立规格。
- v1 Workflow migrator、old Score aliases、dual-format readers、old Manifest/Cache
  compatibility、automatic pLDDT scale guessing 或 silent conversion。
- third-party `pip install` plugins、plugin management、runtime hot loading 和 automatic
  dependency installation。
- Python entry point discovery；未来只能作为相同 Module Package Registration 的另一
  loader。
- cross-Project physical Cache lookup、sharing 或 replay。
- classic Meta ESMFold。
- 修改 SoluProt、Protein-Sol 或其他 vendor/provider repositories；兼容逻辑属于
  Workbench Adapter。
- 自动删除 local Projects、Cache、Run records 或其他 development state。
- Run Evidence Ledger 的具体 physical format、private class/helper names 和内部源码
  拆分。
- 把 entire FrozenCatalog digest 锁进 Workflow、runtime 自动 relock，或允许同
  ID/version 的合同漂移被静默接受。
- 为 Context selector 建设 arbitrary lineage/relational query language；pairing 由
  Produced Observation contract、明确输入关系和 source-scoped cardinality 表达。
- 将 private Execution Plan、scheduler state 或完整 Ledger 物理结构逐字段暴露为 public
  protocol，或另维护一份与机器可读 protocol bundle 竞争的手写 payload 真相。
- 通过 Python callable repr、source path、source text 或 bytecode 生成 contract digest。
- 是否把 Private Run workspace 提取为独立 module；既有安全不变量仍是必须项。
- 各 Module Package 的最终 private implementation layout，以及不改变 accepted
  scientific grouping 和 public identity rules 的 implementation-level ID naming。
- 宣称某个 SimpleFold confidence Method 仅因模型更大就更准确。
- 在当前 SimpleFold confidence Method 中增加 ESM2 contact prediction 或 Boltz
  confidence；这些能力需要独立 Method/Binding。
- 为 current frontend 保留 accidental payload、state-management 或 display contracts。

## Further Notes

- 当前 runtime 仍是 legacy v1；v2 领域文档和 ADR 是目标合同，不是已实现状态。
- ADR-0018 至 ADR-0032 是本规格的架构基础；本规格进一步闭合其未规定的 Workflow
  Contract Lock、canonical digest bytes、Produced Observation、Context selector、
  public protocol 和 Node Disposition interface，superseded v1 ADR 只提供历史背景。
- `ready-for-agent` 表示上述 interface 已足以进入实现，不表示 v2 runtime 或 protocol
  bundle 已经存在。机器可读 protocol bundle 是 public behavior implementation 的第一项
  合同产物，而不是另一份手工维护的平行规格。
- RFC 8785 用作 deterministic JSON bytes 的既有 canonicalization precedent；Workbench
  仍由自己的 closed descriptor schemas 决定哪些语义字段进入每种 contract digest。
- 既有 sealed evidence 只证明其绑定的 v1 source revision；任何 v2 runtime 变更都必须
  生成新的 cumulative regression 和 source-bound acceptance evidence。
- canonical 3GB1 是不可替代的系统 acceptance；外部脚本不能代替缺失 Module Package、
  Node Type 或 backend evidence。
- 本地 ESMFold2、本地 ESM-3、SoluProt 和 Protein-Sol 是检验 extension interface
  depth 的案例，不是四个孤立 Node 实现。
- historical `89 calls` 是一次 v1 Manifest representation，不是 v2 acceptance constant；
  v2 以 Ledger causal closure 与 actual Engine Invocations 为准。
- provider/model availability 是实时外部状态；routine tests 不触发 live/heavy providers，
  required provider gate 在 unavailable、skip 或无 Invocation evidence 时失败。
- 当前 v1 SimpleFold provider contract 聚合了六个 assets；v2 confidence Binding 只继承
  被真实数据路径证明的依赖，不把 provider-wide inventory 当成 Method asset closure。
- physical cleanup 必须等待用户对精确目标的独立授权；接受本规格不授权删除任何数据。
