# Protein Workbench 领域词汇

本文件定义交流和代码阅读所用术语。产品要求以[当前有效决策](docs/documentation-governance-decisions.md)为准；定义不表示功能已全部实现。职责、数据与差距见[架构](docs/architecture.md)，运行与持久发布见[执行](docs/execution.md)。

## 角色与扩展

| 术语 | 含义 |
|---|---|
| 项目用户 | 使用软件完成研究任务的人，选择输入、模块、计算参数、对象关系、区域与流程，并决定保存和运行；不承担内部实现与引用维护。 |
| 项目开发者 | 设计和维护整个软件项目的人，负责产品行为、模块开发规范、共享约定及载体的公共能力；不是用户创建某个蛋白项目的身份。 |
| 模块开发者 | 实现具体功能及专用界面的人，负责对象与位置对应、工具调用、参数约束和结果含义，并遵守公共接入与数据约定；包括官方模块开发者。 |
| 载体 | 提供模块管理、画布、流程编排、运行、保存及数据传递的应用基础。前端画布是其界面的一部分。 |
| 功能模块 | 围绕用户任务提供操作、节点及专用界面的功能单位；可以提供多个节点、使用多个工具。 |
| 工具 / Provider | 模块内部使用的模型、算法、外部服务或程序，不决定功能模块划分。 |
| Module Package | 模块的扩展交付单位，提供节点、数据类型、执行实现及所需界面等声明。官方与外部包遵守相同规范，不限定为仓库内源码。 |
| Module Package Registration | 当前后端生产注册契约，向 Catalog 提供 Node Types、Bindings、Methods、Port Types、Metrics、Utility Transforms 和运行条件等声明。 |
| Adapter | 工具边界的翻译实现，将模块输入和参数按工具接口传入，接回所需结果及已定义的运行失败。 |
| Environment Configuration | 凭据、服务地址、模型及外部程序位置等运行配置，与每次计算的节点参数分开。应用内设置的接入情况见架构文档。 |
| Provider Asset Closure | 一个 Binding 实际运行需要的文件和源位置集合；不是源码、检查点或安装身份的证明系统。 |

## 流程与编辑

| 术语 | 含义 |
|---|---|
| Node Type | 声明输入、输出、参数和操作含义的可复用操作。 |
| Node Definition | 一个 Node Type 的公开定义，声明稳定身份、Ports、跨 Binding 参数和用户可见含义。 |
| Node Instance | Workflow 中对一个 Node Type 的具体使用，带有明确 Binding、参数和连线。 |
| Workflow | Node Instances 通过兼容 Ports 连接成的有向无环图。 |
| Port | Node Type 的命名输入或输出，其值遵守一个 Port Type Definition。 |
| Port Type Definition | 跨 Port 值的名义类型契约，包括值准入、规范表示和内容身份；形状相同不代表可直接连接。 |
| Workflow Draft | 一次不可变的编辑修订，可以未完成，不能直接运行。 |
| Workflow Commit | 对满足运行条件的 Draft 发布的不可变可执行版本，保留 Workflow 和解释结果所需的最小定义快照。 |
| Project Workspace | 配对保存的 Draft 修订与 UI 修订。内存中的未保存修改与已保存版本分别表达。 |
| Execution Plan | 编译 Workflow 后供运行使用的进程内不可变计划，固定类型、实现、参数和必要关联；不是保存的 Workflow 文档。 |
| Authoring Capability Projection | 当前后端从 Catalog 声明生成的编辑能力投影，包括普通节点操作和专用编辑能力。 |
| Prompt Authoring Document | `prompt_authoring.author` 节点的非可执行 `document` 参数，记录来源、残基编辑、轨道条件、随机操作、合并和坐标变换。 |
| Prompt Authoring Preview | 对上述文档求值的未发布预览，包括规范文档、Prompt、实际随机选择、变化和诊断；不是运行结果。 |

## 执行条件与运行记录

| 术语 | 含义 |
|---|---|
| Method | 操作所用算法或模型变体的稳定定义，保留解释结果需要的含义；与 Provider 部署位置分开。 |
| Execution Binding | 一个 Node Type、一个 Method 及其直接实现或 Adapter 的可执行关联，声明路线参数、Availability 和 Readiness。 |
| FrozenCatalog | 当前后端构建后不可变的注册目录，供编辑与编译读取；不是面向用户的插件管理器。 |
| Availability | 启动时观察到的 Binding 前提条件与诊断，不作为运行授权。 |
| Readiness Attestation | 一次 Run 内、进入 Adapter 前确认所需运行条件的结论。缓存重放不需要 Provider Readiness。 |
| Binding Failure | Readiness 阻止进入 Operation 的节点失败，不虚构 Operation 或 Engine Invocation。 |
| Run | 对一个明确 Workflow Commit 的一次执行，具有自己的运行记录和终态。 |
| Node Execution Attempt | 一个节点本次被调度的结果记录，也包括完全由缓存重放满足的执行。 |
| Operation Attempt | 缓存未命中或绕过缓存后，节点实现的一次实际执行，可以包含零次、一次或多次 Engine Invocations。 |
| Engine Invocation | 一次实际进入声明的计算引擎边界；不等于一次 HTTP 请求或 SDK 内部网络尝试。 |
| Result Identity | 根据结果相关稳定定义、规范输入、参数和有效随机性形成的节点结果身份，用于当前缓存复用。 |
| Typed Output | 某个明确输出 Port 发布的有序值，保留名义类型、内容身份和实际产生来源。 |
| Artifact | 按声明媒体契约发布、可独立取回的文件成果，与 Typed Output 保持明确关联。 |
| Run Evidence Ledger | 每次 Run 的有序持久事实来源，供运行投影和事件流使用；仅保留执行与解释结果所需记录。 |
| Node Outcome Publication | 一次节点终结及其成果的持久发布；原子写入不等于可以丢弃批内已成功请求的结果。 |
| Run Closure | 所有实际节点完成后的正常运行终结；进程重启对未完成 Run 记录 `interrupted`。 |

## 数据、评价与区域

| 术语 | 含义 |
|---|---|
| Candidate | 序列或结构等操作对象，具有稳定身份、真实生成来源和数据。 |
| Candidate Collection | 有序的 Candidate 集合。集合顺序与对象之间的评价对应关系是不同信息。 |
| Candidate Data Reference | Candidate ID、名义数据类型和内容摘要组成的完整引用，可确定主体，不能替代完整 Candidate 的数据和元信息。 |
| Candidate Relation | 明确的 subject/reference 引用对组成的有序关系；指定本次比较或评价对象，不改写真实生成来源。 |
| ResidueLayout | 有序、身份完整的残基轴，长度及链顺序从残基身份派生。 |
| ResidueTrack | 自带一个确切 ResidueLayout、每个残基一个可空值的轨道；缺值含义由名义类型负责。 |
| CandidateResidueTrack | 一个明确 Candidate Data Reference 与其 ResidueTrack 的关联。 |
| ProteinPrompt | 当前条件编辑使用的残基对齐多轨道值，包括序列、命名原子坐标、可选二级结构和 SASA，以及功能标注；不是所有模块的通用输入语言。 |
| PDB String | 当前结构值使用的 PDB 文本表示。该内部表示不限定用户导入、导出格式。 |
| Resolved Structure Residue Axis | 对一个结构的明确解释，包括残基身份、序列、片段拓扑、坐标、mask、组分处理及修饰残基转换来源。 |
| Candidate-associated Resolved Residue Axes | 将每个结构主体与相应残基轴绑定的有序集合，不包含可替代完整 Candidate 的全部数据。 |
| Component Disposition | 结构解释中对实际组分包含、排除或需转换的明确决定及对应身份，不是简单按 ATOM/HETATM 猜分类。 |
| Prediction Residue Axis | 由本次实际预测输入形成的残基轴，与后来解析预测输出得到的结构残基轴分开。 |
| Prediction Key | 预测结构及对应置信度事实在 Candidate 身份建立前使用的关联键。 |
| Prediction Confidence Fact | 本次预测产生、尚未关联 Candidate 的置信度及其 Prediction Key、结构身份和预测残基轴。 |
| Confidence Materialization | 将上述置信度事实精确关联到已建立的结构 Candidate，形成 Score Observations，不重新预测。 |
| Metric Definition | 一个测量量的含义、值形状、单位、方向、范围及汇总语义。 |
| Observation Context | 解释评价值所需的实际对象、参考对象、区域等上下文。 |
| Observation Context Profile | 一组 Context 共用的固定条件，如参与角色与归一化方式，不能替代具体评价对象。 |
| Score Observation | 将一个 Candidate 与一个 Metric、Method、Context 及实际评价值关联的结果。 |
| Score Collection | 供分析、筛选和排序等操作消费的 Score Observations 集合。 |
| Utility Transform | 把指定评价量映射成无量纲 `[0, 1]` 值的显式转换。 |
| Selection Rule | 筛选节点拥有的条件、评价选择与排序设置；单指标使用原值和方向，加权排序使用指标提供模块声明的适用转换与权重。 |
| Structure Alignment Evidence | 已计算的结构对应、刚体变换、区域、归一化和 Method 等数据，供比较指标及展示使用，不要求扩建证据体系。 |
| Candidate-associated Scientific Value | 显式携带主体完整引用的派生值，关联不依赖平行列表位置。 |

