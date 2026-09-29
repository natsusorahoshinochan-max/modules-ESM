# 默认示例的阶段分组方案与参考

日期：2026-09-29。状态：五阶段组加独立导出节点已实施，远端前端专项验证通过，并经用户确认阶段性通过。范围只涉及画布展示、进入组、组接口和常用参数，不改变当前科学合同。

## 成熟方案的可借鉴部分

| 官方实现 | 已有行为 | 采用的交互原则 |
|---|---|---|
| Blender Frame | 在同一画布上围住相关节点，可命名、移动整个框；用于视觉组织，不要求建立可复用节点组。[官方 Frame 文档](https://docs.blender.org/manual/uk/4.5/interface/controls/nodes/frame.html) | 进入阶段后，仍需要解释步骤时使用小标题／Frame；不要把彩色框等同于已封装的阶段。 |
| Blender Node Group | 一组节点显示成单个节点，支持嵌套；创建组时将跨边界连接转为 Group Input／Output。Tab 进入／退出，面包屑表示层级。[官方 Node Groups 文档](https://docs.blender.org/manual/en/4.5/interface/controls/nodes/groups.html#make-group) | 顶层用阶段卡片收起内部细节；组内左侧输入、右侧输出，保留明确的返回入口。 |
| Blender Group Sockets | 接口可以命名、描述、排序；相关输入可放进面板，面板可默认收起。[官方 Group Sockets 文档](https://docs.blender.org/manual/en/4.5/interface/controls/nodes/groups.html#group-sockets) | 常用参数直接可见，高级参数折叠；参数名称与实际内部字段的映射可查看。 |
| KNIME Metanode／Component | Metanode 主要组织流程；Component 进一步提供可配置界面、复合视图和复用。外部连线决定输入输出端口，Component 的变量跨边界需明确配置。[官方 Components Guide](https://docs.knime.com/ap/latest/analytics_platform_components_guide/#components-vs-metanodes) | 先解决默认示例的阶段阅读，再决定哪些组值得做成可复用组件；不要因“分组”顺带引入一套新执行语义。 |

KNIME 还通过 Configuration nodes 暴露必要设置，使用户不必进入内部逐个配置节点；可借鉴“组外常用参数”这一操作模式，无需照搬其变量系统。[官方配置说明](https://docs.knime.com/ap/latest/analytics_platform_components_guide/#custom-components-configuration-dialogs)

## 确定的五阶段分组

当前[默认示例文件](../../examples/v2/webui-3gb1.example.json)含 36 个节点、61 条边，按接线顺序组织为五个阶段组与一个普通导出节点。这里记录的是实际拓扑与现有节点名称，不从名称推断新的科学含义。

| 阶段名称 | 节点数 | 已核对的阶段边界 |
|---|---:|---|
| 模板 → Prompt | 4 | 来源节点到 Prompt |
| 生成候选与初筛 | 7 | `generate-paired` 及初筛，7→4 |
| 首轮折叠与筛选 | 11 | `fold-stage-one`、置信度／对齐／TM 相关处理及筛选，4→2 |
| 设计序列 | 2 | `axes-top-two`、`design-children` |
| 末轮折叠与筛选 | 11 | `fold-final` 及末轮评估、排序、取 3 |
| 导出 | 1 | `export-final` |

顶层五个阶段组与导出节点按上述顺序排成单行。初始缩放为 100%，通过阶段导航或水平平移阅读后续阶段；适合视图是用户主动查看总览的动作，不在打开或返回时自动把长流程缩成不可读的缩略图。组内继续按实际依赖排列节点，进入和返回保留各层视图。两轮验证各自保留独立位置，避免按功能归类掩盖执行先后。

按上述五组加导出统计，折叠后仍有 **14 条跨阶段连接**：模板→生成 1、生成→首轮 5、首轮→设计 1、设计→末轮 4、首轮→末轮 2、末轮→导出 1。61 条边中的内部边进入组内，不等于删除；不能宣传为只有 5 条流水线连线。原端口应保持可检查，布局可区分主流程与参考连线，不另造数据束。统计来源同上默认示例。

## 组接口与跨阶段引用

以下为当前实现的展示边界：

- **从现有跨边界连接生成接口。** 输入输出各自对应实际内部节点与端口，可改显示名和顺序，但不合并不同科学值或凭阶段名制造总输入／总输出。组内可点击接口追到具体节点。
- **保留跨阶段引用。** 如果后段还需要模板、早期候选或证据，直接显示源组到使用组的具名连线；不要为了画成单链，让无关中间组假装产出或转发它。常规阅读突出主流程，检查接口时能查全所有跨组连接。借鉴依据是 Blender 显式 Group Input／Output 及 KNIME 明确的边界接口，而非隐式全局变量。
- **只暴露已有常用参数。** 按下表将实际字段或编辑入口映射到组卡片；参数保留单位、原值和内部定位，其余折叠或进入组编辑。不能因分组自动创造统一 seed、统一模型或统一筛选阈值。[Blender 接口配置](https://docs.blender.org/manual/en/4.5/interface/controls/nodes/groups.html#group-sockets)、[KNIME 配置入口](https://docs.knime.com/ap/latest/analytics_platform_components_guide/#custom-components-configuration-dialogs)提供的是交互参考。
- **展示折叠与执行含义分开。** 组沿用现有画布组织和独立复制行为，实际节点、连线及执行语义不变，不复制 Blender 的共享 datablock 或 KNIME 的执行重置规则。

## 常用参数与编辑入口映射

每个控件直接定位一个已有节点字段或已有编辑器，不存第二份参数值。具体字段见[默认示例展示配置](../../webui/src/default-example-canvas.ts)。

| 阶段 | 卡片上可操作的映射 |
|---|---|
| 模板 → Prompt | 打开 `prompt-composition-webui-3gb1.source.author` 的 Prompt 编辑器。 |
| 生成候选与初筛 | `generate-paired.num_samples`、`take-top-four.k`。 |
| 首轮折叠与筛选 | `take-top-two.k`；打开 `rank-stage-one` 的 Selection 编辑器。 |
| 设计序列 | `design-children.num_sequences`。 |
| 末轮折叠与筛选 | `take-top-three.k`；打开 `rank-final` 的 Selection 编辑器。 |

默认分组仅用于当前不可变 3GB1 示例的展示预设。浏览和进入组不复制项目；首次编辑沿用示例到个人项目的复制流程，并一并保存当时的组、位置、视图和参数映射 UI，使副本保留正在使用的展示。既有个人副本不迁移、不自动重排。

结构变换的流畅实时预览优化挂起，不属于本轮分组工作；仍采用现有 90 ms debounce、后端预览与 PDB 重载路径，未更换 renderer。本轮远端验证结果见[交互约定验收记录](../2026-09-29-frontend-interaction-contract.md#验收状态)。
