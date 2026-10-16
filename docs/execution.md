# Workflow 执行与结果发布

本文件区分已确认运行要求与当前实现。产品要求以[当前有效决策](documentation-governance-decisions.md)为准，术语见 [GLOSSARY](../GLOSSARY.md)。实现说明来自静态源码核对，不表示运行验收通过。

## Draft、Commit 与执行计划

允许手动保存未完成的 Workflow Draft，后续重新打开继续编辑。缺少必要节点、连线、参数或模块时不能运行，但保存与打开不应被可执行编译条件阻断。缺失模块时保留原节点、连线和配置，安装启用兼容模块后恢复使用。保存交互及当前差距见[工作区](workspace.md)。

当前 [Workflow authoring](../core/workflow/authoring.py)拥有 Draft 与 Commit。Commit 根据当前 Catalog 检查拓扑、名义 Port 兼容、参数和实际消费的评价关系，编译一个 Execution Plan 后持久发布可运行版本。Run 使用明确 `workflow_commit_id`，不直接执行正在编辑的 Draft。

Commit 保存 Workflow、来源 Draft 修订和解释原结果需要的最小定义快照，不保存 Python Execution Plan。运行时使用进程内计划，在需要重新装载时由同一 authoring owner 编译已有 Commit，再比较结果相关定义。定义不一致时拒绝当前执行，不改写旧结果解释记录。已完成结果的阅读使用原 Commit 事实，不把读取旧结果等同于重新批准旧 Commit 执行。

当前相关入口：

- [compiler.py](../core/workflow/compiler.py)生成已解析计划，只纳入本节点实际使用的 selectors/objectives 和结果相关定义。
- [authoring.py](../core/workflow/authoring.py)保存和读取 Draft/Commit，并处理 Commit 准入。
- [公共协议 bundle](../protein_workbench_public/resources/v2/bundle.json)定义 REST/WebSocket 当前载荷契约，调用者不维护另一套旧接口回退。

当前启动仍安装特定科学教学 Workflow，安装编译失败会阻止启动；这与空载体独立使用要求不一致。默认教学内容仍应保留，启动解耦属于已知差距，不是取消教学实例或吞掉程序错误的授权。

## 运行、失败与前后端边界

后端执行 Run。关闭前端不会取消仍运行的后端任务，取消需明确调用取消操作。同一项目计算期间禁止修改该项目，仍允许查看；当前公共修改入口通过 runtime 的项目修改锁与 Run 准入互斥；前端同时限制运行项目的编辑。未保存修改退出按保存、放弃、取消规则处理，与后端生命周期分开。

节点明确失败后，依赖该节点的后续计算阻塞，不受影响的独立分支继续。显示实际失败和阻塞，整次 Run 不冒充全部成功。模块内部按已定义工具运行结果处理失败，本地不变量错误直接失败；不通过宽泛 catch、猜测默认值或静默继续掩盖问题。

当前 [Run runtime](../core/execution/runtime.py)按 Execution Plan 的拓扑顺序调度，已连接上游失败时阻塞依赖节点，包括可选输入的连接；未连接的可选输入仍可缺省。它管理已发布值传播、取消及运行终结。[node_attempt](../core/execution/node_attempt.py)拥有一个节点从输入准备到最终发布的生命周期：

1. 准备已准入输入、Project Input 内容身份及有效随机性。
2. 计算 Result Identity，按本 Binding 的策略查缓存或绕过缓存。
3. 缓存未满足时，进入适用的 Readiness，再执行 Operation 及实际 Engine Invocations。
4. 准入新输出，完成必要清理，提交节点成果或真实失败。
5. 调度器据持久结论继续独立节点，最终形成 Run Closure。

输入准备前的失败不虚构已开始的调用。一个 Node Execution Attempt 可能仅重放缓存；一个 Operation Attempt 可包含零次、一次或多次引擎调用。引擎成功后仍可能因结果转换、输出准入或成果写入失败使外层操作或节点失败，各层结论分别保留。

### Availability 与 Readiness

启动 Availability 是诊断快照，不直接允许或禁止执行。当前 Adapter 路线首次缓存未命中或绕过缓存时检查 Readiness，同一 Run 内同 Binding 共享该结论；缓存重放不调用 Provider Readiness，直接实现不伪造 Provider 检查。

Readiness 只确认本次所需运行条件，不扫描安装树、模型内容或 Git 状态来建立身份体系。失败发生在 Operation 开始前时记作 Binding Failure，实际未开始的 Operation 和 Invocation 不补造。配置入口与现有实现见 [Provider 配置](provider-configuration.md)。

## Result Identity 与缓存

当前 Result Identity 由编译器固定的结果相关契约事实，加上规范输入内容、Node/Binding 参数、实际使用资源的内容身份及有效随机性组成。运行时直接使用计划事实，不重扫 Catalog。

布局、节点实例定位、Run ID、Project ID、参数定位标签以及文件名不是计算内容身份。相同内容换一个上传引用或文件名，不自动变成新的科学输入；改变输入内容或影响结果的参数则改变身份。当前设备选择和可接受的微小数值差异不拆成设备专属缓存身份，实际设备已知时可作为普通来源信息保留。

缓存目前按 Project 保存，是已成功发布结果的可选重放索引。命中时恢复原成果及来源，不伪造新引擎调用。缓存索引在节点持久成功之后写入，索引失败不改写已经发布的节点结论。对象存在或缓存存在本身都不是成果已经发布的依据。

当同一稳定 ID 的结果相关定义改变时，旧缓存必须按现行验证规则清除或隔离后才能执行。没有旧开发产物兼容承诺，不因此允许静默丢失用户保存内容，或因删除来源项目使已采用输入失效。

## 持久发布与读取

当前 [ResultStore](../core/execution/results/store.py)先将已准入值和 Artifact 字节保存为 Project-scoped 不可变内容对象，再由 [Run Evidence Ledger](../core/execution/ledger/ledger.py)提交成果可见性。只有持久发布的事实才成为正式输出，未被引用对象不能冒充成功结果。

一个节点结论通过一次完整的 Ledger transition 原子发布，关联实际 Operation 终态、Typed Outputs / Artifacts、节点终态和 disposition。Ledger 拥有合法因果顺序、序号、持久确认、reducer 和领域投影；调用者提交实际结论，不自己拼接原始事件序号或事务文件。公共层只把领域投影转换为协议，不另读内部事务建立第二套事实来源。

写入或确认失败不能返回成功。已经持久确认后的公共编码或连接失败，不撤销后端事实。清理失败保留其真实发生层次，不把实际完成的 Engine Invocation 改成外层错误。

Run Projection 和 WebSocket 只携带有界输出描述与运行信息，不嵌入完整结构或科学大数组。具体 Typed Value 按 Run、节点、Port、value index 单独读取，Artifact 按其媒体与引用契约取回。来源、顺序、内容摘要和文件名随正式描述保留。详情、展示和导出见[结果](results.md)。

重启从持久 Ledger 前缀重建运行状态。未完成 Run 记为 `interrupted`，不猜测缺失的引擎、操作、节点或筛选终态。关闭前端与后端进程中断是不同情况，没有据此前端退出后自动补发工具请求的规则。

运行记录只保留当前解释和执行需要的事实，不增加独立 Provider 日志权威、内容证明层级或通用事件存储框架。单值准入、编解码及存储完整性的分工见[架构](architecture.md#单次准入与表示)。

## 批内失败与主动继续

生成或折叠的一个节点可以依次执行多个独立请求。已确认行为如下：

| 情况 | 当前要求 |
|---|---|
| 一个请求在适用自动尝试范围内失败 | 沿用该现有路线的尝试上限和指定错误范围。 |
| 尝试耗尽仍失败 | 停止本批尚未开始的请求，整批明确显示未全部完成。 |
| 同批已有成功请求 | 保留其成功结果，允许查看和导出。失败工具的残缺输出不要求解析或修复。 |
| 节点失败后的下游 | 仍按依赖失败阻塞，保留成功数据不等于把整个节点改成成功。 |
| 用户主动继续 | 输入和计算参数相同时，跳过已成功请求，只重试失败和未开始部分。 |
| 输入或计算参数改变 | 作为新计算，不伪装为原批续算。 |

主动继续不增加自动重试次数。已核对 ESM3、ESMFold2 SDK 默认对指定错误最多总计五次尝试；这不是所有模块和错误的统一次数规则，也不能把一次 Engine Invocation 等同于一次 SDK 网络尝试。

**当前实现与差距：**[折叠实现](../modules/folding/implementation.py)与 [ESM3 生成](../modules/esm3/implementation.py)在已定义运行失败时交回此前完成的结果；联合生成中序列已完成而结构失败时保留该序列。[节点失败发布](../core/execution/_node_attempt_publication.py)将准入后的保留输出与失败结论一起持久发布，供查看和导出；不写成功缓存，也不将部分输出传给依赖下游。失败请求的残缺响应不被修复或伪装为结果。ESMFold2 已支持通过派生 Run 的 `continue_batch` 继续失败批次：固定原 Run 的 Commit，核对 Result Identity，恢复已完成结构与置信度，只执行失败和未开始请求。首请求失败也保留必要续算状态；再次失败仍停止未开始请求，成功后不再显示可继续能力。ESM3 的序列、结构和联合生成同样支持该续算入口：从持久结果恢复已完成样本及其置信度，联合生成的序列步骤已成功时只继续结构步骤。首请求失败及再次失败仍可主动继续；不会新增自动重试或调用已成功步骤。SimpleFold 的批内续算尚未实现。

Run 公共读取的 `continuable_node_ids` 只列出已终结 Run 中具有持久续算状态的失败节点。界面按此显示“继续批次”，明确继续原输入和参数；此操作不保存或采用当前画布修改。已有结果保持可读，成功祖先复用，所选节点成功后再执行其依赖后代，独立分支不重复计算。改变输入或参数后应启动普通新计算。

当前新增公共 API 与浏览器行为测试使用受控官方 SDK 成功/失败响应，覆盖结果保留、重开、累计续算和界面主动操作；这不证明真实 Biohub 线上调用通过，也未运行本地 ESMFold2 模型。

原子持久写入用于确保一次发布完整可靠，与保留已经成功请求并不冲突。这里没有决定废除原子发布、把残缺结果当成功，或增加新的证据和恢复系统。

## 节点范围运行与旧结果复用

当前节点范围实现见 [_run_runtime_scope](../core/execution/_run_runtime_scope.py)及[派生运行](../core/execution/_run_runtime_derived.py)：

- `full` 执行完整计划，遵守 Binding 缓存策略。
- `to_node` 执行所选节点及其祖先。
- `from_node` 执行所选节点及后代，执行范围绕过缓存；范围外必要祖先只从明确 source Run 的成功 publication 复用。
- `retry_failed` 选择原失败节点重跑，仍是节点范围，不等于批内主动续算。
- `continue_batch` 使用原 Commit 继续所选失败批次及其后代，复用范围外必需的成功祖先。

当前继续及派生运行要求 source Run 已进入终态。范围预览只返回节点范围、操作摘要和缺少的上游 publication，不准备输入、恢复结果或计算依赖实际值的 Result Identity，也不触发 Readiness 或 Provider。预览中依赖输入的随机性标为待输入；继续运行沿用当前 Commit 和输入的有效随机性解析，不隐式更换 seed。

复用检查实际内容与 Result Identity，不能用其他 Run 的缓存偷偷补上缺失祖先，也不重新调用应当复用的 Provider。范围外节点不被标成失败，复用记录保留真实 producer Run，不生成虚假 Operation 或 Invocation。当前实现要求 source Run、Commit 及所需成功 publication 明确，恢复不可读或身份不匹配时在本次接纳前失败。

历史结果直接采用、跨项目采用及采用后独立可用是已确认要求。节点范围复用只能证明上述特定路径，不能据此宣称全部采用场景已完成。用户构建后续画布流程，已决定删除的“保存为流程”操作不因复用要求保留。具体保存、复制、来源删除与结果选择见[工作区](workspace.md)和[结果](results.md)。

