# 整体可扩展蛋白质设计软件：项目技术事实

本文件为技术交底提供项目自身的要求、实现位置及缺证范围。项目行为以[当前有效决策](../documentation-governance-decisions.md)为准，术语见 [CONTEXT.md](../../CONTEXT.md)。现有代码只证明实现机制，不证明符合全部要求或通过运行验证。

本地实现定位对应源码基线 `7577542009ad1f1b5ae0c2a7b9c69c6a881f9410`。源码阅读不能证明首次公开时间、原创贡献、专利区别或法律效力。外部公开证据及其日期见[检索总览](2026-10-13-patent-search-summary.md)。

## 整体对象与角色

技术交底对象是支持模块扩展、节点编排、运行和结果使用的蛋白质设计软件整体。载体提供通用管理、编排、运行和保存；功能模块提供具体操作及其界面；ESM、SimpleFold、ProteinMPNN 等是模块内部调用的工具，不是载体自身发明的模型算法。

模块开发者定义节点、参数、输入输出、执行实现或 Adapter。项目用户安装并启用模块，从节点库选择功能、设置参数和连线，构建自己的流程。使用者无需编写装配代码或维护内部残基标识。两种角色可由同一人承担，但其责任不同。

本项目科学正确性的尺度是正确传入用户指定的数据与参数、按工具官方接口进行转换并接回所需结果。已有类型、来源和运行记录用于说明实现，不构成新增科学验证或证据体系的要求。

## 模块接入：要求与实现边界

| 项目 | 当前要求 | 可核查的实现与差异 |
|---|---|---|
| 安装与管理 | 用户选择插件包后安装并启用，可以禁用、卸载；官方模块默认附带并启用 | [bootstrap](../../protein_workbench_public/bootstrap.py) 显式导入模块并构造注册列表；此路径不是用户插件管理功能的完成证明 |
| 注册模型 | 模块按统一契约接入节点、数据和专用界面；官方与外部模块同等接入 | [ModulePackageRegistration](../../core/catalog/declarations.py) 聚合节点、Method、Binding、数据类型、Metric、Utility 和编辑能力；[Builder](../../core/catalog/builder.py) 构造冻结目录 |
| 专用界面 | React 接口；同一数据可有多个查看器并由用户切换 | [App](../../webui/src/App.tsx) 和[后端结果读取](../../protein_workbench_public/http/run_routes.py) 仍有固定分派，完整外部接入待修正 |
| 运行配置 | 模块声明配置项，应用内提供凭据、后端模型位置及服务地址等设置 | [Environment](../../core/execution/environment.py) 按 Binding 声明接纳配置；[Provider 配置](../../protein_workbench_public/provider_environment.py) 主要从环境变量构造运行环境，不能描述为已有完整应用内设置 |
| 空载体 | 无科学模块时仍可创建、打开、保存项目并管理模块 | 固定生产装配不能单独证明空载体独立使用已经满足 |
| 参数开放 | 已提供功能适用且影响结果的官方输入参数可配置 | 现有差异见[参数开放审查](../tool-parameter-exposure-audit.md)；不是新增工具模式的授权 |

当前固定目录和公共协议是实现事实。不能把它们说成已完成安装管理，也不能把它们当作取消上述要求的理由。公开 Catalog 读取接口不等于模块注册或设置界面。

## 已有编排与执行机制

| 环节 | 源码所体现的机制 | 定位 |
|---|---|---|
| 节点定义与实现 | Node Type 声明操作及端口；Method 表达算法或模型身份；Binding 关联执行实现、Adapter 与配置 | [注册声明](../../core/catalog/declarations.py)、[ESM3 注册](../../modules/esm3/package.py)、[folding 注册](../../modules/folding/package.py) |
| 图编辑 | 添加节点、参数设置、端口连接、重连、分组和图层导航 | [前端图编辑](../../webui/src/workflow-authoring.ts)、[App](../../webui/src/App.tsx)、[工作区说明](../workspace.md) |
| 图解释 | 检查端口名义类型、数量、必需输入、Binding 归属和无环依赖，解析参数、实现与输入顺序 | [图准入](../../core/workflow/_compiler/graph.py)、[Compiler](../../core/workflow/compiler.py) |
| 流程发布 | 从已解析计划提取所用定义，保存不可变 Workflow Commit；运行时按当前目录解析 | [流程 owner](../../core/workflow/authoring.py)、[计划](../../core/workflow/plan.py) |
| 执行与复用 | 结果身份用于核对复用；缓存命中与实际工具进入有不同记录；输出与节点终态通过耐久发布保存 | [Node Attempt](../../core/execution/node_attempt.py)、[结果身份](../../core/execution/_node_attempt_identity.py)、[发布](../../core/execution/_node_attempt_publication.py)、[Ledger](../../core/execution/ledger/ledger.py) |
| 范围执行 | 指定来源 Run，按当前结果身份复用已发布节点结果并执行请求范围 | [范围处理](../../core/execution/_run_runtime_scope.py)、[运行说明](../execution.md) |

上述源码定位不是当前 HEAD 的验收报告。节点级复用和重跑不等同于已满足“保留批内成功结果、跳过成功请求主动续算”。已有运行记录也不等同于已提供历史列表、跨项目采用或完整结果导出。

## 蛋白质数据处理的已有实现

### 条件编辑与工具输入

[ResidueLayout](../../datatypes/residue.py) 使用有序、唯一、带链的残基身份；[Prompt](../../datatypes/prompt.py) 表达条件轨道。[recipe](../../modules/prompt_authoring/recipe.py) 处理来源/目标对应、插入、区域与轨道采用，以及 Function 区间映射。[编辑说明](../prompt-editing.md) 描述当前要求和实现边界。

[ESM3 Adapter](../../modules/esm3/adapter.py) 生成工具条件投影、输入编码及适用的随机控制。本地与远端能力不能混同：远端标记 `provider_uncontrolled` 时，不能声称用户 seed 已传给服务。当前 SDK 对多链条件的表示限制也不能被扩写成载体限制。

内部 recipe 的 `match/source_gap/target_gap/insert` 及 identity 维护是实现细节，不能在交底中变成项目用户必须管理的责任。

### 候选、结构与评价对象

候选引用使用身份、名义数据类型和内容摘要，避免独立集合重排后按下标误配。[预测值](../../datatypes/prediction.py) 区分预测时残基轴、Prediction Key 与置信度 fact；[结构轴](../../datatypes/structure.py)、[候选轴关联](../../modules/structure_transform/candidate_axes.py) 和[置信度物化](../../modules/structure_prediction/implementation.py) 负责相应数据关系。

[结构比较](../../modules/structure_comparison/implementation.py) 根据显式 subject/reference 配对，生成对齐及 RMSD、TM-score 等结果；[指标投影](../../modules/structure_comparison/metrics.py) 与[方法声明](../../modules/structure_comparison/definitions/methods.yaml) 描述已有含义。BLOSUM62、SVD、TM-align 等既有算法不是本项目原创的证明。

评价关系与生成来源必须分开。ProteinMPNN 评分的唯一原始父结构限制是已确认缺陷；整个 ProteinMPNN 接入需重做。不得将当前限制写成所有候选评价的必需条件，也不得伪造来源关系以满足旧实现。

### 指标与筛选

[Selection 编译](../../core/workflow/_compiler/selection.py) 和[求值](../../core/scoring/selection.py) 体现 Metric、Method、Context、候选引用及显式 Utility 的既有处理。相关说明见[结果与筛选](../results.md)。这些机制不能证明生物实验表现提高，也不能自动决定未来所有模块必须使用同样内部表示。

缺少必需分数时默认停止对应筛选。用户可通过画布组合整批或分组范围的筛选与排序；不能因现有示例给出固定 Top-N，就将该规则变成载体限制。结果页“保存为流程”已决定删除，当前代码仍待移除，不作为未来实施例的要求。

## 可使用的实例与缺证

[示例目录](../../examples/v2/README.md)、[canonical 3GB1 流程](../../examples/v2/canonical-3gb1.workflow.json) 及 1PGA、2EMO、5G53 的实际 JSON 可用来定位现有节点、参数与连接。实例定义不等于已完成运行，也不代表其中的旧 ProteinMPNN 接口是后续设计基线。

技术交底尚需以下事实材料：

- 一个符合当前接入要求的自定义模块完整实例，含模块源码、注册与安装、专用界面、配置、节点连接及实际结果；现有固定装配实例不能替代。
- 固定版本的完整运行输入、参数、输出及可读说明。真实工具接受了哪些输入、哪些参数，应按官方接口和实际调用说明；不补造未记录的信息。
- 若主张效率、正确性或其他技术效果，提供对应错误类别、比较条件和数据。测试数量、类名或目录数量不能代替效果证据。
- 各拟保护机制的公开内容、公众可访问日期、自然人贡献和相关申请材料。本地 commit 日期不能证明公众当时已经能够取得内容。

上述材料缺口只限定研究可作出的结论，不授权新增功能或扩大验证体系。可执行验证遵守[远端验证政策](../backend-verification.md#execution-policy)。
