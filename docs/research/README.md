# 技术与专利研究参考

研究材料用于查阅第三方实现、公开技术及其来源，不定义项目要求或证明本项目已验收。目标行为以[当前有效决策](../documentation-governance-decisions.md)为准，实现与要求的差异见[问题清单](../2026-10-15-documentation-governance-issues.md)。项目现行说明见[文档索引](../README.md)。

## 前端技术参考

下列参考保留 2026-10-03 核查的固定上游源码、调用链及边界。它们不是推荐部署版本，静态源码阅读不代表运行、性能或用户体验验证。

| 查阅目的 | 参考 | 主要事实 |
|---|---|---|
| 多轨条件编辑与生成调用 | [Biohub/esm](frontend-reference-esm.md) | 来源片段、轨道编译、本地与远端能力、配置修改及结果采用 |
| 结构、选择与场景状态 | [Mol* / MolViewSpec](frontend-reference-molstar.md) | 数据与表示、选择身份、更新、保存和释放 |
| 流程、调用与计算任务 | [Galaxy](frontend-reference-galaxy.md) | Workflow、Invocation、Job、结果、状态查询与取消 |
| 节点生命周期与界面同步 | [KNIME](frontend-reference-knime.md) | 输入规格、实际执行、命令回执、版本投影及执行策略 |
| 编辑图到执行请求 | [ComfyUI](frontend-reference-comfyui.md) | 节点注册、转换、运行事件、本地历史和缓存寿命 |
| 多视图协调与数据加载 | [Vitessce](frontend-reference-vitessce.md) | scope、数据源、Loader、配置保存与取消链 |

参考上游时，应分别核对功能行为、数据含义、调用顺序和复用许可。参考其交互模式不等于采用整个框架，源码许可也不自动覆盖模型权重、托管服务、图标或文档。

## 专利研究

以下材料保留 2026-10-13 检索范围、原始出处、公开日期和未核实事项。它们不提供授权或自由实施结论；法律状态及后续网页变化未在文档治理中重新核验。

| 查阅目的 | 材料 |
|---|---|
| 研究结论与公开证据 | [检索总览](2026-10-13-patent-search-summary.md) |
| 本项目目标、实现事实与缺口 | [项目技术事实](2026-10-13-patent-project-evidence.md) |
| 整体软件交底的组织方式 | [撰写分析](2026-10-13-patent-drafting-plan.md) |
| 中国大陆申请规则及其原始出处 | [规则研究](2026-10-13-patent-cn-rules.md) |
| 工作流与扩展平台先例 | [工作流公开技术](2026-10-13-patent-workflow-prior-art.md) |
| 蛋白质软件、模型与算法背景 | [蛋白质公开技术](2026-10-13-patent-protein-prior-art.md) |
| 模块、节点与执行链的逐篇比较 | [类似软件专利比较](2026-10-13-patent-similar-software-followup.md) |

项目用户安装、启用和使用模块；模块开发者实现模块及工具调用；本项目的开发者维护载体及公共运行、保存和数据传递机制。当前模块管理、专用界面与运行配置的实现说明分别见[工作区](../workspace.md)、[模块 UI](../module-ui.md)和[Provider 配置](../provider-configuration.md)。交底应区分这些角色，以及载体能力、模块功能和上游工具能力，不把已有实现当作全部要求已完成的证明。
