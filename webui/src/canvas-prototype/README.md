# 画布工作台设计参考

A 全画布交互已接入正式工作台。按[启动说明](../../../README.md#启动)启动后端和前端，直接打开前端地址。节点目录、参数、输入输出与运行状态来自真实模块声明，行为要求见[画布工作台交互](../../../docs/requirements.md#画布工作台交互)。

正式画布实现位于 [WorkflowCanvas.tsx](../WorkflowCanvas.tsx)。节点属性原位展开，节点库按需打开；拖动圆点接线，空格拖动平移，F 聚焦选中、Shift F 适应全图。Protein Studio 从模块声明的工作区入口展开，完成或取消后返回原画布。

原型参考快照可在分支 `codex/prototype-canvas-stage1` 的提交 `097adafe` 查看。截图与交互参考位于：

`/Users/sorachan/.codex/visualizations/2026/10/23/01a16826-9640-7741-ac5c-76e864a8cf94/canvas-prototype/revision-a/`
