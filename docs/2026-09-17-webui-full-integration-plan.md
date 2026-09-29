# WebUI 集成交付范围与验收要求

- 最后更新：2026-09-29。
- 状态：P0–P7 的完整验收记录对应 [09-24 固定快照](2026-09-24-port-connections-acceptance.md)，[09-19 记录](2026-09-19-webui-integration-progress.md)对应此前集成快照。2026-09-29 前端交互改进已获阶段性通过；结构变换实时预览仍待优化，不能据此声称全部交互问题已解决。
- 本文维护已确认的产品范围和验收要求；科学与持久化细节由下列现行规格拥有。
- Selector/Objective 来源字段的进一步减法仍未完成，单独记录在验收文档中。

## 1. 范围和依据

交付范围包含来源输入、画布、运行、结果、Prompt 编辑和项目版本管理。

依据按职责区分：

1. [CONTEXT.md](../CONTEXT.md) 与当前科学规格拥有领域含义及科学合同。
2. [2026-09-02 数据流规格](2026-09-02-clean-scientific-data-flow-refactor-spec.md)及后续 Commit、残基和 ESM3 规格优先于旧原型中的科学实现假设。
3. [已确认功能基线](legacy/2026-08-29-webui-functional-spec.md)和[八个原型](../.scratch/webui-product-definition/)提供用户功能及交互方向。

继续遵守当前科学语义：Prompt Studio 编辑普通 `prompt_authoring.author` Node 的 `document`；FASTA/PDB 通过可见的 I/O Nodes 提供；不恢复 managed composition、平行 layout Ports 或旧前端。SS8、Function annotations 重复规则、absent 与 present all-null 按当前规格，不照抄旧原型。Availability 是启动诊断，不等于 Run-scoped Readiness，也不能单独阻止缓存复用或执行。

不新增此前明确排除的功能：账号/多人协作、项目文件夹/标签/收藏、单节点取消、原子级坐标编辑、结构几何缩放、隐式结构优化、自然语言生成 Prompt、独立 ProteinMPNN 约束编辑器。按本轮用户决定，不提供自动残基对应或自动对齐草稿，只提供手动对应。仍只提供最近一次 Run 的常规入口；命名版本不等于 Run 历史列表。

## 2. 当前规格

- [运行范围与复用](2026-09-17-run-scope-spec.md)
- [Selection 与输入](2026-09-17-selection-input-integration-spec.md)
- [结果浏览](2026-09-17-result-explorer-spec.md)
- [Prompt 编辑](2026-09-17-prompt-editing-spec.md)
- [项目工作区与版本](2026-09-17-project-workspace-spec.md)
- [离线预置结果](2026-09-19-webui-example-results-spec.md)
- [真实 FASTA 旅程](2026-09-19-webui-fasta-journey-spec.md)

## 3. 每项交付都必须贯通的路径

每项功能以“用户动作 → 当前 public Interface → 现有科学/持久化 owner → 返回 projection/evidence → UI 展示 → 重开后行为”验收。纯视图动作不制造科学事实；有后台实现、类型声明或按钮，不代表完成集成。

前端按实际职责划分以下 Modules：

| Module | 小型 Interface 承担的完整行为 | 主要代码归属 |
|---|---|---|
| Project workspace | 打开/保存当前工作、输入、命名版本、复制和恢复；协调 Draft 与 UI state | `webui/src/` 项目相关代码；`core/project/`、`core/workflow/authoring.py` |
| Workflow authoring | graph 编辑、参数/模型/选择目标、undo 和复制；保持对象引用一致 | `webui/src/workflow-authoring.ts` 及画布相关代码 |
| Prompt session | 一个编辑 document；矩阵提交依次预览，复杂操作显式预览／应用；整份保存、取消、undo/redo | `webui/src/PromptStudio.tsx`，`modules/prompt_authoring/` |
| Run authoring | 范围提案、确认启动与取消 | App 与 WebUI Run 控件，`core/execution/`、public Run routes |
| Run reading | 同一 Session 的 REST 状态、事件订阅、cursor、活动、诊断与结果分页；REST 唯一决定完成状态 | `webui/src/published-results.ts` |
| Result explorer | 集合/候选焦点、精确关联、比较、筛选、导出及来源 | WebUI Results 代码；published values 的只读 public projection |

public transport 集中在 `webui/src/protocol/`。类型和请求形状以当前 bundle 为准；新增合同同时更新 Python owner、bundle、TypeScript consumer、fixtures 和测试。合同 owner 验证后下游信任，不在每层复制校验。沿用当前 React/Vite/React Flow/3Dmol，矩阵使用 AG Grid Community，模态与菜单使用 Radix；不为本轮另建框架、BFF、通用插件层或双轨协议。

## 4. 功能与验收要求

### P0：产品与科学合同

第 2 节现行规格定义运行范围、Selection、结果关联、Prompt 编辑和项目持久化。
每项能力通过 public Interface 交给对应 owner，前端展示其 projection/evidence。
科学内容与 Run Commit 的比较由后端负责；布局变化不影响结果，改回科学内容可解除过期提示。
范围预览不保证 Provider 已就绪；Availability 与 Run-scoped Readiness 保持各自语义。

### P1：来源输入、可编辑画布与选择目标

**依赖：** P0 的相关合同。先使用户能建立自己的完整 Workflow。

交付：

- 接入文件上传、FASTA 粘贴、Project Input 列表/选择、PDB 链选择和现有 Prompt 来源连接。科学读取和链选择显示为普通 Nodes，UI 不私自解析并改写科学值。
- 打通空白、FASTA、PDB、已有 ProteinPrompt 四种入口；保留 multi-chain declarations。区分“多链 Prompt 的序列来源”和“每条 FASTA record 是独立 Candidate”的批量输入。
- 新增或扩展明确的批量 FASTA import 科学合同：输出 ordered Candidate Collection，保留每条 record 的来源/header/身份。不按名称或序列自动去重；非法记录明确定位并默认阻止本次导入，不静默跳过。缺失名称的展示及精确记录寻址写入规格；不得以显示名称建立 Candidate identity。
- 画布空白处搜索添加、兼容 Port 高亮、单输入替换和断开；接好搜索/fit-view 等可见控件。
- 节点卡片按公开合同分组，提供枚举、布尔、数值边界/步长、单位及结构化值编辑。对现有 Catalog 的真实复杂参数提供领域控件，不把研究人员逼到 JSON 或内部 ID 输入框。
- 保留已选 Binding、展示 Availability 原因；跨模型共有参数和各 Binding 专属值的恢复按已声明参数作用域处理，不按同名字段猜语义。
- 多选复制粘贴：新 Node IDs，保留内部边、参数和 author document；仅复制完整内部引用，正确重建 Selector/Objective 的引用，外部连接留待明确接入；不产生悬空科学引用。普通 undo 覆盖参数、模型、移动、连线和片段编辑。
- Selection 编辑：选择精确 Metric/Method/Observation Context、Utility Transform、权重、missing policy、阈值与 Top-N；显示声明权重及有效百分比。50/50 可以改为其他比例并重新运行。
- 保存为流程操作必须覆盖三类：条件筛选、排序并取前 N 个、手动勾选候选。条件筛选支持 AND/OR 和明确分组，界面展示完整表达，保存后保持相同语义。
- 手动选择保存精确候选引用及来源，不能保存当前表格行号。执行时在当前输入集合中匹配；找不到所选精确引用时明确报错，不自动替换、不跳过、不改为读取旧 Run 结果。用户可以重新勾选。精确引用包含 Candidate Data Reference 的身份、数据类型和内容身份，不以同名或同序列替代。

**验收：** 从空白项目上传用户输入，建立 Prompt→生成/折叠→评分→Selection；不手填 Project Input、Selector 或 Objective 身份。重开后保留配置；复制片段、撤销和模型切换不改变未授权科学内容；AND/OR 分组的预览、保存、重开和执行含义一致；手动选择的精确引用缺失时明确失败。

### P2：运行范围、取消、恢复和部分结果

**依赖：** P0 运行合同、P1 可保存的 Workflow。

交付：

- 三种运行范围：完整流程、到所选节点、从所选节点继续。后端给出范围、依赖、可能复用部分、强制重算部分和明确 blockers；画布高亮与确认摘要一致。
- “到节点”覆盖该节点及所需祖先，其他节点不进入本次执行；“从节点继续”仅执行选中节点及其后代，不包含其他独立分支，不补跑范围外上游。继续所需的任一上游结果不存在或不满足复用合同，拒绝继续并定位缺失依赖；不提供在该动作内扩大范围的选项。
- “继续”区分当前 Commit 和源 Run，科学身份改变时不得复用不相符的结果。不通过前端删除节点来伪装运行范围。“从节点继续”强制重算选中节点及其后代，即使已有完全匹配的缓存，也不得以缓存重放满足这些节点；范围外所需上游只复用，不执行。界面提前说明强制重算范围。该政策只定义继续运行的行为，不改变完整运行的既有缓存政策，也不隐式更换 effective seed。
- 运行前展示实际 Bindings/Methods、参数、数量和 effective randomness；删除固定 `Ready` 和固定漏斗。若确认期间 Draft 改变，确认目标必须重新核对或保持明确固定的 Commit。
- 界面明确标记范围外节点和 Selection，不混同失败、阻塞或取消；具体 evidence/closure 语义由 P0 规格决定，不能用 fabricated succeeded/failed 表示未执行。
- 接入整次取消；失败节点、依赖阻塞、无关分支继续和节点运行详情；可以从错误定位到参数、来源或 Prompt 位置。
- 状态订阅保存最后已消费 cursor；采用明确的连接恢复政策，显示断连，不盲目重提 Run。重开页面恢复最近 Run。支持后端重启后依据保留的旧结果发起新 Run：先重新验证 Commit，旧的中断 Run 保持 interrupted，不伪装为原 Run 从断点恢复；仍须满足“不补跑上游”的继续前提。
- 不再要求整个 Run succeeded 才能检查输出：运行中、失败、取消、中断时，已原子发布的 Typed Outputs/Artifacts 均可进入基础结果浏览。此处交付基础列表与值查看，完整比较在 P3。

**验收：** 完整流程或选定范围内一条分支失败，范围内独立分支完成；取消后已发布值可查看；局部运行不会调用范围外 Provider；继续仅覆盖选中节点及后代，即使预置完全匹配的缓存仍进入正常实际执行路径，发生失败时保留真实失败而不回退到缓存；范围外上游不执行，缺少任一必要可复用上游时拒绝且不补跑；改参数后继续使用新 Commit，结果复用遵守 Result Identity；断线/重开不重复启动或伪造节点结论；后端重启后可以在上述前提下发起新 Run，旧 interrupted 记录不改写。

### P3：通用结果、谱系、比较、筛选和导出

**依赖：** P1 的 Selection authoring、P2 的 Run/部分输出浏览。

交付：

- 以明确 Node/Port/Typed Output 定位可浏览集合，支持中间阶段、无 Selection 的流程、纯序列和结构候选，移除 last-selection/last-output 假设。
- 候选、Score、结构对齐和其他派生值按 Candidate Data Reference 及精确 Context 关联，不能按数组顺序或仅 Candidate ID 连接。
- 谱系展示父结构→ProteinMPNN 子代序列→再次折叠结构；支持多个 parents，点击各角色同步内容与来源，不只展示第一个 parent 的字符串。
- 展示全部适用 Score Observations，包含 Metric Definition、Method、单位、范围、方向、aggregation 和实际参考 Candidate；不只硬编码 pLDDT/TM-score。
- 多候选并排结构/序列/分数。叠加消费已有 Structure Alignment Evidence 的明确 subject/reference 与 transform；不能假设多个候选天然共用同一坐标框架，证据不足时解释原因。
- 候选列表与详情／比较相邻显示；候选焦点、勾选、最多四个比较位置及临时排序／筛选分别维护。未完成的筛选草稿不改变列表，完整后显式应用；隐藏勾选可在“查看已选”中集中管理。Workflow 往返按工作区与结果 Run 恢复视图及滚动位置，对话框关闭恢复工作焦点。保存为流程操作覆盖条件筛选、排序取前 N、手动勾选候选三类，先显示将新增的可编辑 Node 及所需 Selector/Objective 或候选引用，再写入 Draft，不重算旧结果。筛选完整保留 AND/OR 及分组；手动勾选按精确引用在当前输入集合中匹配，缺失报错并允许用户重新选择。不得把手动勾选仅保留为一次性导出状态。
- 固定 ZIP 直接导出，不要求先保存筛选或重新运行。使用真实 sequence/structure values，携带精确身份、完整 parent refs、Metric/Method/Context、单位、Run/Commit 和输出来源。允许纯序列及混合选择导出：包含 FASTA、分数 CSV 和 manifest，仅为实际有结构的 Candidate 写 PDB，明确列出没有结构的项。
- 画布、Results、比较和导出持续展示实际 Run/Commit 来源及过期状态，不能因 copied-from 一直标旧或因非复制项目漏标。
- 删除缺少数据时静默显示 `/3GB1.pdb` 的 fallback。无结果、无结构和加载错误分别展示真实状态。
- 集合分页、按需结构加载、视图渲染容量随批量场景一起验收；不会一次创建所有候选的 3D viewers。

**验收：** 同一 UI 浏览自定义 Workflow 的各阶段及部分输出；父子关系与精确 Score 关联可核对；改变显示筛选不改科学 Workflow；三类保存为流程操作均可编辑、重开并执行，使用能区分不同括号分组的条件验证 AND/OR 语义；手动勾选不依赖表格顺序，候选缺失或相同 Candidate ID 对应不同内容时不得错误匹配；纯序列/混合导出与勾选一致，ZIP 中每个值可追溯；旧结果提示跟随科学变化而非画布变化。

### P4：完整 Prompt 编辑与随机条件

**依赖：** P1 的来源及当前 Prompt session；P0 的科学语义说明。

交付：

- 布局/条件/结构模式改变可用操作和快捷键；blank 默认布局、其他来源默认条件，矩阵保持统一。
- 桌面采用结构视图与 AG Grid Community 残基矩阵两栏，分隔条可调整宽度；窄屏切换结构／矩阵。常用动作在矩阵工具栏，复杂动作按需打开对话框。单格确认逐次预览并分别进入撤销历史；显式多轨批量操作预览后整组应用。
- 矩阵单击选中、键入替换、F2／双击编辑；Enter 下一轨道、Tab 下一残基、Shift 反向、Esc 取消输入。支持 Shift 锚点连选、Ctrl／⌘ 追加选择和 TSV 复制粘贴；无效粘贴整次拒绝，非法单格输入保留，输入法组合确认不提前提交。Coordinates／Function 使用专用编辑入口；诊断可点击定位。
- Function annotations 提供明确端点编辑和拆分，完整 tuple 的变更经过后端 preview；遵守可重叠、完全相同 tuple 不重复的现行合同，不自动裁剪或合并。
- 增加随机 Mask/插入控件：count、eligible scope、seed、换 seed 重抽、实际位置显示和最终确认；backend recipe 唯一实现随机选择，不在浏览器另做随机算法。
- 保留当前随机插入 residues 的限制，不增加隐式固化、单独删除或 ID 猜测。显示随机结果和后续编辑的真实后果。
- 保留 whole-track absent 与 present all-null，展示各轨道完整摘要。模型兼容性/effective-input 展示使用 ESM3 owner 的权威投影；不为兼容模型删除 named atoms 或科学内容。
- Studio 退出和页面离开时保护未保存编辑；顶部保存直接写回整份会话，复用仍有效的 normalized preview，内容或来源变化后再重新预览，失败保留编辑。Ctrl／⌘ Z 与 Ctrl／⌘ Shift Z 按焦点范围撤销／重做。草稿科学错误与模型执行不兼容分别表达。

**验收：** 单格及粘贴确认后依次应用并可分别撤销；显式多轨批量、随机重抽、Function 端点／拆分和布局变化经过 preview→apply，再可 undo／redo→保存→重开。快速输入、无效粘贴、焦点范围和输入法组合确认有浏览器交互回归；按相同已确认 document 执行得到一致 conditioning，合法稀疏 Prompt 可以保存。

### P5：多来源合并、手动对应和精确刚体编辑

**依赖：** P4 的统一 preview/undo；P0 合并和坐标编辑合同。

交付：

- 合并入口通过明确的普通 I/O/author Nodes 提供 `merge_sources`；显示 source 顺序和来源，不把原始数据嵌进 document。
- 接入已选证据分屏：上下序列视图与精确对应表同步，支持手动 match/source gap/target gap、调整对应和区间。不提供自动对应或自动对齐草稿，不能凭数组位置建立科学关系。
- 显示逐残基、逐轨道的新增/保留/替换与冲突，用户明确选择采用部分；来源 Mask 覆盖、新增目标残基及注释后果均在预览中单独说明，由用户明确决定。全源/全目标覆盖、跨链和 unmapped 数据后果经 backend admission；Function 区间不自动截短以让合并成功。
- 合并新来源涉及 graph 改动时，来源连接与已确认 document 的写回必须有一个后端 authoring 原子结果；取消不能留下已改的 Workflow。只发布而未引用的 immutable Input 与修改 Workflow 分别处理。
- 三维残基选择支持连续和非连续集合；整个选区接受一个精确刚体变换，未选残基不动。
- 中键旋转镜头、Shift＋中键平移、滚轮缩放；三维点选与 B 穿透框选同步残基选区。G 默认在操作开始时的视平面移动，R 默认绕当时视线旋转；X/Y/Z 约束世界轴，再按同轴解除。鼠标、数值与按钮共享持续操作，Enter／左键确认，Esc／右键取消；最终坐标仍采用世界坐标，位移使用 Å、角度使用 °。旋转默认中心为选区全部现有原子坐标的几何中心；允许选择明确的残基位置或输入自定义中心，并显示中心标记。所选残基位置的精确坐标、连续变换次序及边界提示遵循[Prompt 编辑规格](2026-09-17-prompt-editing-spec.md)，后端 recipe 应用 rotation/translation。预览/确认/取消/undo 不与 viewer camera 旋转混淆。
- 对边界不连续作定位提示；不自动最小化或移动邻居，不支持原子单选／结构几何缩放。
- 当前仍使用 3Dmol；拖动经 90 ms debounce、后端 preview 和 PDB 模型重载更新显示，尚未满足流畅实时预览要求。此次阶段性通过保留这一后续优化项，未更换 renderer。

**验收：** 不同长度及缺口来源完成手动对应与部分采用，结果与预览一致；刚体操作保持选区内部相对几何且未选坐标不变；默认中心按选区全部现有原子坐标计算，残基位置中心/自定义中心与标记及实际变换一致；取消、撤销和重开均核对；无对齐确认不会产生隐式科学对应。

### P6：完整项目管理与命名版本

**依赖：** P0 的持久化合同、P1 的完整 authoring state。可在相关依赖完成后与 P4/P5 独立推进。

交付：

- 项目重命名、通用复制、最近删除、恢复和永久删除。
- 通用复制带当前 Workflow、参数、Prompt、所需 Inputs 和画布布局，重定位 Project-scoped refs；不带命名版本、Run/Results 或 Cache。示例首次编辑复制仍可引用旧示例结果，不能与通用复制混淆。
- 命名版本引用一个确定的 immutable Draft revision 与 UI snapshot；不强制把可能未完成的 Draft 当 runnable Commit。执行仍需正常 Commit admission。
- 打开旧版本先查看；首次修改时建立新的当前工作并产生新的编辑 revision，保留旧版本和打开前当前工作，明确显示来源并提供返回原工作的入口；无需引入通用 Git 分支系统。
- UI state 由前端解释，后端持久化 opaque payload；命名版本记录精确布局 snapshot。Draft 保存与 UI state 保存分别显示状态，不能一方失败仍声称全部成功。
- 删除进入可恢复状态，恢复保持 Project identity、Inputs、版本和 Run evidence。删除运行中的项目时不自动取消，提供等待完成或明确取消后删除，Run closure 后才以 `deleted_at` 标记最近删除，项目数据保留原位；永久删除需明确用户动作及引用处理合同，防止损坏其他有效项目。
- Project 切换、历史打开、复制和删除都遵守 Prompt 未保存离开流程；输入和科学内容不依赖 localStorage 生存。

**验收：** 创建版本→继续编辑→打开旧版→分出当前工作→返回原工作；复制后尚未运行，源项目不受影响；删除/恢复保留原身份与完整内容；清空浏览器存储仍可恢复项目和版本布局。

### P7：真实示例、三条完整旅程与交付验收

**依赖：** P1–P6；真实示例按冻结的科学合同生成和打包。

交付：

- 用当前默认 Workflow、明确 Bindings/Methods/seed 生成真实完成的 3GB1 结果，保留 Ledger、Commit 科学定义、Typed Outputs、候选谱系、Score、Selection 和结构对齐证据。
- 通过 backend owner 安装可读取的例子资源；包中声明所需完整数据，不复制前端模拟 JSON，也不提交 `.local/` 原始运行目录、环境或凭据。完整结果随安装包离线分发，首次打开即可查看；资源身份和体积见预置结果规格。
- 科学定义或示例 Workflow 改变时，按当前 Commit admission 更新示例和证据，不能重标旧结果；不修改 canonical verification Workflow 来迎合 UI。
- 完成三条旅程：批量 FASTA→评分/前后筛选→折叠→导出；Prompt→ESM3→重折叠→结构比较→筛选；Prompt→ESM3→ProteinMPNN→重折叠→谱系比较→筛选。
- 清理无行为按钮、固定 3GB1/Top 3/模型文案、README 与测试的过时断言。首次启动真实显示 bundled Results，首次修改继续保留正确来源标记。
- 批量 UI 建议以 1000 records 作为容量验收数据，测试列表/筛选/按需加载，不要求为了 UI 性能测试进行 1000 次昂贵 Provider 推理；科学执行采用代表性真实样本。

**验收：** 干净安装的后端和构建后 WebUI 完成三条真实用户旅程；全部阶段的已承诺行为达到第 7 节完成标准。

## 5. 需求追踪表

| ID | 最终要求 | 交付阶段 |
|---|---|---|
| G01 | 画布空白处搜索、Palette 两种分类、有效 Port 高亮、连断线、fit-view | P1 |
| G02 | 参数分组/类型/单位/边界，模型记忆和不可用原因 | P1 |
| G03 | 多选片段复制、内部引用重建、连续撤销 | P1 |
| G04 | 四种 Prompt 来源入口、上传/粘贴、PDB 选链 | P1 |
| G05 | 多记录 FASTA 的独立 Candidate 导入及完整旅程 | P1、P7 |
| G06 | Selection Objective/Observation Selector 编辑、50/50 权重可调 | P1 |
| G07 | 三种运行范围、范围高亮、真实摘要与 blockers | P0、P2 |
| G08 | 整次取消、失败后继续、分支状态和节点详情 | P2 |
| G09 | 断连/重开恢复、失败取消后的部分输出 | P2 |
| G10 | 阶段结果导航、任意集合、纯序列/无 Selection 流程 | P3 |
| G11 | 完整谱系、精确 Score/Context/Method 展示与来源 | P3 |
| G12 | 多候选并排及已有对齐证据叠加 | P3 |
| G13 | 临时排序筛选、保留勾选；AND/OR 分组筛选、排序取前 N、精确勾选均可保存为流程操作，勾选引用缺失报错 | P1、P3 |
| G14 | 固定 ZIP、精确 provenance、无结构情况 | P3 |
| G15 | 正确判断旧结果并在各视图持续显示 | P0、P3 |
| G16 | 三种 Prompt 模式、多轨道联合预览和矩阵输入 | P4 |
| G17 | Function 端点修改/拆分、diagnostics 点击定位 | P4 |
| G18 | 随机 Mask/插入、scope/seed/重抽与实际位置 | P4 |
| G19 | 稀疏轨道语义、完整摘要、连接模型兼容性展示 | P4 |
| G20 | 多来源合并、证据分屏、对应表/gap/逐区域选择 | P0、P5 |
| G21 | 精确刚体平移/旋转、轴约束、边界提示 | P0、P5 |
| G22 | 项目重命名/复制/删除/恢复/永久删除 | P6 |
| G23 | 命名版本、旧版继续、原工作保留、布局快照 | P6 |
| G24 | 真实预置结果及首次编辑后的来源链接 | P7 |
| G25 | 删除无行为按钮、固定科学文案和结构 fallback | P1–P7 随所属能力交付 |

## 6. 已确认产品决定

以下决定与第 2 节的实施合同共同定义当前产品行为。

| ID | 议题 | 已确认决定 |
|---|---|---|
| D01 | 从节点继续的范围及缓存政策 | 仅执行选中节点及其后代，强制重算，即使已有完全匹配缓存也不重放；范围外所需上游只复用，提前展示计算范围 |
| D02 | 没有可复用上游 | 拒绝继续；不在此动作中补跑上游或扩大范围 |
| D03 | 范围外节点/Selection | 界面明确标记范围外，不混同失败、阻塞或取消；后端记录方式由实施合同明确 |
| D04 | 保存为流程操作 | 支持条件筛选、排序并取前 N 个、手动勾选候选三类。筛选支持 AND/OR 和明确分组，保存后含义不变；手动选择保存精确候选引用，在当前输入集合匹配，缺失报错，不替换或跳过，用户可重新勾选 |
| D05 | 逐区域合并 | 明确选择采用范围，可细到残基×轨道；Mask 覆盖、新增残基和注释后果在预览中单独说明，不自动决定 |
| D06 | 自动对应 | 不需要自动对应；只提供手动残基对应，不实施自动对齐草稿或算法选择 |
| D07 | 刚体变换 | G 默认视平面、R 默认视线轴，X/Y/Z 约束世界轴；最终世界坐标、位移 Å、角度 °；默认旋转中心为选区全部现有原子坐标的几何中心，允许选明确残基位置或输入自定义中心并显示标记；镜头旋转不改变结构坐标 |
| D08 | 命名版本 | 允许保存未完成 Draft；先查看旧版，首次修改建立新的当前工作，保留旧版本及打开前工作 |
| D09 | 删除运行中的项目 | 不自动取消；提供等待完成或明确取消后删除，Run 结束后才以 `deleted_at` 标记最近删除，项目数据保留原位 |
| D10 | 纯序列/混合导出 | 允许导出；ZIP 包含 FASTA、分数和 manifest，只为确有结构的候选写 PDB，并列明无结构项 |
| D11 | 批量 FASTA | 不按名称或序列自动去重，保留输入顺序和记录来源；非法记录明确定位，默认阻止本次导入，不静默跳过 |
| D12 | 后端重启后继续 | 支持依据旧结果发起新 Run；重新验证 Commit，旧中断 Run 保持 interrupted，不伪装为原 Run 断点恢复 |
| D13 | 旧结果判定 | 科学内容恢复一致即可解除过期提示，仅布局变化不影响结果；无法判断时显示待确认，比较由后端负责 |
| D14 | 导入/合并保存边界 | Workflow 修改整体提交或整体取消；已上传 Input 保留在项目输入列表，项目永久删除时清理 |
| D15 | 预置结果分发 | 完整真实结果随安装包离线分发，首次打开即可查看；体积与原始身份见预置结果规格 |

## 7. 验证与完成标准

每个阶段同时更新当前 producers、consumers、examples 和文档，删除被替代路径。不维护旧原型状态机和生产状态机两套科学实现。

全部测试、构建、类型检查和 lint 在远端验证服务器执行，复用目录已有的 Python 3.12 虚拟环境及前端依赖；不在本地电脑运行。完整验收必须使用同一个固定源码快照与构建产物，不能拼接不同快照的通过结果。

**后端改动：** Python 3.12，先运行受影响 owner/public Interface 的 focused pytest，再运行仓库要求：

```bash
.venv/bin/python -m verification.backend routine
.venv/bin/python -m verification.backend deterministic-acceptance
```

运行范围、Selection、合并、随机性、坐标变换、批量 Candidate identity 的测试验证科学和 evidence 合同；项目复制/恢复验证持久化及输入引用，不只验证 HTTP 状态码。

**前端改动：** 按 [WebUI README](../webui/README.md) 在远端 `webui/` 运行应用 typecheck、真实旅程独立 typecheck、lint、相关 Playwright journeys 及 build。应用 typecheck 不覆盖 `real-tests/`，两者均须通过。这是前端自己的验收要求，不把 Python backend verification 改成依赖前端。

**浏览器：** 主验收连接真实 public server，经过真实 Draft/Commit、Prompt preview/apply、Run projection 和 Typed Output retrieval。网络故障模拟只用于验证显示/恢复行为，不作为科学执行成功证据。记录关键界面尺寸、键盘/鼠标等价路径、空数据/失败/取消状态；不得凭已有测试名称宣称 export 或真实运行已经验收。

**真实 Provider：** P7 示例生成与三条研究旅程保留当前实现的真实证据；科学/Adapter 合同有变更的部分运行对应现行 acceptance。Provider 工作依仓库当前 campaign 规则串行执行；历史缓存、mock 或 readiness 不能替代所需 acceptance。纯样式修正不无理由重跑昂贵 campaign。

功能标为完成必须满足：

1. 有完整可达的用户入口，可见按钮都有正确行为或明确原因。
2. 需要后台的动作确实经过当前 public Interface 和唯一 owner。
3. 保存、取消、撤销、切项目、重开后的状态符合合同。
4. Candidate、Metric、Method、单位、layout、randomness、lineage 和 evidence 不由 UI 猜测。
5. 代表性旅程和失败路径通过，真实结果可从来源逐项核对。
6. 需求追踪表记录完成证据；接口只存在、按钮只显示、mock-only 演示均不能关闭条目。
