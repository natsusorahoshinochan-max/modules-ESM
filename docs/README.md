# 项目文档

[当前有效决策](documentation-governance-decisions.md)规定已确认的产品要求与开发边界。各领域说明分别标明现有机制和未实现要求；[问题清单](2026-10-15-documentation-governance-issues.md)仅维护当前未解决的实现差异与待核实事实，不以旧验收或旧设计作为现行权威。

## 使用与开发入口

| 阅读目的 | 文档 |
|---|---|
| 安装、启动与部署当前应用 | [WebUI 使用说明](../webui/README.md)、[Provider 配置](provider-configuration.md) |
| 理解术语和载体、模块、工具的职责 | [领域词汇](../GLOSSARY.md)、[架构](architecture.md) |
| 了解运行、缓存、发布和失败处理 | [执行](execution.md) |
| 项目、画布、手动保存和教学实例 | [工作区](workspace.md) |
| 导入、历史结果复用、查看、筛选与导出 | [结果与数据](results.md) |
| 序列、轨道、区域、随机插入和结构编辑 | [Prompt 编辑](prompt-editing.md) |
| 模块 React 编辑器接入与打包 | [模块 UI 契约](module-ui.md) |
| 功能模块职责与当前工具调用能力 | [模块能力](module-capabilities.md) |
| 官方 Biohub 请求与项目适配范围 | [Biohub 资料入口](biohub-api-reference/README.md) |
| 核对当前参数开放差异 | [参数审查](tool-parameter-exposure-audit.md) |
| 测试职责、共享支持与当前覆盖边界 | [测试组件](testing.md) |
| 贡献者执行验证 | [后端验证](backend-verification.md)、[WebUI 验证](../webui/README.md#verification) |
| 查看随包示例的当前用途 | [示例说明](../examples/v2/README.md) |
| 查阅第三方技术与专利研究 | [研究资料](research/README.md) |

## 文档边界

文档和注释只描述当前有效内容，区分已确认要求、实现事实和未解决差异。事实依据采用当前源代码、固定上游接口与明确来源；研究候选不自动成为需求，历史通过不证明当前代码已验证。

项目用户通过模块和节点组合操作。模块开发者负责工具调用、参数转换及内部对应；载体提供通用管理、执行和数据传递。现行职责不按模型名称或已有包数量划定。

文档更新直接替换失效内容，不保留 AI 对话、任务流水、失效方案或旧验收档案。原始研究数据、用户项目和运行结果不属于旧文档清理对象。固定上游文档保留其来源身份，不作为 Workbench 全部能力的承诺。
