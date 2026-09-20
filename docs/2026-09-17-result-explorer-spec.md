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
