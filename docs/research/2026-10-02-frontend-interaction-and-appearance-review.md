# 前端交互与外观调研

> 2026-10-03 补充：后续研究已按新的设计前提重新开放既有契约、ADR、技术选型与功能范围，见[六个项目的 API 与架构深研](2026-10-03-frontend-architecture/README.md)。本篇保留首轮现状记录；下文关于保留工作区、框架或遵循既有范围的建议不作为后续重设计的约束。

日期：2026-10-02。性质：研究与设计建议，不是新产品规格或本轮验收记录。

本次阅读当前规范和 WebUI 源码，检查已有远端验收截图，并查阅开源项目的官方资料。没有修改产品代码，没有启动本地或远端测试、构建、浏览器验证和 Provider。文中的“已实现”表示源码支持；截图表示对应历史快照的外观；“建议”不表示已有用户研究证明，也不自动扩展现行范围。

**判断：主要研究闭环已经具备，下一轮应优先改善信息层级、科学信息的可读表达和操作反馈。** 现有 Workflow、Prompt Studio 和 Results 三个工作区值得保留。应围绕“我要设计什么、现在在改什么、这次运行做了什么、为什么选择这个候选”组织界面。

**一、用户需要完成什么，目前支持到哪里**

项目定位和对象定义以 [CONTEXT.md](../../CONTEXT.md) 为准；功能范围取[当前集成计划](../2026-09-17-webui-full-integration-plan.md)、各功能 owner 规格及[当前交互约定](../2026-09-29-frontend-interaction-contract.md)。集成计划仍有旧的 Draft/UI 分别保存措辞，保存行为以 [Project Workspace 规格](../2026-09-17-project-workspace-spec.md) L34–74 的统一 workspace publication 为准。

| 用户任务 | 应提供的功能与解释 | 当前实现 | 后续设计重点 |
|---|---|---|---|
| 从自己的材料开始 | 空白、FASTA、PDB、已有 Prompt；上传、粘贴和复用 Input；显式链选择；区分批量候选与单 Prompt | 已实现来源弹窗、记录预览和批量 FASTA；取消保留已发布 Input 的行为有说明。[InputSourceDialog](../../webui/src/InputSourceDialog.tsx) L25、123–154 | 把“导入候选”与“编写生成条件”作为明确任务表达，避免用户先猜底层 Node Type。 |
| 搭建和阅读研究流程 | 搜索操作、类型兼容连线、参数与单位、分组、复制、撤销、定位失败节点 | 已有 React Flow 画布、兼容操作搜索、组接口、面包屑与每层视图；默认示例已分成五阶段。[App](../../webui/src/App.tsx) L134–152、428、615–645、726–745；[WorkflowPorts](../../webui/src/WorkflowPorts.tsx) L40–83 | 延续阶段概览→组内节点→专用编辑器的层级；明确区分操作名称、参数、端口和内部标识。 |
| 编写蛋白质条件 | 同一残基轴上的五轨矩阵；表格编辑、批量操作、Mask、随机条件、Function 区间；结构与矩阵联动 | 已有 AG Grid Community 矩阵、键盘编辑、原子粘贴、可调整双栏、复杂操作弹窗及独立撤销。[ResidueMatrix](../../webui/src/ResidueMatrix.tsx) L82–179；[PromptStudio](../../webui/src/PromptStudio.tsx) L601–646 | 强化当前轨道、活动格、选区和编辑态的区分；增加概览与密度选择的设计评估。 |
| 修改局部结构与合并来源 | 精确选区、G/R、世界轴和数值、预览、确认/取消；来源与目标对应关系可检查 | 已有拾取、B 穿透框选、G/R、镜头保持、合并证据编辑；实时变换反馈仍受后端预览约束。[StructureViewer](../../webui/src/StructureViewer.tsx) L112、175–179、220–287；[Prompt 规格](../2026-09-17-prompt-editing-spec.md) | 即时预览是明确未完成项，继续按已挂起事项记录；若恢复工作，应先测量现有渲染路径。 |
| 理解和控制一次 Run | 启动前看实际执行范围；区分重算、复用和范围外；运行中可看状态、取消和定位问题 | 已有全流程、运行到节点、从节点继续；准备范围后确认；Workflow/Results 共用状态和诊断。[RunDialog](../../webui/src/RunDialog.tsx) L20–34；[App](../../webui/src/App.tsx) L166–177、704–706 | 用阶段和正在执行的操作作为主要反馈；节点完成百分比明确为节点计数，不表达预计剩余时间。 |
| 理解和比较结果 | 任意已发布中间结果；候选、序列、结构、Scores、parents 和来源；比较、勾选、筛选相互独立 | 已有分页、相邻详情、最多四项比较、已选清单、AND/OR 筛选、已有对齐证据展示。[ResultsWorkbench](../../webui/src/ResultsWorkbench.tsx) L225–247 | 让可比较的指标和参考对象容易读懂，减少长 ID 对主视图的占用；不改变精确关联。 |
| 把筛选决策用于下一轮 | 临时探索可以保存成可编辑 Workflow 操作；确认新增节点、来源和科学规则 | 已有条件、Top-N 和人工勾选的保存预览；科学排名要求显式 Utility Transform。[ResultsWorkbench](../../webui/src/ResultsWorkbench.tsx) L250–254 | 清楚说明“临时查看条件”与“保存到 Workflow”的不同后果，并展示新增操作的位置。 |
| 保存和恢复工作 | 可见保存状态、失败保留、明确重试、命名版本、复制、旧版编辑与返回、可靠导出 | 已有 WorkspaceEditor 和项目版本管理；Workflow 与 UI 一起发布；导出包含实际数据和来源。[WorkspaceEditor](../../webui/src/workspace-editor.ts)；[ProjectWorkspaceDialog](../../webui/src/ProjectWorkspaceDialog.tsx) L115–124 | 在三个工作区保持可辨识的项目、编辑状态和结果来源；区分当前编辑与旧 Run 结果。 |

这些能力应串成研究旅程评估，而不是逐个按钮评估。现行集成计划 L172 起列出的代表性旅程为：批量 FASTA→评分/筛选→折叠→导出；Prompt→ESM3→重折叠→比较→筛选；Prompt→ESM3→ProteinMPNN→重折叠→谱系比较→筛选。

**二、外观与交互的具体观察**

已有的深色橄榄背景、琥珀色主要动作、节点类别色和阶段卡片构成了一致的视觉方向。问题主要出现在同一产品内的字号、密度、术语层级和空间分配；改变配色不是解决这些问题的前提。

| 观察与证据 | 对用户的影响判断 | 建议 |
|---|---|---|
| 普通节点标题 11px，状态/端口规则等为 7–9px；新阶段卡片标题 16px、参数 12–13px。[styles.css](../../webui/src/styles.css) L136–164；[workflow-authoring.css](../../webui/src/workflow-authoring.css) L35–48、92–114 | 阶段概览比进入组后的细节明显更易读；缩放还会进一步缩小文字。此判断来自 CSS 与历史截图，未进行新可读性实验。 | 统一正文、标签、注释、数值四级字号。建议先试正文 13–14px、重要标签不低于 12px；这属于设计起点，不是标准规定。靠折叠和按需详情控制密度。 |
| Palette 固定 260px，右侧结果摘要固定 244px；二者展开时占用约 504px。[styles.css](../../webui/src/styles.css) L80、169 | 在 1288px 桌面，中央画布仅余约 784px；查看完整阶段和跨阶段引用需要更多横向移动。 | 保留现有阶段导航与 100% 阅读；评估右侧摘要折叠/按需打开，把空间优先交给正在编辑的区域。不要默认 Fit View 把文字缩成概览。 |
| 主界面出现 `Active Catalog`、`contracts`、`Run Closure`；结果筛选标签包含 Metric/Method ID 和 Context Profile JSON。[App](../../webui/src/App.tsx) L169、729；[ResultsWorkbench](../../webui/src/ResultsWorkbench.tsx) L80 | 用户需要把系统语言再翻译成研究意图，筛选项尤其难比较。 | 主层显示已定义的名称、单位、Method、参考对象和来源摘要；精确标识与完整 Context 可展开、复制。采用当前 Catalog/Commit 科学定义中的展示信息，不猜测含义。 |
| Results 候选列表的主要列是 Candidate、类型/长度、parents；完整候选 ID 会换行，指标主要在详情。[ResultsWorkbench](../../webui/src/ResultsWorkbench.tsx) L231–245；[results.css](../../webui/src/results.css) L18–27 | 列表更擅长查身份，按科学指标快速比较的效率有限。 | 评估用户选定的少量 Score 列；每列绑定完整观察组。显示名/短 ID 仅作阅读标签，完整 Candidate Data Reference 保留。缺失、歧义和无法比较必须可见。 |
| 矩阵每个残基列默认 88px、每轨 68px，固定轨道标题 142px；每格还显示状态文字。[ResidueMatrix](../../webui/src/ResidueMatrix.tsx) L30、83–88、130 | 精确单格编辑清楚，但结构与矩阵并排时，只能同时看到有限残基，长序列全局关系较难读。 | 保留当前详细编辑模式，评估紧凑概览/残基总览条；全局定位后再展开局部。Coordinates 和 Function 的完整编辑仍用专用区域。 |
| Prompt 头部、模式、摘要和选区占多条横栏；常用矩阵工具较多。历史截图中矩阵本体开始于屏幕中部。 | 科学状态可见，但非当前任务信息可能挤占操作空间。 | 当前选区与待确认修改优先常驻；来源摘要/详细轨道状态可渐进展开。不要移走必需的单位或把 Mask 与 absent 合成一个状态。 |
| 画布、矩阵与 3D 已各有快捷键提示，帮助入口分散。[App](../../webui/src/App.tsx) L739；[ResidueMatrix](../../webui/src/ResidueMatrix.tsx) L179；[StructureViewer](../../webui/src/StructureViewer.tsx) | 专业用户有快捷路径，但第一次使用时需要分别寻找帮助。 | 统一“当前区域操作帮助”，同时保留就近按钮；遵守现有文本/画布/矩阵/3D/弹窗焦点边界。 |
| 运行进度计算为已完成节点数/总节点数。[App](../../webui/src/App.tsx) L168–174 | 一个很慢的 Provider 节点可能使百分比长时间不变；百分比不能据此推导时长。 | 保留节点计数作为辅助信息，主要显示当前研究阶段、实际节点、运行状态和可用控制；没有可靠估计时不显示 ETA。 |

文字对比度和点击目标可以采用 W3C 的可读性基准作为设计检查：普通文字至少 4.5:1，大字至少 3:1；目标尺寸规则为 24×24 CSS px，并有间距等例外。本次未测量整个界面的实际对比度或命中面积，不能据截图宣布通过或失败。参见 [W3C 对比度说明](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)与[目标尺寸说明](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)。

**三、哪些是明确限制，哪些不应算缺口**

- **明确未完成：结构变换即时反馈。** 当前为 90ms 尾沿防抖→后端 preview→清除模型并重新加载 PDB→恢复镜头。连续移动会推迟请求。现行约定 L59–63 明确这项优化挂起；本报告没有重新启动它。若后续恢复，应先评估以操作起点为基准的浏览器临时坐标预览，确认后使用后端结果，取消恢复，且一次变换只产生一条历史。替换 renderer 本身不能消除往返等待。
- **明确待完善：Selector/Objective 来源字段的表达。** [集成计划](../2026-09-17-webui-full-integration-plan.md) L6 已记录进一步简化未完成；结果筛选的长 ID/JSON 标签也是可见的表达负担。简化展示不代表删除精确来源。
- **当前规模边界：分页浏览和全量探索不同。** 当前每集合首批读取 100 条，显示页 50 条；完整搜索、筛选和排序前由用户明确加载整个当前集合。已有 1000 条测试旅程，不能推导任意规模都流畅。[Result Explorer 规格](../2026-09-17-result-explorer-spec.md) L29、45；[容量旅程](../../webui/tests/result-capacity.spec.ts) L6–55。
- **会话恢复不是重启恢复。** Workflow/Results 往返保留筛选、选中、比较和滚动，规范只保证当前浏览器会话。`App.tsx` L192 的 Map 不等于刷新后持久化；不应将未承诺的行为记为 bug。[Result Explorer 规格](../2026-09-17-result-explorer-spec.md) L17。
- **常规 Run 历史列表明确在当前范围外。** 代码主要打开项目最新 Run 或示例参考结果，这与当前范围一致。命名 Workflow 版本也不等于 Run 历史。Galaxy 的历史界面可以研究，但不能因此列为本轮漏做功能。
- **其他明确不纳入：** 账号/多人协作、项目文件夹/标签/收藏、单节点取消、原子级编辑、几何缩放、隐式结构优化、自然语言 Prompt、独立 ProteinMPNN 约束编辑器、自动残基对应/自动对齐草稿。依据[集成计划](../2026-09-17-webui-full-integration-plan.md) L20 起的范围边界。

**四、开源社区可参考什么**

详细功能、官方截图/演示入口、源码和许可来源见[开源参考调研](2026-10-02-frontend-open-source-references.md)。这些项目覆盖了本产品的不同交互难题；本次考察未找到可直接覆盖全部现行科学合同的整套前端。

| 参考方向 | 最适合借鉴的内容 | 本项目的适配原则 |
|---|---|---|
| Biohub `esm` widgets | 蛋白质多轨条件编写，分步选择来源/区段/目标位置的引导 | 用于设计 Prompt 的操作顺序与说明；托管 Forge 界面和开源 widgets 要分开讨论。 |
| Mol* / MolViewSpec | 结构与序列的联动、选择/高亮、视图控制与观察状态表达 | 先学结果阅读交互；显示状态不能代替已发布对齐证据、残基轴或 Prompt 科学文档。 |
| Galaxy | 工具、主工作区、执行信息之间的导航，参数及结果来源的可追踪性 | 借鉴运行和证据的可达性；完整历史管理保持在现行范围外。 |
| KNIME Components / Metanodes | 阶段封装、常用配置外露、内部细节按需进入 | 与现有五阶段组最接近；不要引入第二套执行语义或隐式变量。 |
| ComfyUI 子图 | 复杂节点图的折叠、进入、边界接口和局部编辑 | 借鉴渐进展开和节点操作发现方式；组端口继续精确映射真实 Node Instance/Port。 |
| Vitessce | 多视图共享选择、显式协调状态、可配置面板布局 | 借鉴矩阵/结构/结果之间的联动原则；不要搬入单细胞数据模型或额外科学解释层。 |

基础组件本身已经采用开源社区实现，重设计应在现有复用边界上开展：

| 当前基础 | 本次判断 |
|---|---|
| React Flow | 继续负责画布、端口和交互适配。官方 [Sub Flows](https://reactflow.dev/learn/layouting/sub-flows) 可作基础参考；[Pro Examples](https://reactflow.dev/examples/pro-examples) 中的分组、撤销等示例不能当作默认免费的源码素材。图形 parent/child 也不自动提供本项目的精确科学接口。 |
| AG Grid Community | 继续复用编辑器、焦点和虚拟滚动。官方 [Cell Selection](https://www.ag-grid.com/react-data-grid/cell-selection/) 与 [Clipboard](https://www.ag-grid.com/react-data-grid/clipboard/) 页面标明 Enterprise；本项目现有残基选择与浏览器剪贴板是自己的适配，不能误认为只是开启 Community 选项。 |
| 3Dmol.js | 继续作为当前渲染基础。先测坐标更新与绘制，再决定是否存在更换的实际理由；与 Mol* 的比较应围绕本项目的拾取、身份映射和变换场景。 |
| Radix | 延续公共弹窗和菜单的焦点、键盘及关闭行为；视觉统一优先通过本项目样式完成。 |

社区交互模式、可读源码和可直接嵌入的组件是三种不同参考价值。许可按各项目实际代码核查，模型权重许可、托管服务条款和商业示例许可不互相替代。

**五、建议的推进顺序**

| 顺序 | 具体工作 | 可评估的结果 |
|---|---|---|
| 第一轮：统一阅读与任务表达 | 统一字号、对比度、表单密度；整理 Palette 的研究目的表达；结果指标展示名称/单位/Method/参考对象；内部 ID 可展开；明确保存状态和结果 current/stale/unknown | 用户不查源码，能辨认当前项目、正在修改的对象、结果属于什么 Run，以及某个值的测量含义。 |
| 第二轮：优化决策路径 | 精简常驻工具；统一当前区域帮助；评估列表中的选定指标列；保留已选/比较/查看焦点独立；把保存 Selection 的新增节点及来源更直观地展示 | 用户能从中间结果找出候选、检查选择理由、保存为明确的 Workflow 操作，并返回原阅读位置。 |
| 挂起事项恢复时：结构即时预览 | 在现有 3Dmol 公共接口下测量并验证浏览器临时坐标预览；覆盖确认、取消、轴约束、迟到响应和撤销 | 连续移动有及时反馈，后端仍拥有最终科学解释，一次操作一条历史；实际延迟以测量为准。 |
| 后续按证据决定 | Prompt 紧凑总览、可调整面板、展示密度偏好；若真实候选规模要求更高，再独立明确大集合探索合同 | 只在明确任务和测量支持下增加能力；避免同时引入新渲染器、全新画布与另一套表格。 |

前三个工作区的布局方向可以保持简单：Workflow 以阶段与节点为中心、操作库和结果摘要按需出现；Prompt 以结构和矩阵双栏为中心、复杂编辑局部展开；Results 以集合导航、候选列表和相邻详情为中心、比较槽位及已选清单就近可达。这是在现有结构上收敛信息层级，不要求另建多个功能重复的页面。

后续可用五个任务做用户观察与远端验证：从示例找到并修改生成数量；导入 FASTA 后确认记录与链/来源；选择指定残基并完成编辑/撤销；从中间结果解释两个候选的差异并保存筛选；在保存失败或预览失败后恢复工作。记录完成步骤、误操作、是否需要提示和等待时的困惑，再决定设计取舍。测试、类型检查、构建和浏览器检查仍遵循[远端执行政策](../backend-verification.md#execution-policy)。

**六、科学表达必须保留的边界**

- 显示名和短 ID 不参与关联；Candidate 及 Score 继续依靠完整 Candidate Data Reference 与精确 Metric/Method/Context。
- 单位、值形状、方向、缺失状态、参考对象和残基轴不能为“简洁”而被隐去或合并。whole-track absent 与 present/all-Mask 不等价。
- 组与阶段只组织画布；不合并端口、不打乱多来源顺序、不创造统一 seed。
- 临时排序/筛选是阅读状态；保存为 Selection 应完整保留相应合同和来源。排名/Top-N 显式配置 Utility Transform 及其所需权重、缺失策略；条件筛选保留原值单位与 AND/OR 括号；手动选择保留精确 Candidate Data References。
- 结构并排查看与已有证据下的叠加是不同功能；没有已发布证据不自动对齐，镜头操作也不是科学坐标变换。
- Prompt Preview 不等于 Run、Candidate 或 Evidence；临时坐标显示不改写已发布数据。
- Draft、Commit、Run 和 Workspace 各有身份；布局变化不使科学结果过期，Availability 不等于 Readiness。

以上来源为 [CONTEXT.md](../../CONTEXT.md)、[Prompt 规格](../2026-09-17-prompt-editing-spec.md)、[Result Explorer 规格](../2026-09-17-result-explorer-spec.md)、[Run Scope 规格](../2026-09-17-run-scope-spec.md)和 [Project Workspace 规格](../2026-09-17-project-workspace-spec.md)。

**证据说明**

视觉观察实际查看了以下已有远端输出，均为 1288×989；它们用于观察外观，不是新运行的验收证据，也不是性能测量。Results 图来自 1000 条同序列输入的容量旅程，不代表真实研究候选的分布。

- [Workflow 五阶段截图](../../.local/frontend-interactions-20260929/stage-3/artifacts/stage-focused/default-example-groups-the-19d3f-al-crossing-edges-at-1288px/default-stages-1288x989.png)。
- [Prompt 双栏截图](../../.local/frontend-interactions-20260929/round-4b/artifacts/webui-focused-journeys/residue-matrix-matrix-stay-e04a8-and-narrow-two-view-layouts/prompt-desktop-1288.png)。
- [Results 列表与相邻详情截图](../../.local/frontend-interactions-20260929/round-4b/artifacts/webui-focused-journeys/result-capacity-a-real-100-c05df-s-and-retains-hidden-checks/results-adjacent-detail-1288x989.png)。

这些截图位于忽略目录 `.local/`，不纳入提交，也不保证其他检出中存在。可共享的依据是本文记录的观察、源码路径，以及[交互约定中的历史验收记录](../2026-09-29-frontend-interaction-contract.md#验收状态)。09-29 五阶段展示记录了 70 项专项用例及最终 5 项浏览器回归通过；不能据此宣称本轮完成了新验收、完整可访问性评估或实时预览优化。
