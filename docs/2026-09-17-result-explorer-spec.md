# Published Result Explorer

此增量规格落实集成计划 P0/P3。浏览入口为 Run、Node Instance、output Port、Typed Output value index，不能依赖最后一个 Selection 或整个 Run 成功。只读取已原子发布的值。

`result_collection` 对一个已发布 Candidate Collection 分页，保持其顺序；返回总数和每个条目的原始 item index、完整 Candidate Data Reference、全部 parent IDs、metadata、实际 sequence（序列候选）及结构是否存在。精确数据身份由 Catalog 的 nominal Port Type owner 在首次发布时计算并保存，浏览读取沿用已有身份。分页不创建新 Collection，不修改候选身份。`result_candidate` 按同一个输出定位及 item index 返回实际结构；item index 仅用于该不可变输出内取值，不用于关联 Score 或跨 Run 选择。

结构候选的序列只读取已发布的、以同一 Candidate Data Reference 关联的 Resolved Structure Residue Axis。没有该证据时展示“尚无已发布序列证据”，不在浏览器根据 ATOM/CA 推断序列，不继承任意 parent 的序列。需要完整 FASTA 时流程应显式包含相应 residue-axis operation。结构本身始终可以查看和导出；manifest 单独列出尚无序列证据的项。

Score 展示保留完整 subject、Metric、Method、Context、value、axis 和输出来源。等值关联键是 Candidate Data Reference 的三个字段；不同 Context 保持独立。多父谱系按全部 parent IDs 找到已发布的精确候选引用；无法解析或存在多个不同数据版本时显示实际引用列表，不任选一个。

视图焦点、勾选、临时筛选与排序分别存储。切阶段或筛选不会清除已勾选引用；导出明确显示隐藏勾选数量。保存为流程操作使用 Selection 的当前科学合同，科学修改作为一个 Draft 保存。

对齐叠加只消费已发布 Structure Alignment Evidence 的 subject/reference 和刚体变换；没有相应证据时只能并排比较，不自动对齐。导出包含实际值、完整来源、全部 parent refs 和科学定义，PDB 仅对应确有结构的项。

对齐显示按证据合同使用行向量 `subject_coordinate × row_vector_rotation + translation`，把 subject 映射到 reference 坐标框架。变换只作用于 viewer 中的坐标，原始发布 PDB 和导出 PDB 保持不变；显示具体 Method、RMSD、coverage 和来源，不将镜头旋转计入科学变换。

焦点和勾选保存输出位置及完整 Candidate Data Reference，每次投影刷新后从当前索引读取显示数据，因此后续发布的 residue-axis/sequence 证据会出现在现有勾选的详情和导出。导出 parents 列出每个 parent ID 对应的全部精确 Data References 及输出来源，分别标记 unresolved、resolved 或 multiple_data_versions，不能凭 ID 猜选内容版本。

临时条件按精确观察组及 Candidate Data Reference 计算 AND/OR；缺失或非唯一观察显示无法判断，不通过布尔短路隐藏。保存条件生成同样括号结构的普通 Selection Node；原值临时排序若保存为排名操作，必须在预览里选择 Utility Transform 和 N，再按公开科学合同执行。所有新增 Node/Selector/Objective 先处于可编辑预览，确认后整体保存 Draft，不修改旧 Run。

从下游阶段保存条件或 Top-N，直接连接当前 Candidate 阶段和原 Score 来源。Selection 按完整 Candidate Data Reference、Metric、Method、Context、partition 及成对引用匹配，缺失和歧义由匹配 owner 报错。Top-N 在当前阶段内执行。无需原始 population 选择、范围辅助节点或专用传播模式。

候选引用在首次发布时保存在现有 Port manifest。读取信任这些记录，不重算候选摘要或重新准入整个集合；分页仅解码当前页。首屏读取各集合第一页，翻页按需读取。对完整集合搜索、筛选和排序前明确加载全部候选；导出补齐父引用索引，不把尚未加载当作未发布。

Candidate Collection 的局部恢复由内置 codec owner 提供。其 interface 返回集合 ID、item type、总数和请求范围内的 Candidate，不创建新的科学 Collection。浏览 module 不解释内部 wire 字段，也不调用私有递归解码工具；它负责输出种类检查、详情越界错误和响应投影，并按恢复后的 Candidate ID 关联 manifest 中已有的精确引用。详情复用同一局部恢复路径，仅请求一个条目。

局部恢复信任既有发布链和已接收的请求参数，不重复执行完整 canonical 准入、集合谱系校验或摘要计算；选中条目继续使用既有递归解码及 datatype 构造行为。实现仍读取完整对象并解析完整 JSON，局部性仅指 Candidate 对象恢复范围，不代表磁盘局部读取。结构分页不返回 PDB，详情返回原始 PDB，不增加结构解释或替代存储格式。

## 统一结果读取状态

WebUI 的 `PublishedResults` module 是当前 Run 阅读的唯一 owner：同一 Session 持有 REST projection、事件订阅及 cursor、当前执行节点、诊断、连接信息和结果分页。App、Results Workbench、Selection 编辑器与导出共用其 snapshot，不另存执行结论或候选集合。结果归属取实际 `(project_id, run_id)`，个人 Project 引用示例结果时仍使用示例 Run 的归属。App 负责 Workflow 编辑、提交、启动与取消；阶段、显示页码、焦点、勾选、筛选和排序由视图负责。

节点完成与 Run 终态只取 REST projection。WebSocket 实时提供执行活动、诊断及连接信息，并触发 REST 刷新；回放完成时统一刷新，不逐条回放请求。收到完成事件后，正式完成状态在下一次 REST 返回时显示。事件 cursor 只表示已消费的事件位置，不由 REST snapshot 的 cursor 推进。启动回执与首次 REST 之间仍保留当前 Session，不能因此再次启动。

切换结果 Run 同步替换读取会话，旧会话的迟到成功或失败不能修改当前 snapshot，包括 A→B→A。相同 Run 的刷新保留已加载页面，并只读取新增或此前未成功读取的不可变输出；旧 projection 响应不能覆盖更新的请求。同 Run 刷新不作废候选分页请求。Commit 科学定义在会话内复用，读取不重新验证服务器响应或科学身份。

每个集合只有一个进行中的分页请求，所有消费者共享。offset 由 owner 的已加载数量决定，每页成功立即保留；失败直接报告，下一次明确操作从未完成位置继续，不自动重试。原始候选与发布证据各存一处，snapshot 统一派生序列视图，因此后到的 residue-axis 证据更新所有已加载页面。

首屏按每集合 100 条读取，显示页保持 50 条。普通翻页只补足当前集合；搜索、筛选和排序由用户明确加载当前集合全部候选后启用。导出与 Selection 编辑补齐全部已发布集合：前者需要完整父引用索引，后者允许编辑期间切换任意候选来源。补齐返回完成时的同一份 snapshot；期间接纳的新来源纳入完整性判断，不主动轮询或等待未来发布。

导出在点击时保留 checked keys，补齐后从返回 snapshot 重新取得候选、观察、序列及原 Commit 定义，不使用等待前的 Candidate 展示对象。旧会话的 Selection 打开请求直接结束；旧阶段的翻页完成不改变新阶段页码。读取阶段与输出是否存在分别表达，无输出的成功读取同样结束加载。
