# 前端交互与外观：开源实现参考

> 2026-10-03 补充：六个项目已完成进一步的固定版本源码研读，见[API 与架构深研总览](2026-10-03-frontend-architecture/README.md)。本篇保留首轮参考记录；后续研究不以既有科学契约、ADR、框架或排除范围为硬约束，运行历史、分组执行语义与渲染器等均可重新选择。

核查日期：2026-10-02。范围为 Protein Workbench 当前 WebUI；资料限定为项目官方文档、源码、许可证和演示入口。本次完成文档和源码调研，没有安装或运行这些产品，未做性能对比；下文“建议”是针对本项目的设计判断，不代表上游已验证我们的场景。

## 结论与本项目的对应关系

社区已经有成熟的**局部实现**，但这六个项目都不是 Protein Workbench 科学合同的替代品。最值得借鉴的是来源与目标映射、多视图联动、复杂 Workflow 的渐进展开，以及运行结果与证据的邻接布局。当前 React Flow、AG Grid Community、3Dmol.js 和 Radix 已承担底层交互，无需因参考产品换框架。

本项目现状以 [WebUI README](../../webui/README.md)、[操作约定](../2026-09-29-frontend-interaction-contract.md)、[交付范围](../2026-09-17-webui-full-integration-plan.md) 和 [领域词汇](../../CONTEXT.md) 为准：画布已有层级分组和阶段参数，Prompt Studio 已有五轨矩阵与结构选择，Results 已有候选详情、比较与精确来源。结构变换仍是后端异步预览；更换渲染器本身不能解决请求防抖和整模重载。

| 本项目要支持的用户任务 | 首选参考 | 对当前实现的具体用途 |
|---|---|---|
| 明白条件来自哪里、落在目标哪些残基上 | Biohub ESM widgets | 为现有矩阵、来源合并提供来源→目标映射说明和颜色线索 |
| 在结构和残基轨道之间观察同一个对象 | Mol* / MolViewSpec | 完善 3Dmol 视口的显示控制、图例和视图状态；不改变科学对象 |
| 理解本次执行到哪里、输出从哪里来 | Galaxy | 增强当前 Run 的状态、结果和来源入口之间的可达性 |
| 先看阶段目的，需要时再看具体节点 | KNIME、ComfyUI | 细化已有 React Flow 分组、参数摘要、面包屑与端口说明 |
| 在列表、分数、结构间保持明确的选择关系 | Vitessce | 明确哪些视图共享焦点/选择，哪些状态独立保存 |

常规 Run 历史列表、账号与多人协作、自动残基对应及自动对齐均在当前明确排除范围内；外部产品有这些功能不意味着本项目存在对应交付缺口。

## 1. Biohub ESM widgets：最贴近 Prompt 编写任务

**已核实实现。** 官方 `esm` 仓库包含 `ipywidgets` 界面：四种条件轨道按 Accordion 展开，每种轨道按来源蛋白分 Tab；用户选择来源残基区段、设置目标起点、加入 Prompt。`PromptManager` 显示来源区段与目标区段，并用同一来源颜色表示对应片段；独立预览页展示 Sequence、Structure、SS、SASA 和 Function。直接证据见 [轨道/来源界面源码](https://github.com/Biohub/esm/blob/main/esm/widgets/views/esm3_prompt_selector.py)、[来源与目标映射源码](https://github.com/Biohub/esm/blob/main/esm/widgets/utils/prompting.py)、[预览源码](https://github.com/Biohub/esm/blob/main/esm/widgets/views/esm3_prompt_preview.py)。

**可借鉴的交互与外观。** 借鉴“来源→选区→目标→整体预览”的清晰顺序，以及来源色与区段摘要的对应关系。在我们的合并/来源面板中，显示明确的来源残基身份、目标身份和将影响的轨道，比只有字段和数值更容易核对。布局判断来自上述 `Accordion` / `Tab` / `VBox` 源码；本次未取得可直接亲测的独立托管 widgets 演示，不把它描述为经过体验验证的完整产品。

**适配边界。** 保留我们已有的 AG Grid 矩阵，参考其来源说明，不退回逐轨文本框。不要照搬 SDK 的索引换算、mask 表示、来源数量限制或覆盖规则；本项目的 ResidueLayout、absent 与 present all-null、Function 区间语义由自己的科学合同拥有。官方 widgets 源码公开不能证明 Biohub/Forge 托管网站前端公开。

**源码与许可。** [Biohub/esm](https://github.com/Biohub/esm)，当前代码 [LICENSE.md](https://github.com/Biohub/esm/blob/main/LICENSE.md) 为 MIT。本结论限定于仓库代码及 widgets，不外推到模型权重、数据或托管服务条款。

## 2. Mol* / MolViewSpec：结构观察与可恢复视图

**已核实实现。** Mol* 将序列条放在 3D 视口上方，显示控制放在侧栏；悬停呈现结构/链/残基身份，选择在序列和结构中共同标记，提供相机复位、展开视口及快照入口。官方 [总界面说明与截图](https://molstar.org/viewer-docs/) 可直接查看这些布局与行为。MolViewSpec 则把结构表示、颜色和注释等场景信息声明为可保存的数据，Mol* 是其参考实现，见 [官方说明与示例入口](https://github.com/molstar/mol-view-spec)。

**可借鉴的交互与外观。** 让结构占据稳定主视区，将表示方式、着色依据、图例和聚焦动作放在视口边缘；残基摘要紧邻结构与矩阵。对需要重返同一观察角度的 Results 比较，可评估保存相机与显示状态的价值。交互上继续清楚区分悬停、选择、聚焦；不要采用会让单击选择同时跳动相机的默认行为。

**适配边界。** 当前已有 3Dmol 渲染和选择；先改善其交互适配和局部预览，只有实测确认现有公共接口无法满足需求时，才评估 Mol* 的集成成本。MolViewSpec 是可视化场景表示，不是 Workflow Draft、Prompt Authoring Document 或 Run Evidence Ledger；显示中的叠合、测量或截图不能被当作已发布的 Structure Alignment Evidence / Score Observation。

**源码与许可。** [Mol*](https://github.com/molstar/molstar) 及其 [MIT LICENSE](https://github.com/molstar/molstar/blob/master/LICENSE)；[MolViewSpec](https://github.com/molstar/mol-view-spec) 及其 [MIT LICENSE](https://github.com/molstar/mol-view-spec/blob/master/LICENSE)。本阶段以设计参考为主，不建议直接引入完整查看器外壳。

## 3. Galaxy：让运行状态、输出和来源保持相邻

**已核实实现。** Galaxy 的 History 面板按分析过程展示数据，条目可折叠/展开，包含状态、预览、详细信息、重跑和关联输入入口；其官方教程给出了工具区、内容区、History 面板及展开条目的截图。Galaxy 25.0 的运行表单把输入准备、参数与 Workflow 图放在同一界面，并提供输入准备状态和重复运行入口。见 [History 官方教程](https://training.galaxyproject.org/training-material/topics/galaxy-interface/tutorials/history/tutorial.html) 与 [25.0 用户发布说明及演示](https://docs.galaxyproject.org/en/latest/releases/25.0_announce_user.html)。

**可借鉴的交互与外观。** 为当前 Run 使用可折叠的状态与输出摘要，使失败节点、已发布中间结果和来源入口不必跨多个位置查找。沿用本项目“列表与详情相邻”的方向，优先在详情顶部回答“哪个 Node Instance 产生、属于哪个输出 Port、用了哪些输入”。状态同时使用文字/图标，颜色只作辅助。

**适配边界。** 只参考信息组织和可达性；不引入 Galaxy History 模型、常规 Run 历史列表或多用户权限。Galaxy 的条目序号、dataset/job 状态也不能代替 Candidate identity、Node Execution Attempt、Operation Attempt 和 Engine Invocation。这里的建议不是新造一套执行状态。

**源码与许可。** [galaxyproject/galaxy](https://github.com/galaxyproject/galaxy)。当前 [LICENSE.txt](https://github.com/galaxyproject/galaxy/blob/dev/LICENSE.txt) 明确代码自 2026-02-25 起采用 MIT，并另列部分图标、图片和文档的 CC 条款；不要将软件许可自动套用于整站视觉素材。

## 4. KNIME：工作区布局与“组织”/“封装”的区分

**已核实实现。** KNIME 的 Workflow editor 配合节点库、说明、配置与 Node monitor；官方将仅用于组织 Workflow 的 metanode，与可有独立配置和组合视图的 component 区分。见带界面截图的 [用户指南](https://docs.knime.com/ap/5.8/analytics_platform_user_guide/) 与 [Components 指南](https://docs.knime.com/ap/latest/analytics_platform_components_guide/index.html)。

**可借鉴的交互与外观。** 在画布保持主要空间，节点说明/参数作为有明确标题的上下文面板，输出预览靠近当前选中节点。已有阶段卡片可用“阶段目的、关键参数、输入输出摘要、进入详情”的固定层级，避免把所有内部节点参数铺满顶层。

**适配边界。** 本项目当前 group 是 UI 组织，最接近 metanode 的用途；阶段参数只是现有内部字段的映射，不应因视觉封装而产生新的科学 Node Type、隐藏共享 seed 或隐式输入。KNIME 的节点执行交通灯、reset 和组件变量作用域不直接移植。

**源码与许可。** 官方 [knime-oss/knime-ui](https://github.com/knime-oss/knime-ui) 确认包含前端及桌面嵌入相关代码；[KNIME 官方许可页](https://www.knime.com/downloads/full-license) 给出 GPLv3 及 Section 7 附加许可。此次未核实 `knime-ui` 每个前端文件的完整许可覆盖，仓库首页也未显示统一根许可证，因此只推荐产品模式参考，不作整库可直接复制的结论。

## 5. ComfyUI：节点图的渐进展开和外露参数

**已核实实现。** 官方 Subgraph 功能支持把选中节点组合、进入内部编辑、公开输入输出、通过导航栏返回上层、嵌套以及调整外露控件的次序/可见性；蓝图加入后可以独立编辑。带截图的 [Subgraph 官方文档](https://docs.comfy.org/interface/features/subgraph) 是最直接的观察入口；[官方前端仓库](https://github.com/Comfy-Org/ComfyUI_frontend) 还附有搜索、节点库、队列和快捷键演示。

**可借鉴的交互与外观。** 顶层显示易读的阶段卡片、少量常用控件和公开 Port；内部保持原有节点编辑能力；面包屑持续说明当前层级。对我们当前已实现的组，这更适合作为一致性检查，而非待新增功能清单：是否每个入口都明确、公开 Port 是否可辨、复制是否独立、返回是否保留视图。

**适配边界。** 沿用 React Flow 的分组实现，不引入 ComfyUI 的图运行时或插件体系。也不照搬 bypass、批量覆盖随机种子等产品习惯。官网该页同时存在“解组将来支持”和后文已介绍解组的文档不一致，因此不据此推断所有稳定版本的行为。

**源码与许可。** [ComfyUI_frontend](https://github.com/Comfy-Org/ComfyUI_frontend) 的 [LICENSE](https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/LICENSE) 为 GPL-3.0。交互模式参考与复制其代码是两个决定；本调研没有建议直接拷贝源码。

## 6. Vitessce：多视图联动的明确边界

**已核实实现。** Vitessce 用 coordination type、scope 和 value 指定哪些视图共享哪些属性；选择、着色、视图位置等可以有不同联动范围，状态可序列化。见 [联动模型文档](https://vitessce.io/docs/coordination/)。其 [View Types 截图](https://vitessce.io/docs/components/) 和 [官方站点](https://vitessce.io/) 展示图、矩阵、集合列表、控制器及状态视图如何共同构成分析界面。

**可借鉴的交互与外观。** 把候选列表、Score 信息和结构详情安排为稳定的邻接区，同一个 Candidate 的焦点以一致标记出现；面板标题清楚说明当前对象。状态层面，明确区分悬停、当前焦点、比较列表和导出勾选；只有应当共享的状态才联动。Prompt Studio 的矩阵选区与结构高亮也适用这一原则。

**适配边界。** 本项目已明确比较独立于导出勾选，且结构悬停不抢焦点，这是应保留的正确方向。借鉴联动思想即可，不把单细胞数据模型、Zarr 管线或通用可视化平台整体带进来；精确关联仍以 Candidate Data Reference / ResidueLayout 为准，不能按列表位置关联。显示中的临时筛选也不自动成为 Selection Objective。

**源码与许可。** [vitessce/vitessce](https://github.com/vitessce/vitessce)，[LICENSE](https://github.com/vitessce/vitessce/blob/main/LICENSE) 为 MIT；[官方文档](https://vitessce.io/docs/coordination/) 另注明文档为 CC BY 4.0。

## 建议进入设计验证的三个小切口

1. **Prompt 的来源与目标说明。** 在现有来源合并/随机条件详情附近，测试带身份与轨道摘要的映射卡片；以正确理解影响范围为验收目标，不以装饰性颜色数量为目标。
2. **阶段卡片与上下文详情的视觉层级。** 检查默认示例在现有验收视口下，阶段目的、关键参数、公开 Port 和进入入口是否能被快速找到；保留现有 DAG 与分组语义。
3. **当前 Run 的结果与证据定位。** 让当前结果、来源节点和相应执行说明可相互到达；继续保持 Candidate 焦点、比较与导出状态独立。这是对现有路径的信息呈现评估，不扩展为历史管理产品。

结构变换逐帧反馈属于另一个可测量的交互问题：按现行操作约定先评估 3Dmol 公共接口下的浏览器临时坐标预览，再决定是否存在更换渲染器的必要。上述社区资料不足以替代这一实测。
