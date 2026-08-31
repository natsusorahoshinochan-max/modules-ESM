# PROTOTYPE 4 — Import、correspondence 与 merge（一次性原型）

> 当前原型直接对齐 Prompt Authoring contract。它是轻量、内存态、无后端连接的交互 stub；`?variant=` 仍可切换 A/B/C，方案 B「证据分屏」仍是已采用方向。

## 已采用的界面方向

方案 B 保留三栏证据结构：

- 左栏放 source / target 的可见 chain + residue locator 证据；
- 中栏放完整 correspondence editor，逐行列出 `match`、`source_gap`、`target_gap`；
- 右栏放五个 track decision、Preview 和全部 diagnostics。

方案 A「对应账本」和方案 C「关卡式确认」只保留为同一状态模型的布局对照，不是新的产品版本。

## 本次契约对齐

- Open 只记录来源事实。初始与 Reset correspondence 都是明确标注 provenance 的 `prototype stub · chain + residue locator pairing` temporary suggestion；它仍未确认，且不能直接 Apply。
- UI 只显示 `source/target + chain + residue` locator。内部 opaque handles 只用于原型内存状态，不作为字段、轨道或编辑控件出现。
- correspondence 始终完整：每个 source residue 恰好出现在一个 `match` 或 `source_gap` row；每个 target residue 恰好出现在一个 `match` 或 `target_gap` row。`target_gap` 保留现有 target track values，source 在该 locator 不贡献值。把 source 改到已占用 target 时，被替换的 source 自动成为 `source_gap`，因此不会制造重复 target。
- 五个 track 都有显式 state：`sequence`、`structure`、`secondary_structure`、`sasa`、`function_annotations`。只有 `adopt` 或 `preserve` 能成为 materialized track decision；`conflict` 只是未裁决 evidence state，始终 blocking。Conflict 卡只能把整个 track 收敛为 `all adopt` 或 `all preserve`，不能逐 locator 混合 Apply。
- Function annotation 的 exact tuple 固定为 `(label, start residue, end residue)`；evidence 独立显示为 provenance，不是 tuple 成员。Source interval 必须按 correspondence 原顺序完整映射到同链、连续且顺序一致的 target interval，否则 Preview 返回可定位的 blocking `annotation loss`。
- Preview 与 Apply 分离。未确认 correspondence 也可以生成 Preview，并在同一 diagnostics 集合中返回 blocking `correspondence_unconfirmed`。Preview 同时列出 missing adopted tracks、annotation loss、track conflicts、`source_gap` 和 `target_gap`；每条 diagnostic 都带可见 locator。Blocking diagnostics 未清除时不能 Apply。

## 运行

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-4-import-merge-alignment/serve.py
```

打开 <http://127.0.0.1:4182/>。方案 B 默认打开。

- `?variant=B` — **已采用：证据分屏**。
- `?variant=A` — 对应账本布局对照。
- `?variant=C` — Open → correspondence → track decisions → Preview / Apply 关卡布局对照。

所有状态只存在内存，刷新即重置。A/B/C 的底部箭头和键盘左右键会更新可分享的 `?variant=` 参数；输入控件聚焦时不会拦截方向键。

## 推荐走查

### Correspondence

1. 初始页面核对顶部 `TEMPORARY SUGGESTION · UNCONFIRMED` 和 suggestion provenance。
2. 查看完整表：locator draft 有 28 个 `match`，target chain A residue 9 与 20 各有一个显式 `target_gap`；28 个 source 与 30 个 target 均各处置一次。
3. 不确认 correspondence，直接点击 `Generate Preview`。确认 Preview 正常生成，并含 blocking `correspondence_unconfirmed`；Apply 仍禁用。
4. 点击 `Regenerate chain + residue locator draft · still unconfirmed` 或 Reset，确认 provenance 保持 locator draft 且状态仍未确认。
5. 在表格中把任一 source 设为 `source_gap`；或将它分配给某个 target gap。观察 coverage invariant 始终显示 source `28/28`、target `30/30` exactly once。
6. 点击 `Confirm correspondence`。任何后续 correspondence edit 都会撤销确认与旧 Preview。

### Track decisions、Preview 与 Apply

1. 默认 Sequence 和 Structure 为 `conflict`。生成 Preview，确认每个 conflict 都是 blocking，且 conflict rows 只有 evidence，没有逐 residue decision 按钮。
2. 用 `all preserve · whole track` 或 `all adopt · whole track` 将 Sequence 和 Structure 收敛为 materialized decisions；把 SASA 改为 `preserve`。Secondary structure 保持 `preserve`，Function annotations 可保持 `adopt`。
3. 确认 correspondence 后再次生成 Preview。五个 track 均为 adopt/preserve，blocking diagnostics 为 0；annotation pending-delete 与 target gaps 仍作为 warning 显示。
4. 点击 `Apply merge`。结果只写入原型内存，不代表正式保存。
5. Annotation failure 路径：Reset 后把 source chain A residue 5 映射到 target chain A residue 10，确认 correspondence，并把所有 conflict tracks 收敛为 adopt/preserve。Preview 必须显示原顺序 target residues `10, 6, 7` 和 blocking `annotation loss`，不能排序成连续区间。

## 原型边界

- chain + residue locator suggestion 只是可见 provenance 的 stub，不定义正式科学算法。
- 示例 source 是 PDB structure 加一条 annotation sidecar tuple；Secondary structure 与 SASA 明确缺失，用于走查 missing adopted track。
- 示例中的 structure values、annotation tuples 和 scientific conflicts 只服务于状态走查，不形成科学定义。
- 不做持久化、错误恢复、生产级校验、provider parsing 或自动修复。
- 目录中的旧 PNG 不再由本文引用；当前契约以可运行的 HTML 原型为准。
