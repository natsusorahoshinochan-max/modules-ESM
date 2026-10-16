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

`POST /api/v2/projects/{project_id}/inputs/{project_input_ref}:inspect` 接受 `format: "fasta" | "pdb" | "mmcif" | "structure"`。选择 `structure` 时，由模块依据首个非空、非注释记录是否以 `data_` 开头区分 mmCIF 与 PDB；选择明确的 `pdb` 或 `mmcif` 时要求与识别格式一致，不按扩展名或 MIME 选择解析器。它读取已上传的不可变输入，返回项目、输入引用、摘要及所选格式，不创建 Draft、Run、Candidate 或 Cache。

FASTA 检查与运行共用 parser，返回记录顺序、序号、header、显示名、起始行号、长度和总长度；非法记录使检查整体失败。结构检查支持 PDB/mmCIF，按坐标记录首次出现顺序返回链身份，不推断序列、残基对应，也不提前执行蛋白残基轴准入。尚未选择的非蛋白链不应因此阻止蛋白链选择。

不存在项目或输入使用既有 `project_not_found` / `project_input_not_found`；内容解释失败返回 HTTP 422 `project_input_invalid`，保留输入引用与明确格式。内容解释由 `protein_io.inspection` 负责，HTTP 和浏览器不重复实现。

这段描述的是现有接口边界，不能作为排除 mmCIF 或多构象的产品规定。现有结构导入把整份文件作为一个候选，检查只列链；残基轴处理要求单 MODEL。结构值本身可保留多 MODEL 文本，不能把“保存了文件”写成“已经支持构象选择及拆分”。通用查看、选取及导出全部非蛋白组分的覆盖仍须对齐，专用蛋白残基轴排除水或配体不代表原始文件已被删除。

## 历史运行与输入采用

用户应能打开项目的运行列表，分别查看历史运行及结果。支持直接将本项目或其他项目的历史结果采用为后续输入，不要求先导出再导入，也不要求重算。后续计算及筛选由用户在画布中组织；这项能力不恢复结果页的“保存为流程”功能。

采用后的输入独立可用，永久删除来源项目也不影响采用方。记录真实来源；内部保存与引用维护由开发者负责。复制项目遵循[项目复制范围](workspace.md#项目生命周期复制与输入)：复制所需输入，副本保持未运行，不整体复制历史输出。

不提供不同次运行的候选并排查看。同次运行内的多候选比较仍可用；历史结果参与结构比较等计算模块，也不等同于跨运行并排查看。评价所用参考对象与真实生成来源分别记录，不能要求修改谱系才能比较或追加评分。

项目的“运行历史”列出已保存 Run 的真实状态、原 Workflow Commit 与保留结果情况，并通过“打开运行”切换唯一的结果读取会话；失败、取消和中断不会隐藏已发布结果。选中 Run 保存在页面 URL 与当前浏览器会话的项目查看状态中，刷新和重新打开项目恢复该选择，不保存或修改流程。当前项目的活动运行锁独立于正在查看的历史 Run；浏览旧结果不解除运行期间的编辑限制。

公共读取入口为 `GET /api/v2/projects/{project_id}/runs`。重启后从持久 Run 记录恢复列表；已知 Run 的必要证据不可用时返回既有 `evidence_unavailable` 错误，不静默遗漏该 Run。实现见 [RunHistoryDialog](../webui/src/RunHistoryDialog.tsx)、[项目运行状态与选择](../webui/src/project-run-history.ts)及[公共 Run 路由](../protein_workbench_public/http/run_routes.py)。

历史/跨项目结果采用及来源永久删除后的独立可用性仍需沿实际采用与持久化路径核对；运行列表、节点级重跑和既有输入复制不代表完整采用能力。相关运行边界见[执行规范](execution.md)。

## 结果入口与展示

结果以实际 Project/Run、节点实例、输出端口及 Typed Output value index 定位。任意已发布中间输出均可浏览，不依赖最后一个 Selection 或整次运行成功。未发布的临时张量、视图和失败响应不冒充成功结果。

候选分页保持集合顺序，返回总数、原 item index、完整 Candidate Data Reference、全部 parent IDs、metadata、已知序列和结构存在状态。item index 仅定位同一不可变输出中的条目；Score 和跨来源引用使用 `{candidate_id, data_type_id, content_digest}`，不以行号或名字建立关联。浏览沿用首次发布的身份，不重算摘要或产生新候选。

结构候选序列读取以同一完整引用关联的已发布残基轴证据；缺少时显示“尚无已发布序列证据”。浏览器不按 ATOM/CA 猜序列，也不任取一个 parent 继承序列；可继续查看和导出原结构，manifest 单列无序列证据项。

Score 显示保留 subject、Metric、Method、Context、数值、单位、轴及来源，不把不同 Context 合并。多父关系使用全部 parent IDs 查实际完整引用；未解析、多个内容版本分别展示，不任选版本。区域、比较对象和生成来源不能在投影中丢失。

候选列表与详情/比较相邻且分别滚动。点击名称改变查看焦点；复选框管理导出勾选，比较位置和筛选状态独立。现有比较最多四个位置，替换或清空不改变勾选；当前比较来源限定同次运行。

切阶段或筛选保留勾选。“查看已选”显示来源、隐藏和跨页数量，可逐项移除、清空或定位。焦点不在当前列表时解释来源，提供恢复未筛选列表并定位条目的入口。Workflow/Results 往返在浏览器会话中按实际项目/运行保留阶段、页码、焦点、勾选、比较、筛选、滚动，隐藏页面不覆盖滚动位置。

同一类型允许多个模块声明查看器，恰有一个显式默认值，用户可切换；切换仅改变显示，不修改结果。专用值读取按模块声明的 Port Type 分派，查看器与节点编辑器共用 [React 接口](module-ui.md)。`protein.structure` 已声明三维和原文两个查看器；原始值读取保持可用。外部测试包使用相同契约读取和展示独立自定义类型；其余内置展示迁移仍待完成。

### 对齐展示

结构比较模块负责所选对象的对应、对齐及指标计算；结果查看器消费已发布对齐的 subject/reference 和变换，不在浏览动作中暗中计算新对齐。缺少相应结果时，可在同次运行中并排查看。

现有叠加采用行向量 `subject_coordinate × row_vector_rotation + translation`，将 subject 映射到 reference 坐标框架。它只改变显示，原始结构及导出结构不随视图变换改写。展示具体 Method、RMSD、coverage 和来源；镜头旋转不属于结构变换。

## 筛选、排序与手动选择

用户通过画布组合已有指标的筛选和排序；整批前十名与各骨架分别前十名都应可表达，不预先固定唯一规则。模块按完整候选引用匹配评分，不要求当前候选输入与评分时 subject_source 是同一输出端点。

当前 `selection.filter` 用有序不重复 `selector_ids` 指向同一候选输入的观察，`scores` 为多值输入。匹配保留 Metric、Method、Context、partition、成对引用及 `exactly_one` 含义。缺少必需评分默认停止对应筛选；多义或内容版本不符明确报错，AND/OR 短路不能隐藏这些问题。尚未确认“排除缺分候选后继续”的额外功能。

`expression` 为后序表达式：比较项含从 0 开始的 `selector_index`、`operator`、`threshold`，比较符为 `> >= < <= == !=`，阈值采用 Metric 单位；分组项 `{operator: "and" | "or", operand_count: N}`，N 至少 2。最终栈只保留一个结果并使用全部声明的 Selector。UI 用嵌套 AND/OR 分组无损表示，由筛选 owner 核对一次，不在 TypeScript 复制推导。

`out_of_scope_policy` 只处理该 Score 来源上所声明 Selector 并集之外的观察：`error` 拒绝，`ignore` 明确忽略；范围内缺失和多义规则不变。输出保留原候选对象、metadata、谱系及相对顺序。

现有排序、Top-N、加权排名分别由 `selection.sort`、`selection.top_k`、`selection.weighted_rank` 提供，使用 Selection Objective 声明的 Utility Transform；原值显示排序不能悄悄变成效用排序。平局沿用 Candidate ID 升序。结果页临时条件草稿与已应用条件分开，条件完整并明确应用才改变列表，可放弃或清除；临时筛选、排序不修改流程。

`selection.manual` 仍可作为普通模块操作存在：在其明确输入集合中匹配完整 `selected_candidates` 引用，保持输入顺序，空选择得到空集合。缺失或内容改变时报错，不自动换成同名或同序列候选。它不自行搜旧 Run 替换输入；历史结果应先通过明确采用能力成为输入。

当前 `workflow:observation-options` 读取编译器的可用观察投影，只提交 `workflow.nodes`、`workflow.edges` 与 `ranking`。未完成 Selector/Objective 配置不能阻止来源枚举；完整配置在 Commit 边界处理。手动选择的 `candidate_selection_consumption` 及有序完整引用终局记录由现有编译和运行边界负责，空引用数组与没有该分支分别表达。

现有结果页已移除“勾选保存为流程”、条件和 Top-N 转流程入口；不得以改名恢复。此要求不取消普通筛选节点、查看、导出、历史采用或局部 Prompt 采用，也不新增对外部插件的同类功能禁令。

## 当前结果读取边界

### 结果与当前流程的一致性

结果页的 `current` 表示结果与当前流程中影响结果的输入、参数及定义一致，`stale` 表示这些内容已改变，`unknown` 表示当前无法确认一致性，例如流程无法编译或所需输入不可用。`stale` 不表示历史结果本身无效，历史结果仍按产生它的原 Commit 解释。

仅改变布局不会使结果过期；恢复原输入、参数及定义后，可恢复一致状态。一致性检查不保存 Draft、不触发重算，也不改写历史结果。现有状态展示见 [ResultsWorkbench](../webui/src/ResultsWorkbench.tsx)。

### 阅读会话

`PublishedResults` 是当前前端一个 Run 阅读会话的统一 owner，协调 REST projection、事件 cursor、活动、诊断、分页和不可变值缓存；视图只持有焦点等交互状态。结果归属取实际 `(project_id, run_id)`，不把示例结果假记为个人项目的新运行。

节点完成及 Run 终态来自 REST。WebSocket 提供执行活动、诊断与连接状态并触发刷新；回放结束统一刷新。事件 cursor 只表示已消费事件，不能由 REST cursor 代推进。启动回执至首次 REST 之间保留会话，不重复启动。

切换 Run 替换读取 session，迟到响应不能改变新会话，包括 A→B→A。同 Run 刷新保留已加载页，只读新增或先前未成功读取的不可变输出；原 Commit 定义在会话内复用，不重新验证响应或候选身份。

每集合共享一个进行中的分页请求，offset 来自已加载数量，成功页即时保留；失败明确报告，下次明确操作从未完成位置继续，不自动重试。结构、已知阅读值及原值的请求与成功内容由该 session 共享。后到的序列/残基轴证据更新既有候选投影。

当前每集合首取 100 条，显示页为 50 条。搜索、完整筛选和排序先由用户明确加载该集合全部候选；导出补齐候选及父引用索引，不能把尚未加载当成未发布。`prepareExport` 固定点击时的勾选，在同一返回 snapshot 中取候选、观察、序列和结构，不能混入其他会话事实。局部恢复只指恢复请求范围内的 Candidate 对象，当前仍读取完整 JSON，不宣称磁盘局部读取。

## 导出

无需先保存筛选或重新计算即可导出所选现有结果。支持纯序列和混合候选；内容包含现有序列、结构、分数、完整 parent refs、观察定义、真实 Run/Commit/输出来源，并列出无结构、无序列证据项。原始观察不混入仅供 UI 分组的 Context Profile。

应附带已经记录的原计算参数，保证离开软件后可读；只写 Commit ID 或 Method 定义不足以替代实际节点/Binding 参数。不补造未记录数据，不新增日志或证据体系。结构须提供 PDB/mmCIF 选择，并保留所选非蛋白组分。

当前 ZIP 格式化由[结果导出](../webui/src/result-explorer.ts)维护；它写 FASTA、分数 CSV、manifest，并按用户选择写 PDB 或 mmCIF。导出节点的 `format` 参数与结果页“结构导出格式”均默认 PDB；不同格式由 protein_io 的 Gemmi 转换处理，同格式保持原文，保留的输入及发布结果不会改写。PDB 无法表示的链、残基身份或坐标明确拒绝转换，用户仍可选择 mmCIF。跨格式保留所支持的结构内容，不保证任意源格式专用元数据的无损往返。ZIP 中的 `computation-parameters.json` 保存来源 Run/Commit 的节点与 Binding 参数，以及 Commit 中实际保存的 admitted 参数；后者缺失时写 `null`，不根据当前定义补默认值。`manifest.json` 指向该文件；候选、序列、观察和对齐的 `source` 对应参数文件的 `outputs`，其 `parameter_record_ids` 指向计算记录。混合勾选保留各自来源。缓存重放按发布记录的 producer Run 读取原 Commit，以结果身份、输出端口、内容摘要和 value manifest 摘要定位原执行节点，排除重放节点，不把当前工作区或重放 Run 的配置冒充原计算参数。当前 Run 中实际执行的输出按原节点 ID 精确定位；缓存结果若仍对应多个内容完全相同的执行节点，则标记 `ambiguous` 并列出候选参数记录，不断言唯一来源。

参数文件中的 `workflows` 是来源 Commit 已保存的流程、连线、Selector 与 Objective，不表示其中每个节点都执行过。不存在原 Run/Commit 或节点记录时，对应输出明确记为 `unavailable`；其他读取失败停止本次导出，用户可明确重试。只导出计算记录与结果，不读取 Environment Configuration 或凭据，不新增持久日志。参数读取由[结果参数读取](../webui/src/result-parameters.ts)负责。

## 当前差距与核对

| 范围 | 当前状态 |
|---|---|
| 单条 FASTA | 单条入口拒绝多条记录并提示批量入口 |
| 历史 Run 查看 | 项目运行列表与单 Run 选择；按原 Run/Commit 读取状态与保留结果，选择可刷新恢复 |
| 历史/跨项目采用及来源删除独立 | 节点级复用和输入复制不代表完整采用；采用及来源删除后的可用性尚未证实 |
| 结构格式、多构象、非蛋白组分 | 已支持 PDB/mmCIF 导入与格式转换；构象选择/拆分及完整组分操作仍待完成 |
| 模块查看器 | 内置读取和固定分派须按模块契约开放；多个查看器切换尚待实现 |
| 结果页转流程 | 已删除入口及节点生成路径 |
| ESMC 输出 | 可选 embedding、实际逐位置 logits，模块数值查看器及原值读取；见[模块能力](module-capabilities.md) |
| 批次成功结果与续算 | 失败时保留已完成结果；跳过成功请求的主动续算仍缺，见[执行规范](execution.md) |
| 导出参数与 mmCIF | 已提供节点及结果页格式选择与转换，以及来源 Run/Commit 参数文件 |

