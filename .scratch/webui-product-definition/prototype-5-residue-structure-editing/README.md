# PROTOTYPE 5 — 残基选区的精确刚体编辑（一次性原型）

> 单文件逻辑原型，用于验证 Prompt Studio 结构 authoring 的选区边界和精确变换意图。

## 唯一产品问题

当结构编辑只作用于当前明确选中的 residue 集合时，研究人员能否确认一个精确刚体 translation / rotation，并看到未选 residue 始终不变？

原型对齐：

- `docs/2026-08-29-webui-functional-spec.md` 第 3.11 节；
- `docs/2026-08-31-prompt-authoring-layer-and-parameter-ownership-spec.md` 第 7.1–7.2 节。

它不裁决正式结构边界科学检查、自动优化算法、最终视觉或生产架构。

## 当前结论

**已按 current authoring contract 修订，2026-08-31。**

原型只保留如下结构编辑合同：

- 当前明确 selection 是唯一受变换的 residue 集合；
- 连续或不连续 selection 共享一个 exact rigid transform；
- X/Y/Z 只使用本原型的示意工作坐标；坐标框架仍未裁决，不构成产品合同；
- public authoring intent 只表达 `residue_handles`、`origin`、`translation` 和 `rotation_matrix`；
- 人可读位置用 chain/residue locator 显示，opaque handle 值不在 UI 中展开；
- 未选 residue 坐标最大变化始终是 `0 Å`。

## 运行

直接双击 `index.html`，或运行：

    .venv/bin/python .scratch/webui-product-definition/prototype-5-residue-structure-editing/serve.py

打开 <http://127.0.0.1:4183/>。所有状态只存在内存中，刷新即重置。

1CRN chain A sequence 提供真实蛋白质研究语境；视口坐标和边界均是明确标注的交互示意，不形成科学判断或产品默认值。

## 操作模型

- 空闲时左键选择 residue；拖拽框选；Shift 选择连续区间；Ctrl/Cmd 追加或切换不连续位置。
- 中键拖拽旋转视角，Shift + 中键平移，滚轮缩放。视角操作不改变 selection、坐标或历史。
- 默认 Perspective。小键盘数字 5 和顶部按钮在 Perspective / Orthographic 之间切换。
- 视口示意网格固定在本原型工作坐标 `Z=0` 的 XY 平面，与结构使用同一相机投影。
- 选择后按 G 或 R 进入鼠标模态预览。X/Y/Z 对本轮示意工作轴施加约束，仅用于验证交互。
- 数值键可精确覆盖当前鼠标量值，但不是开始变换的前提。
- 选中的所有 residue 共享一个 `origin`、`translation` 和 `rotation_matrix`；选区内部相对几何保持不变。
- 视口左键或 Enter 确认；右键或 Esc 取消；Ctrl/Cmd+Z 撤销。
- S 缩放和单原子选择被明确拒绝，不创建 authoring intent。
- 可见按钮与快捷键进入同一状态机。

## Public authoring intent

右侧状态面板在预览和最近一次确认后显示：

- `residue_handles`: 由模拟 authoring snapshot 提供，UI 只显示数量，不显示值；
- `origin`: 选区共享的精确旋转原点；
- `translation`: 精确三维位移向量；
- `rotation_matrix`: 精确 `3×3` 旋转矩阵。

鼠标事件、快捷键、hover、高亮、面板布局和 undo history 仍是 frontend-owned UI state，不写入 authoring intent。示意坐标只用于视口渲染；原子坐标展开由后端维护。

## 引导走查

页面底部提供五个 walkthrough tabs：

1. 投影：切换 Perspective / Orthographic，确认视图变化不改动 selection、坐标或历史。
2. 精确移动：对 A:15 V 执行 G+X 和精确 `+2.5 Å`，同时核对坐标框架未裁决的标记。
3. 不连续刚体：对 A:8–10 + A:23 + A:31‑33 执行 R+Z 和精确 `+15°`。
4. 未选不变：核对预览与确认记录的未选坐标最大变化都为 `0 Å`。
5. 取消与禁止：确认取消不提交，S 和单原子选择不创建状态。

## 原型边界

- 黄色虚线只显示选中/未选的链内相邻关系，不是正式结构合理性判定。
- 选区内部距离误差和未选坐标最大变化是交互证据，不代替正式科学检查。
- “保存 ProteinPrompt”只模拟明确保存边界，不写回 Workflow 或持久化存储。
