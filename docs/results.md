# 数据输入、结果查看与复用

本文件维护输入、结果阅读、筛选和导出的有效约定，并标明现有实现差距。产品范围以[当前有效决策](documentation-governance-decisions.md)为准；问题证据与处理状态由[治理问题清单](2026-10-15-documentation-governance-issues.md)维护。功能模块职责见[模块能力](module-capabilities.md)。

## 序列输入

单条序列入口只导入一条记录。遇到含多条记录的 FASTA，提示用户改用批量导入，不能拼成一条序列。批量入口 `protein_io.import_sequences` 为每条记录生成一个独立候选，保持输入顺序，不按名称或相同序列去重。

现有批量 parser 接受 UTF-8、空行、序列内空白和 ASCII 小写规范化。空记录、非法字符或误置 header 定位到记录和行号，一条非法记录使整个导入失败，不跳过记录或发布部分集合。没有 header 的纯序列按一条记录处理；缺失名称显示 `Record N`，原 header 仍为空字符串。

候选 metadata 保留完整 header（不含 `>`）、源文件起始行号、从 1 开始的记录序号和文件名。候选身份来自正常输出发布，不以名称或序列去重生成。原始输入字节保持不可变。公共值允许的字符与具体工具可接收字符分开，由相关值合同及 Adapter 各自负责；当前说明不足以裁定所有特殊氨基酸在全部操作中的适用范围。

当前单条 parser 使用同一记录解析器并明确拒绝多条记录，错误提示引导使用批量入口；不会拼接多条序列。[FASTA 实现](../modules/protein_io/fasta.py)与[输入 UI](../webui/src/InputSourceDialog.tsx)是核对入口。

## 结构输入与组分

已确认的结构能力是：

- 导入与导出均支持 PDB、mmCIF；导出格式由用户选择，包括结果页导出。工具需要的格式由 Adapter 转换。
- 每次只导入一个结构文件；单文件包含多个构象时，可以选一个，也可以拆成多个候选。
- 配体、金属、水、核酸等组分在查看、选取和导出时保留并支持选择。计算是否包含这些组分按工具接口处理，不因蛋白工具的限制而删除其他操作所需数据。
- 多个构象与多个文件是不同范围；上述要求不增加一次选择多个结构文件的能力，也不增加对接等计算。

### 当前输入检查接口

`POST /api/v2/projects/{project_id}/authoring-actions/protein_io.inspect_input` 的 `parameters` 接受 `project_input_ref` 和 `format: "fasta" | "pdb" | "mmcif" | "structure"`；请求可带 `prospective_inputs` 读取未保存的输入。选择 `structure` 时，由模块依据首个非空、非注释记录是否以 `data_` 开头区分 mmCIF 与 PDB；选择明确的 `pdb` 或 `mmcif` 时要求与识别格式一致，不按扩展名或 MIME 选择解析器。它读取已保存或本次请求暂存的输入，返回项目、输入引用、摘要及所选格式，不创建 Draft、Run、Candidate 或 Cache。

FASTA 检查与运行共用 parser，返回记录顺序、序号、header、显示名、起始行号、长度和总长度；非法记录使检查整体失败。结构检查支持 PDB/mmCIF，返回每个构象的源顺序 `model_index`（从 1 开始）、文件内 `model_id` 和各自的链身份，同时保留全文件链列表。链按坐标记录首次出现顺序列出；检查不推断序列、残基对应，也不提前执行蛋白残基轴准入。尚未选择的非蛋白链不应因此阻止蛋白链选择。

不存在项目或输入使用既有 `project_not_found` / `project_input_not_found`；内容解释失败返回 HTTP 422 `project_input_invalid`，保留输入引用与明确格式。内容解释由 `protein_io.inspection` 负责，HTTP 和浏览器不重复实现。

`protein_io.import_structure` 接受 `model_index`，输出选定的单构象结构及单候选集合；省略该参数只适用于单构象文件，多构象文件必须明确选择。`protein_io.import_structures` 接受非空、无重复的 `model_indices`，按所给顺序将每个构象拆为独立 Candidate，不发布含糊的单结构端口。索引越界使整个导入失败，不发布部分集合。两种格式都保留所选原子的链、残基编号、插入码和坐标；候选 metadata 保留文件名、源构象索引及模型编号。原始上传文件不被覆盖，仍可重新选择其他构象，已发布候选及保存参数可重开读取。

“添加来源”的 PDB/mmCIF Candidates 入口允许勾选一个或多个构象，仍只上传一个文件。PDB/mmCIF → Prompt 入口先选一个构象，再选择该构象的有序链；预览和实际运行采用相同的模型选择。后续单模型工具接收已选或已拆分的单构象结构，不传入整个集合文件。候选详情的“结构组分”按模型、author/label 链、残基编号与插入码列出全结构组分，包括配体、金属、水和核酸，不经过蛋白残基轴过滤。原子视口显示全部原子，孤立金属和水也有可见球体；点选原子或勾选列表采用整个对应组分，选中项以金色突出，可聚焦选区。原结构三维视图仍可展开。类别以已知残基类型和单原子金属元素区分；其他组分保留原名称，不推断未知分子的生物学角色。

组分勾选以实际项目、Run 和候选为范围保存在浏览器会话中，切换候选或刷新后恢复；它是结果查看状态，不保存或改写 Workflow。用户明确选择 PDB/mmCIF 后，“导出所选组分”调用模块结果 action，只导出所选组分的原子，保持原坐标系、模型、链、残基身份和适用的连接记录。PDB 不能表示的 mmCIF 身份沿用明确拒绝转换的规则，仍可导出 mmCIF。结构原文和原 Candidate 不变；整个候选的 ZIP 导出与组分导出分开。

## 历史运行与输入采用

用户应能打开项目的运行列表，分别查看历史运行及结果。支持直接将本项目或其他项目的历史结果采用为后续输入，不要求先导出再导入，也不要求重算。后续计算及筛选由用户在画布中组织；这项能力不恢复结果页的“保存为流程”功能。

采用后的输入独立可用，永久删除来源项目也不影响采用方。记录真实来源；内部保存与引用维护由开发者负责。复制项目遵循[项目复制范围](workspace.md#项目生命周期复制与输入)：复制所需输入，副本保持未运行，不整体复制历史输出。

不提供不同次运行的候选并排查看。同次运行内的多候选比较仍可用；历史结果参与结构比较等计算模块，也不等同于跨运行并排查看。评价所用参考对象与真实生成来源分别记录，不能要求修改谱系才能比较或追加评分。

项目的“运行历史”列出已保存 Run 的真实状态、原 Workflow Commit 与保留结果情况，并通过“打开运行”切换唯一的结果读取会话；失败、取消和中断不会隐藏已发布结果。选中 Run 保存在页面 URL 与当前浏览器会话的项目查看状态中，刷新和重新打开项目恢复该选择，不保存或修改流程。当前项目的活动运行锁独立于正在查看的历史 Run；浏览旧结果不解除运行期间的编辑限制。

公共读取入口为 `GET /api/v2/projects/{project_id}/runs`。重启后从持久 Run 记录恢复列表；已知 Run 的必要证据不可用时返回既有 `evidence_unavailable` 错误，不静默遗漏该 Run。实现见 [RunHistoryDialog](../webui/src/RunHistoryDialog.tsx)、[项目运行状态与选择](../webui/src/project-run-history.ts)及[公共 Run 路由](../protein_workbench_public/http/run_routes.py)。

已结束 Run 的统一读取资料保留原状态、成果描述、身份、来源、失败诊断和通用事件；重开时直接读取，不重放旧筛选终态或重新编译流程。原 Ledger、Commit、输入和结果对象保持原样。历史 Commit 快照使用原始保存内容，独立于当前可执行 Workflow 参数解析；导出和采用不会把旧设置重新批准为可执行配置。读取资料的准备入口见 [history_preservation.py](../protein_workbench_public/history_preservation.py)，仅由数据根副本转换调用；该入口不切换正在使用的数据根。

画布的“采用历史结果”从项目、Run 与兼容输出选择模块声明可采用的值。候选、分数、Prompt、序列、结构、轨道、残基轴、评价关系、比对、统计和表征等现有科学结果使用同一个公共 `result_sources` 接口声明来源节点；载体先把所选值及依赖写为目标项目的不可变 Project Input，成功后才将来源节点加入当前编辑，用户手动保存流程。取消选择不改变流程，持久化失败不显示成功。下载附件载荷不作为新的计算输入模式，附件仍可直接导出。

采用保留原始 Candidate ID、数据引用、Score 的 Metric、Method、Context 和值，不生成新谱系。Score 输入保存所需 Candidate、残基轴或比对值，以及已记录的定义和原计算参数；不整体复制来源 Run。已保存的参数导出读取目标本地输入，即使来源项目删除或原模块停用仍保留原参数及 recorded/ambiguous/unavailable 状态。兼容筛选节点可以使用保存的评价定义，不要求重新执行原评分工具。Score 来源节点同时提供可表示为单一 Candidate Collection 的 subjects/references 及唯一明确的 subject-reference relation；pairwise 排名能力指向这些真实输出，可直接接入后续排序。失败 Run 中已发布的值也可明确采用，不改变源 Run 状态或自动启动源下游。相关运行边界见[执行规范](execution.md)。

## 结果入口与展示

结果以实际 Project/Run、节点实例、输出端口及 Typed Output value index 定位。画布节点与分组的输出入口覆盖所有名义类型，显示已发布值数量；点击后定位到对应输出和值索引，内容由用户按需加载。候选数量和科学展示由模块结果面板负责。任意已发布中间输出均可浏览，不依赖最后一个 Selection 或整次运行成功。未发布的临时张量、视图和失败响应不冒充成功结果。

候选分页保持集合顺序，返回总数、原 item index、完整 Candidate Data Reference、全部 parent IDs、metadata、已知序列和结构存在状态。item index 仅定位同一不可变输出中的条目；Score 和跨来源引用使用 `{candidate_id, data_type_id, content_digest}`，不以行号或名字建立关联。浏览沿用首次发布的身份，不重算摘要或产生新候选。

结构候选序列读取以同一完整引用关联的已发布残基轴证据；缺少时显示“尚无已发布序列证据”。浏览器不按 ATOM/CA 猜序列，也不任取一个 parent 继承序列；可继续查看和导出原结构，manifest 单列无序列证据项。

Score 显示保留 subject、Metric、Method、Context、数值、单位、轴及来源，不把不同 Context 合并。多父关系使用全部 parent IDs 查实际完整引用；未解析、多个内容版本分别展示，不任选版本。区域、比较对象和生成来源不能在投影中丢失。

候选列表与详情/比较相邻且分别滚动。点击名称改变查看焦点；复选框管理导出勾选，比较位置和筛选状态独立。现有比较最多四个位置，替换或清空不改变勾选；当前比较来源限定同次运行。

切阶段或筛选保留勾选。“查看已选”显示来源、隐藏和跨页数量，可逐项移除、清空或定位。焦点不在当前列表时解释来源，提供恢复未筛选列表并定位条目的入口。Workflow/Results 往返在浏览器会话中按实际项目/运行保留阶段、页码、焦点、勾选、比较、筛选、滚动，隐藏页面不覆盖滚动位置。

同一类型允许多个模块声明查看器，恰有一个显式默认值，用户可切换；切换仅改变显示，不修改结果。专用值读取按模块声明的 Port Type 分派，查看器与节点编辑器共用 [React 接口](module-ui.md)。`protein.structure` 已声明三维和原文两个查看器；原始值读取保持可用。外部测试包使用相同契约读取和展示独立自定义类型；序列与 Prompt 轨道同样通过模块查看器展示；候选分页通过模块 action 读取，候选关联分数、对齐、筛选和导出通过模块 Run 面板呈现。

### 对齐展示

结构比较模块负责所选对象的对应、对齐及指标计算；结果查看器消费已发布对齐的 subject/reference 和变换，不在浏览动作中暗中计算新对齐。缺少相应结果时，可在同次运行中并排查看。

现有叠加采用行向量 `subject_coordinate × row_vector_rotation + translation`，将 subject 映射到 reference 坐标框架。它只改变显示，原始结构及导出结构不随视图变换改写。展示具体 Method、RMSD、coverage 和来源；镜头旋转不属于结构变换。

## 筛选、排序与手动选择

用户通过画布组合已有指标的筛选和排序；整批前十名与各骨架分别前十名都应可表达，不预先固定唯一规则。模块按完整候选引用匹配评分，不要求当前候选输入与评分时 subject_source 是同一输出端点。

`selection.filter` 将完整 `condition` 保存为节点参数。比较项是 `{kind: "comparison", selection, operator, threshold}`，比较符为 `> >= < <= == !=`，阈值使用 Metric 原单位；分组项是 `{kind: "group", operator: "and" | "or", children: [...]}`，可递归组合。每项 `selection` 使用与原值排序相同的精确评价选择，不引用全局 Selector，也不生成后缀表达式。界面直接编辑这棵条件树，复制后可独立修改。

执行前先为全部输入候选解析每个比较项所需的评价，再计算 AND/OR。必需评价缺失、为 null 或仍有歧义时明确失败；不能用布尔短路隐藏缺分。未选中的 Metric、Method、参考对象或区域不自动造成失败。空分组和未完成评价可保存并重开编辑，但不能 Commit 或运行。输出保留原候选内容、完整身份、metadata、生成来源和相对顺序，可用于下游节点；筛选不补算分数。

整批 Top-k 直接连接完整候选集合；按骨架 Top-k 先用 `collection_ops.select_related_subjects` 根据显式 Candidate Relation 和所选骨架取得候选范围，再连接普通 `selection.top_k`。多个分支可以共享同一 Score Collection；节点本地选择只匹配本范围的完整候选引用及指定评价，未选择的其他观察不影响计算。本范围内缺分或多义仍失败。评价关系通过 `relate_to_single_reference`、`concat_relations` 等普通操作组合，不伪造生成 parents。可运行公共 API 场景与连线说明见[Top-k 范围示例](../examples/v2/top-k-scopes.md)。

`selection.sort` 和 `selection.top_k` 将 `selection` 及 `direction` 直接保存在节点参数。评价包含稳定分数输入槽、Metric、Method、partition 和 Context Profile，可进一步选择精确参考、显式关系或每候选实际 Context/残基轴；不读取全局 Objective 或评分转换。排序直接用指标原值，升降序由用户选择，同分保持输入顺序。Top-k 最多返回 k 个，候选不足取全部、空输入为空，不扩大临界并列。

分数及关系的普通连线用节点本地 `target_slot` 标识，规则只引用该槽。删除或重连来源产生新槽，旧选择保留但不能运行，用户须重新明确评价；未完成节点仍可手动保存。复制节点复制其规则，槽只在该节点内解释。结构比较的实际 Context 可携带已记录主体/参考残基区域；历史未记录区域保持缺席，不从摘要推断。

`selection.pareto` 在节点参数 `objectives` 数组中保存各项 `selection` 和 `direction`，评价选择与原值排序使用相同的精确匹配和稳定输入槽。每项方向单独选择较小值更优（`ascending`）或较大值更优（`descending`）；一候选在所有所选指标上不差且至少一项更好时支配另一候选。只使用原值，不要求权重或评分转换；保留互不支配候选的输入相对顺序，不产生综合排名。相等的指标向量不会互相淘汰；任何必需分数缺失或仍有歧义时停止。输出保留候选的原身份、内容和来源，可连接下游。

`selection.weighted_rank` 当前仍使用全局 Objective 的 Utility 转换，替换由加权任务负责。结果页临时条件草稿与已应用条件分开，条件完整并明确应用才改变列表，可放弃或清除；临时筛选、排序不修改流程。

`selection.manual` 仍可作为普通模块操作存在：在其明确输入集合中匹配完整 `selected_candidates` 引用，保持输入顺序，空选择得到空集合。缺失或内容改变时报错，不自动换成同名或同序列候选。它不自行搜旧 Run 替换输入；历史结果应先通过明确采用能力成为输入。

当前 `workflow:observation-options` 读取编译器的可用观察投影，只提交 `workflow.nodes`、`workflow.edges` 与 `ranking`。未完成 Selector/Objective 配置不能阻止来源枚举；完整配置在 Commit 边界处理。手动选择的 `candidate_selection_consumption` 及有序完整引用终局记录由现有编译和运行边界负责，空引用数组与没有该分支分别表达。

现有结果页已移除“勾选保存为流程”、条件和 Top-N 转流程入口；不得以改名恢复。此要求不取消普通筛选节点、查看、导出、历史采用或局部 Prompt 采用，也不新增对外部插件的同类功能禁令。

## 当前结果读取边界

### 结果与当前流程的一致性

结果页的 `current` 表示结果与当前流程中影响结果的输入、参数及定义一致，`stale` 表示这些内容已改变，`unknown` 表示当前无法确认一致性，例如流程无法编译或所需输入不可用。`stale` 不表示历史结果本身无效，历史结果仍按产生它的原 Commit 解释。

仅改变布局不会使结果过期；恢复原输入、参数及定义后，可恢复一致状态。一致性检查不保存 Draft、不触发重算，也不改写历史结果。现有状态展示见 [ResultsWorkbench](../webui/src/ResultsWorkbench.tsx)。

### 阅读会话

`PublishedResults` 是当前前端一个 Run 状态与通用值阅读会话的 owner，协调 REST projection、事件 cursor、活动、诊断和不可变值缓存。Protein I/O 的 `CandidateResults` 订阅该会话并维护候选分页、分数/轴/对齐关联索引；候选面板和编辑辅助共享同一索引，视图持有焦点等交互状态。结果归属取实际 `(project_id, run_id)`，不把示例结果假记为个人项目的新运行。

节点完成及 Run 终态来自 REST。WebSocket 提供执行活动、诊断与连接状态并触发刷新；回放结束统一刷新。事件 cursor 只表示已消费事件，不能由 REST cursor 代推进。启动回执至首次 REST 之间保留会话，不重复启动。

切换 Run 替换读取 session，迟到响应不能改变新会话，包括 A→B→A。同 Run 刷新保留已加载页，只读新增或先前未成功读取的不可变输出；原 Commit 定义在会话内复用，不重新验证响应或候选身份。

每集合共享一个进行中的分页请求，offset 来自已加载数量，成功页即时保留；失败明确报告，下次明确操作从未完成位置继续，不自动重试。结构、已知阅读值及原值的请求与成功内容由该 session 共享。后到的序列/残基轴证据更新既有候选投影。

当前每集合首取 100 条，显示页为 50 条。搜索、完整筛选和排序先由用户明确加载该集合全部候选；导出补齐候选及父引用索引，不能把尚未加载当成未发布。`prepareExport` 固定点击时的勾选，在同一返回 snapshot 中取候选、观察、序列和结构，不能混入其他会话事实。局部恢复只指恢复请求范围内的 Candidate 对象，当前仍读取完整 JSON，不宣称磁盘局部读取。

## 导出

无需先保存筛选或重新计算即可导出所选现有结果。用户结果下载统一为 ZIP，包含所选格式的数据和已经记录的计算参数说明；结果页组分导出与导出节点的附件下载遵守同样约定。模块提供实际数据与选择含义，载体提供公共打包入口，已发布 Artifact 的原始媒体和计算数据不变。

候选 ZIP 支持纯序列和混合候选，包含现有序列、结构、分数、完整 parent refs、观察定义、真实 Run/Commit/输出来源，并列出无结构、无序列证据项。原始观察不混入仅供 UI 分组的 Context Profile。以下候选文件格式不要求组分包或普通附件包也包含候选 manifest、FASTA 或评分 CSV。

应附带已经记录的原计算参数，保证离开软件后可读；只写 Commit ID 或 Method 定义不足以替代实际节点/Binding 参数。不补造未记录数据，不新增日志或证据体系。结构须提供 PDB/mmCIF 选择，并保留所选非蛋白组分。

当前候选 ZIP 的文件格式化与打包由[结果导出](../modules/protein_io/ui/result-explorer.ts)维护；它写 FASTA、分数 CSV、manifest，并按用户选择写 PDB 或 mmCIF。导出节点的 `format` 参数与结果页“结构导出格式”均默认 PDB；不同格式由 protein_io 的 Gemmi 转换处理，同格式保持原文，保留的输入及发布结果不会改写。PDB 无法表示的链、残基身份或坐标明确拒绝转换，用户仍可选择 mmCIF。跨格式保留所支持的结构内容，不保证任意源格式专用元数据的无损往返。候选 ZIP 中的 `computation-parameters.json` 保存来源 Run/Commit 的节点与 Binding 参数，以及 Commit 中实际保存的 admitted 参数；后者缺失时写 `null`，不根据当前定义补默认值。`manifest.json` 指向该文件；候选、序列、观察和对齐的 `source` 对应参数文件的 `outputs`，其 `parameter_record_ids` 指向计算记录。混合勾选保留各自来源。缓存重放按发布记录的 producer Run 读取原 Commit，以结果身份、输出端口、内容摘要和 value manifest 摘要定位原执行节点，排除重放节点，不把当前工作区或重放 Run 的配置冒充原计算参数。当前 Run 中实际执行的输出按原节点 ID 精确定位；缓存结果若仍对应多个内容完全相同的执行节点，则标记 `ambiguous` 并列出候选参数记录，不断言唯一来源。

参数文件中的 `workflows` 是来源 Commit 已保存的流程、连线、Selector 与 Objective，不表示其中每个节点都执行过。不存在原 Run/Commit 或节点记录时，对应输出明确记为 `unavailable`；其他读取失败停止本次导出，用户可明确重试。只导出计算记录与结果，不读取 Environment Configuration 或凭据，不新增持久日志。参数读取由[结果参数读取](../webui/src/result-parameters.ts)负责。

组分与附件通过公共 `PublishedResults.exportBundle` / `exportArtifact` 下载 ZIP，附带 `export-details.json` 记录模块提供的具体选择或附件来源。组分说明包含实际模型、链、残基和组分名称。附件的参数关联使用已有生产 Run、节点结果身份和附件内容身份，按实际执行节点读取原参数及已记录的准入参数；同 Run 和跨 Run 的缓存重放都不冒充原生产者。`publishing_workflow` 仅说明本次发布流程，不替代原计算参数。附件读取到打包保持同一会话，切换运行后迟到的响应不触发下载。

## 当前差距与核对

| 范围 | 当前状态 |
|---|---|
| 单条 FASTA | 单条入口拒绝多条记录并提示批量入口 |
| 历史 Run 查看 | 项目运行列表与单 Run 选择；按原 Run/Commit 读取状态与保留结果，选择可刷新恢复 |
| 历史/跨项目采用及来源删除独立 | 统一 Project Input 采用 API 与画布入口，类型由模块显式声明；Candidate/Score 保存原值、依赖、定义及参数；来源删除后可重开运行；项目副本保留独立输入，不复制 Run |
| 结构格式、多构象、非蛋白组分 | 已支持 PDB/mmCIF 导入、构象选择/拆分及格式转换；候选详情支持全原子组分查看、选择与两种格式导出 |
| 模块查看器 | 已注册结构、序列与 Prompt 查看器并支持切换；候选分页及关联分数、对齐面板通过同一模块公共读取和 Run 查看器接口接入 |
| 结果页转流程 | 已删除入口及节点生成路径 |
| ESMC 输出 | 可选 embedding、实际逐位置 logits，模块数值查看器及原值读取；见[模块能力](module-capabilities.md) |
| 批次成功结果与续算 | ESMFold2、ESM3、SimpleFold 和 ProteinMPNN 设计在各自已定义失败时保留完成结果，提供固定原输入和参数、跳过成功请求的主动续算，见[执行规范](execution.md) |
| 导出参数与 mmCIF | 已提供节点及结果页格式选择与转换，以及来源 Run/Commit 参数文件 |

