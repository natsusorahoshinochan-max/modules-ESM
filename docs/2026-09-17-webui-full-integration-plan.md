# WebUI 全部功能缺口集成计划

- 日期：2026-09-17
- 状态：实施规划；已记录 15 项议题及第二轮 4 项补充决定，当前待确认的产品行为已收敛，技术规格工作见第 6.2 节；不代表功能已完成
- 核对基线：`bfa47720`，规划前工作区干净
- 目标：把八个已选原型的有效产品要求和此前发现的集成缺口接入当前 WebUI，覆盖三个科研场景。
- 完成标准：用户可以从自己的输入开始，编辑、执行、检查、比较、导出并保存实验，不依赖默认示例的固定节点、数量、模型或手工填写内部身份。

## 1. 范围和依据

本计划纳入旧轻量切片曾推迟的合并、随机编辑、刚体结构编辑和项目版本管理。阶段顺序用于控制依赖，不削减最终范围。

依据按职责区分：

1. [CONTEXT.md](../CONTEXT.md) 与当前科学规格拥有领域含义及科学合同。
2. [2026-09-02 数据流规格](2026-09-02-clean-scientific-data-flow-refactor-spec.md)及后续 Commit、残基和 ESM3 规格优先于旧原型中的科学实现假设。
3. [已确认功能基线](legacy/2026-08-29-webui-functional-spec.md)和[八个原型](../.scratch/webui-product-definition/)提供用户功能及交互方向。
4. [轻量实现规格](legacy/2026-09-01-lightweight-webui-implementation-spec.md)用于识别原先承诺和推迟范围，不再作为本轮功能上限。

继续遵守当前科学语义：Prompt Studio 编辑普通 `prompt_authoring.author` Node 的 `document`；FASTA/PDB 通过可见的 I/O Nodes 提供；不恢复 managed composition、平行 layout Ports 或旧前端。SS8、Function annotations 重复规则、absent 与 present all-null 按当前规格，不照抄旧原型。Availability 是启动诊断，不等于 Run-scoped Readiness，也不能单独阻止缓存复用或执行。

不新增此前明确排除的功能：账号/多人协作、项目文件夹/标签/收藏、单节点取消、原子级坐标编辑、缩放、隐式结构优化、自然语言生成 Prompt、独立 ProteinMPNN 约束编辑器。按本轮用户决定，不提供自动残基对应或自动对齐草稿，只提供手动对应。仍只提供最近一次 Run 的常规入口；命名版本不等于 Run 历史列表。

## 2. 核对后的实施依赖

| 能力 | 当前真实状态 | 规划处理 |
|---|---|---|
| 上传来源 | 后端已有 Project Input publication；前端 client 无调用 | 接入文件/粘贴输入、来源选择、可见 I/O graph；补最小输入枚举/展示合同 |
| 空白 Prompt | 已有 chain declarations 和 preview/apply | 保留并补多来源入口、模式、交互细节 |
| 多记录 FASTA | 当前 import 输出一个 sequence Candidate，parser 会连接 records | 批量候选导入必须另立明确科学操作，不能把 records 连接后冒充多个 Candidate |
| 运行取消 | public `cancel_run` 已有 | 接入生命周期及部分结果浏览 |
| 派生运行 | `retry_failed` / `force_selected` 复用源 Run 的同一个 Commit 和 retained Plan | 不能直接包装成“运行到节点”或“修改后继续”；需要运行范围规格及 runtime 扩展 |
| 派生运行重启 | 源 Run 缺少 retained Plan 时当前拒绝 | 明确持久证据、Commit 重新 admission 与恢复条件；不重建中断过程中不存在的 outcomes |
| 排序权重 | Workflow-owned `selection_objectives` 已有；前端只改 Node/Binding 参数 | 增加 Observation Selector / Selection Objective 编辑，统一科学身份和缺失策略 |
| 组合条件筛选 | 当前 `selection.filter` 只消费一个精确 Observation Selector | 补齐 AND/OR 及明确分组的合同和流程表达，保存后完整保留条件语义，不降级为单条件或全部 AND |
| 手动勾选保存为流程操作 | 当前勾选只用于前端导出；尚未接入持久化候选选择合同 | 与条件筛选、排序取前 N 一起交付；补齐明确候选引用的科学合同，不能以缺少现有 Node 为由退回仅 UI 勾选 |
| Prompt 高级操作 | recipe 已有随机、刚体、source merge | 接入 UI；合同不足处先明确，再原子更新 owner/protocol/UI |
| 合并细粒度决策 | 现有 `track_decisions` 为每条轨道 adopt/preserve | 不宣称已支持逐残基冲突选择；设计能明确表达选中区域及注释后果的合同 |
| 项目管理 | 只有创建、查找及受保护示例复制 | 通用复制、命名版本、UI snapshots、最近删除需补后端持久化和 public operations |
| 预置结果 | 新环境 `latest_run_id` 为 null，测试明确断言无结果 | 建立当前 Workflow 的真实结果生成、打包、安装和校验路径 |

证据入口：

- [当前客户端](../webui/src/protocol/client.ts)、[App](../webui/src/App.tsx)、[PromptStudio](../webui/src/PromptStudio.tsx)、[StructureViewer](../webui/src/StructureViewer.tsx)。
- [Derived Run implementation](../core/execution/_run_runtime_derived.py)、[Run routes](../protein_workbench_public/http/run_routes.py)。
- [Prompt recipe](../modules/prompt_authoring/recipe.py)、[FASTA parser](../modules/protein_io/fasta.py)、[I/O implementation](../modules/protein_io/implementation.py)。
- [Project owner](../core/project/manager.py)、[Workflow authoring](../core/workflow/authoring.py)、[示例测试](../tests/test_webui_example_v2.py)。

## 3. 每项交付都必须贯通的路径

每项功能以“用户动作 → 当前 public Interface → 现有科学/持久化 owner → 返回 projection/evidence → UI 展示 → 重开后行为”验收。纯视图动作不制造科学事实；有后台实现、类型声明或按钮，不代表完成集成。

前端按实际职责逐步抽出少量有深度的 Modules，不先重写全站：

| Module（规划名称） | 小型 Interface 承担的完整行为 | 主要代码归属 |
|---|---|---|
| Project workspace | 打开/保存当前工作、输入、命名版本、复制和恢复；协调 Draft 与 UI state | `webui/src/` 项目相关代码；`core/project/`、`core/workflow/authoring.py` |
| Workflow authoring | graph 编辑、参数/模型/选择目标、undo 和复制；保持对象引用一致 | `webui/src/workflow-authoring.ts` 及画布相关代码 |
| Prompt session | 一个编辑 document、一个局部 preview、最终保存 preview；支持取消和 undo | `webui/src/PromptStudio.tsx`，`modules/prompt_authoring/` |
| Run session | 范围提案、确认启动、状态订阅、取消、恢复与错误定位 | WebUI Run 代码，`core/execution/`、public Run routes |
| Result explorer | 集合/候选焦点、精确关联、比较、筛选、导出及来源 | WebUI Results 代码；published values 的只读 public projection |

public transport 集中在 `webui/src/protocol/`。类型和请求形状以当前 bundle 为准；新增合同同时更新 Python owner、bundle、TypeScript consumer、fixtures 和测试。合同 owner 验证后下游信任，不在每层复制校验。沿用当前 React/Vite/React Flow/3Dmol，不为本轮另建框架、BFF、通用插件层或双轨协议。

## 4. 阶段计划

### P0：冻结必要的产品/科学合同，建立需求追踪

**依赖：** 无。先消除会导致错误科学结果或返工的歧义。

交付：

- 从本计划第 5 节建立逐项验收条目，标记已有行为、待接入行为和 owner 缺口。
- 形成三份可实施的增量规格：运行范围与复用；结果/Selection authoring；项目快照与恢复。
- 形成 Prompt 扩展合同说明：逐区域合并、Function 端点/拆分、刚体坐标框架及可复现输入；同时核对随机 seed/scope 现有语义。
- 明确 public operation 差异和数据所有权。新增只读 projection 从已发布事实投影；科学计算继续通过明确的 Node/Adapter owner。
- 定义科学内容是否变化的比较方式：由后端已规范化的 Workflow/科学定义判断与 Run Commit 的关系，不能只比较 Project 来源或递增 revision。移动节点不使结果过期，改回原科学内容可重新匹配；未经 admission 的 Draft 如无法判断，应明确显示待确认状态。
- 将本计划第 6.1 节已确认决定落实为实施合同，细化第 6.2 节剩余内容；凡涉及尚未冻结的科学语义，必须先在规格中明确，不能由 UI 实现自行决定。不得重新引入用户已拒绝的补跑上游和自动残基对应方案。

**验收：** 每项缺口都有唯一阶段、owner、用户旅程；范围预览和执行有同一权威来源；没有把 Availability 当 Readiness 或把运行计划预览当成真实 Provider 已可用的保证。

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
- 临时排序/筛选、勾选与焦点分别维护；隐藏已勾选项仍保留并告知。保存为流程操作覆盖条件筛选、排序取前 N、手动勾选候选三类，先显示将新增的可编辑 Node 及所需 Selector/Objective 或候选引用，再写入 Draft，不重算旧结果。筛选完整保留 AND/OR 及分组；手动勾选按精确引用在当前输入集合中匹配，缺失报错并允许用户重新选择。不得把手动勾选仅保留为一次性导出状态。
- 固定 ZIP 直接导出，不要求先保存筛选或重新运行。使用真实 sequence/structure values，携带精确身份、完整 parent refs、Metric/Method/Context、单位、Run/Commit 和输出来源。允许纯序列及混合选择导出：包含 FASTA、分数 CSV 和 manifest，仅为实际有结构的 Candidate 写 PDB，明确列出没有结构的项。
- 画布、Results、比较和导出持续展示实际 Run/Commit 来源及过期状态，不能因 copied-from 一直标旧或因非复制项目漏标。
- 删除缺少数据时静默显示 `/3GB1.pdb` 的 fallback。无结果、无结构和加载错误分别展示真实状态。
- 集合分页、按需结构加载、视图渲染容量随批量场景一起验收；不会一次创建所有候选的 3D viewers。

**验收：** 同一 UI 浏览自定义 Workflow 的各阶段及部分输出；父子关系与精确 Score 关联可核对；改变显示筛选不改科学 Workflow；三类保存为流程操作均可编辑、重开并执行，使用能区分不同括号分组的条件验证 AND/OR 语义；手动勾选不依赖表格顺序，候选缺失或相同 Candidate ID 对应不同内容时不得错误匹配；纯序列/混合导出与勾选一致，ZIP 中每个值可追溯；旧结果提示跟随科学变化而非画布变化。

### P4：完整 Prompt 编辑与随机条件

**依赖：** P1 的来源及当前 Prompt session；P0 的科学语义说明。

交付：

- 布局/条件/结构模式改变可用操作和快捷键；blank 默认布局、其他来源默认条件，矩阵保持统一。
- 同一选区组合编辑多条轨道，只保留一个可持续更新的 pending preview，一次应用整组操作；Enter/Esc/undo 和可见按钮等价。
- 补齐矩阵输入细节：数字小数、Backspace、插入数量和序列、区间/非连续选择、跨链边界与焦点；诊断可点击定位。
- Function annotations 提供明确端点编辑和拆分，完整 tuple 的变更经过后端 preview；遵守可重叠、完全相同 tuple 不重复的现行合同，不自动裁剪或合并。
- 增加随机 Mask/插入控件：count、eligible scope、seed、换 seed 重抽、实际位置显示和最终确认；backend recipe 唯一实现随机选择，不在浏览器另做随机算法。
- 保留当前随机插入 residues 的限制，不增加隐式固化、单独删除或 ID 猜测。显示随机结果和后续编辑的真实后果。
- 保留 whole-track absent 与 present all-null，展示各轨道完整摘要。模型兼容性/effective-input 展示使用 ESM3 owner 的权威投影；不为兼容模型删除 named atoms 或科学内容。
- Studio 退出和页面离开时保护未保存编辑；最终保存总是确认新鲜 normalized preview，失败保留编辑。草稿科学错误与模型执行不兼容分别表达。

**验收：** 多轨道联合编辑、随机重抽、Function 端点/拆分、布局变化可 preview→apply→undo→保存→重开；按相同已确认 document 执行得到一致 conditioning，合法稀疏 Prompt 可以保存。

### P5：多来源合并、手动对应和精确刚体编辑

**依赖：** P4 的统一 preview/undo；P0 合并和坐标编辑合同。

交付：

- 合并入口通过明确的普通 I/O/author Nodes 提供 `merge_sources`；显示 source 顺序和来源，不把原始数据嵌进 document。
- 接入已选证据分屏：上下序列视图与精确对应表同步，支持手动 match/source gap/target gap、调整对应和区间。不提供自动对应或自动对齐草稿，不能凭数组位置建立科学关系。
- 显示逐残基、逐轨道的新增/保留/替换与冲突，用户明确选择采用部分；来源 Mask 覆盖、新增目标残基及注释后果均在预览中单独说明，由用户明确决定。全源/全目标覆盖、跨链和 unmapped 数据后果经 backend admission；Function 区间不自动截短以让合并成功。
- 合并新来源涉及 graph 改动时，来源连接与已确认 document 的写回必须有一个后端 authoring 原子结果；取消不能留下已改的 Workflow。只发布而未引用的 immutable Input 与修改 Workflow 分别处理。
- 三维残基选择支持连续和非连续集合；整个选区接受一个精确刚体变换，未选残基不动。
- G/R、X/Y/Z、数值输入与按钮共享流程；默认世界坐标，位移使用 Å、角度使用 °。旋转默认中心为选区全部现有原子坐标的几何中心；允许选择明确的残基位置或输入自定义中心，并显示中心标记。所选残基位置如何解析为精确坐标、连续变换次序及边界提示规则在 P0 定稿，后端 recipe 应用 rotation/translation。预览/确认/取消/undo 不与 viewer camera 旋转混淆。
- 对边界不连续作定位提示；不自动最小化或移动邻居，不支持原子单选/缩放。

**验收：** 不同长度及缺口来源完成手动对应与部分采用，结果与预览一致；刚体操作保持选区内部相对几何且未选坐标不变；默认中心按选区全部现有原子坐标计算，残基位置中心/自定义中心与标记及实际变换一致；取消、撤销和重开均核对；无对齐确认不会产生隐式科学对应。

### P6：完整项目管理与命名版本

**依赖：** P0 的持久化合同、P1 的完整 authoring state。可在相关依赖完成后与 P4/P5 独立推进。

交付：

- 项目重命名、通用复制、最近删除、恢复和永久删除。
- 通用复制带当前 Workflow、参数、Prompt、所需 Inputs 和画布布局，重定位 Project-scoped refs；不带命名版本、Run/Results 或 Cache。示例首次编辑复制仍可引用旧示例结果，不能与通用复制混淆。
- 命名版本引用一个确定的 immutable Draft revision 与 UI snapshot；不强制把可能未完成的 Draft 当 runnable Commit。执行仍需正常 Commit admission。
- 打开旧版本先查看；首次修改时建立新的当前工作并产生新的编辑 revision，保留旧版本和打开前当前工作，明确显示来源并提供返回原工作的入口；无需引入通用 Git 分支系统。
- UI state 由前端解释，后端持久化 opaque payload；命名版本记录精确布局 snapshot。Draft 保存与 UI state 保存分别显示状态，不能一方失败仍声称全部成功。
- 删除进入可恢复状态，恢复保持 Project identity、Inputs、版本和 Run evidence。删除运行中的项目时不自动取消，提供等待完成或明确取消后删除，Run closure 后才移动项目；永久删除需明确用户动作及引用处理合同，防止损坏其他有效项目。
- Project 切换、历史打开、复制和删除都遵守 Prompt 未保存离开流程；输入和科学内容不依赖 localStorage 生存。

**验收：** 创建版本→继续编辑→打开旧版→分出当前工作→返回原工作；复制后尚未运行，源项目不受影响；删除/恢复保留原身份与完整内容；清空浏览器存储仍可恢复项目和版本布局。

### P7：真实示例、三条完整旅程与交付验收

**依赖：** P1–P6；真实示例的生成/打包设计从 P0 开始，在相关合同稳定后生成最终结果。

交付：

- 用当前默认 Workflow、明确 Bindings/Methods/seed 生成真实完成的 3GB1 结果，保留 Ledger、Commit 科学定义、Typed Outputs、候选谱系、Score、Selection 和结构对齐证据。
- 通过 backend owner 安装可读取的例子资源；包中声明所需完整数据，不复制前端模拟 JSON，也不提交 `.local/` 原始运行目录、环境或凭据。优先满足首次打开即可查看；先核算完整证据体积，再决定安装包内附带或独立资源包分发，具体形式及资源使用条件在实施规格中确认。
- 科学定义或示例 Workflow 改变时，按当前 Commit admission 更新示例和证据，不能重标旧结果；不修改 canonical verification Workflow 来迎合 UI。
- 完成三条旅程：批量 FASTA→评分/前后筛选→折叠→导出；Prompt→ESM3→重折叠→结构比较→筛选；Prompt→ESM3→ProteinMPNN→重折叠→谱系比较→筛选。
- 清理无行为按钮、固定 3GB1/Top 3/模型文案、README 与测试的过时断言。首次启动真实显示 bundled Results，首次修改继续保留正确来源标记。
- 批量 UI 建议以 1000 records 作为容量验收数据，测试列表/筛选/按需加载，不要求为了 UI 性能测试进行 1000 次昂贵 Provider 推理；科学执行采用代表性真实样本。

**验收：** 干净安装的后端和构建后 WebUI 完成三条真实用户旅程；全部阶段的已承诺行为达到第 7 节完成标准。

## 5. 缺口追踪表

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

阶段依赖主线：`P0 → P1 → P2 → P3 → P7`；Prompt 路线为 `P1 → P4 → P5 → P7`；项目路线为 `P0/P1 → P6 → P7`。顺序不意味着前端先做全部外壳、后端最后补接线；每个阶段都是实际可验收的交付。

## 6. 用户决定与剩余规格工作

### 6.1 已确认决定

本节记录用户针对决策清单的逐项批注，取代原先建议；不从“同意方向”推导出尚未给出的算法、默认值或清理政策。编号对应原 15 项议题；未另标轮次的批注指第一轮，其中批注 11 同时确认 D11–D15 的方向。第二轮批注 1–4 分别确认强制重算、AND/OR 分组、手动选择缺失报错和默认旋转中心，已合入 D01、D04、D07。

| ID | 议题 | 已确认决定 | 决定来源 |
|---|---|---|---|
| D01 | 从节点继续的范围及缓存政策 | 仅执行选中节点及其后代，强制重算，即使已有完全匹配缓存也不重放；范围外所需上游只复用，提前展示计算范围 | 第一轮批注 1；第二轮批注 1 |
| D02 | 没有可复用上游 | 拒绝继续；不在此动作中补跑上游或扩大范围 | 批注 2 |
| D03 | 范围外节点/Selection | 界面明确标记范围外，不混同失败、阻塞或取消；后端记录方式由实施合同明确 | 批注 3 |
| D04 | 保存为流程操作 | 支持条件筛选、排序并取前 N 个、手动勾选候选三类。筛选支持 AND/OR 和明确分组，保存后含义不变；手动选择保存精确候选引用，在当前输入集合匹配，缺失报错，不替换或跳过，用户可重新勾选 | 第一轮批注 4；第二轮批注 2、3 |
| D05 | 逐区域合并 | 明确选择采用范围，可细到残基×轨道；Mask 覆盖、新增残基和注释后果在预览中单独说明，不自动决定 | 批注 5 |
| D06 | 自动对应 | 不需要自动对应；只提供手动残基对应，不实施自动对齐草稿或算法选择 | 批注 6 |
| D07 | 刚体变换 | 默认世界坐标、位移 Å、角度 °；默认旋转中心为选区全部现有原子坐标的几何中心，允许选明确残基位置或输入自定义中心并显示标记；镜头旋转不改变结构坐标 | 第一轮批注 7；第二轮批注 4 |
| D08 | 命名版本 | 允许保存未完成 Draft；先查看旧版，首次修改建立新的当前工作，保留旧版本及打开前工作 | 批注 8 |
| D09 | 删除运行中的项目 | 不自动取消；提供等待完成或明确取消后删除，Run 结束后才移动项目 | 批注 9 |
| D10 | 纯序列/混合导出 | 允许导出；ZIP 包含 FASTA、分数和 manifest，只为确有结构的候选写 PDB，并列明无结构项 | 批注 10 |
| D11 | 批量 FASTA | 不按名称或序列自动去重，保留输入顺序和记录来源；非法记录明确定位，默认阻止本次导入，不静默跳过 | 批注 11 |
| D12 | 后端重启后继续 | 支持依据旧结果发起新 Run；重新验证 Commit，旧中断 Run 保持 interrupted，不伪装为原 Run 断点恢复 | 批注 11 |
| D13 | 旧结果判定 | 科学内容恢复一致即可解除过期提示，仅布局变化不影响结果；无法判断时显示待确认，比较由后端负责 | 批注 11 |
| D14 | 导入/合并保存边界 | Workflow 修改整体提交或整体取消；已上传未使用 Input 的保留/清理细节仍待规格明确 | 批注 11 |
| D15 | 预置结果分发 | 优先满足首次打开即可查看；先核算证据体积，再决定随安装包附带或独立分发，尚未选定分发形式 | 批注 11 |

### 6.2 剩余技术规格工作

当前四项待确认产品行为均已得到用户决定。以下不重开已确认决定，只列为后续技术规格工作的输入，不构成新的逐项用户确认清单；它们不阻止独立的上传、画布操作、取消等工作。若细化中出现新的科学含义或用户数据丢失取舍，再单独提出。

- **运行范围的证据合同：** 范围外节点/Selection 是否进入 Run Ledger、如何表达、如何闭合；后端重启后依据哪些已保存事实完成 Commit admission 和上游复用。
- **Selection 细节：** AND/OR 及分组的正式表达和与精确 Observation Selector/missing policy 的关系；遵守当前合同的排序并列和顺序规则；精确勾选引用的持久化及缺失诊断。D04 已确定缺失报错，不再讨论自动跳过、替换或默认读旧结果；不得因现有合同不足删除三类能力中的任何一类。
- **合并及刚体细节：** 采用范围、Mask 覆盖、新增残基、Function 区间后果的确切 document 表达；明确残基定位点的坐标解析、连续变换组合次序与边界提示规则。默认旋转中心已确定，不再包含该选择或自动对应算法的决策。
- **输入和项目持久化细节：** FASTA 缺失名称的显示和记录寻址；未引用 Input 的保留/清理；命名版本与原工作的返回入口、永久删除时的引用处理。已确认的不自动去重、不静默跳过、整体提交/取消原则不变。
- **结果一致性与分发细节：** 当前 Draft 与 Run Commit 科学内容的权威比较方法；预置证据体积及最终分发形式。D15 同意的是决策过程和首开体验目标，不是已选定在线下载。

## 7. 验证与完成标准

每个阶段同时更新当前 producers、consumers、examples 和文档，删除被替代路径。不维护旧原型状态机和生产状态机两套科学实现。

**后端改动：** Python 3.12，先运行受影响 owner/public Interface 的 focused pytest，再运行仓库要求：

```bash
.venv/bin/python -m verification.backend routine
.venv/bin/python -m verification.backend deterministic-acceptance
```

运行范围、Selection、合并、随机性、坐标变换、批量 Candidate identity 的测试验证科学和 evidence 合同；项目复制/恢复验证持久化及输入引用，不只验证 HTTP 状态码。

**前端改动：** 在 `webui/` 运行 `npm run typecheck`、`npm run lint`、相关 Playwright journeys 及 `npm run build`。这是本轮新增功能自己的验收要求，不把 Python backend verification 改成依赖前端。

**浏览器：** 主验收连接真实 public server，经过真实 Draft/Commit、Prompt preview/apply、Run projection 和 Typed Output retrieval。网络故障模拟只用于验证显示/恢复行为，不作为科学执行成功证据。记录关键界面尺寸、键盘/鼠标等价路径、空数据/失败/取消状态；不得凭已有测试名称宣称 export 或真实运行已经验收。

**真实 Provider：** P7 示例生成与三条研究旅程保留当前实现的真实证据；科学/Adapter 合同有变更的部分运行对应现行 acceptance。Provider 工作依仓库当前 campaign 规则串行执行；历史缓存、mock 或 readiness 不能替代所需 acceptance。纯样式修正不无理由重跑昂贵 campaign。

功能标为完成必须满足：

1. 有完整可达的用户入口，可见按钮都有正确行为或明确原因。
2. 需要后台的动作确实经过当前 public Interface 和唯一 owner。
3. 保存、取消、撤销、切项目、重开后的状态符合合同。
4. Candidate、Metric、Method、单位、layout、randomness、lineage 和 evidence 不由 UI 猜测。
5. 代表性旅程和失败路径通过，真实结果可从来源逐项核对。
6. 需求追踪表记录完成证据；接口只存在、按钮只显示、mock-only 演示均不能关闭条目。

## 8. 开工顺序与本次产物

下一实施批次从 P0 的运行范围/结果/项目合同和 P1 的输入、参数及 Selection authoring 开始；按阶段拆成可独立评审的小变更。运行取消、参数控件等已有明确合同的工作不必等待所有高级功能的规格全部写完。真实示例资源生成在最终科学合同稳定后执行，避免过早生成随后失效的昂贵结果。

本次只新增并更新规划文件，已同步用户决定及对应阶段验收；尚未改动实现、执行运行代码测试、发起 Provider 运行或生成新的 Acceptance Result。
