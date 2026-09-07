# PROTOTYPE 3 — 残基操作、后端预览与六态投影（一次性原型）

> 当前文件直接修订既有原型；它仍是一次性产品判断材料，不是生产实现。

## 已采用方向

方案 A「变更账本」仍是采用方向：残基矩阵、联合操作编辑器和整份 preview ledger 同屏。方案 B「前后对照」与方案 C「操作配方」保留在 `?variant=A/B/C` switcher 中，作为原有比较证据。

本次修订只对齐当前 Prompt Authoring contract，不重做已采用的信息架构：

- 界面只显示用户可定位的 chain / position locator；opaque authoring handles 仅在内存中关联点击与 preview，不出现在界面或 state inspector。
- 残基轴与各轨道统一使用 `source`、`current`、`changed`、`cleared`、`inserted`、`pending-delete` 六态。
- 新增与删除以领域操作表达。新增位置的科学身份由 backend preview stub 分配，界面不构造或编辑内部身份。
- Function annotations 没有稳定公共 ID，只按完整 `(label, start, end)` tuple 投影。修改显示为旧 tuple `pending-delete` 与新 tuple `inserted`。
- 随机 Mask 与随机插入都提交 seed、count 和 eligible scope，由 backend preview stub 返回实际位置；换 seed 会重抽，确认使用同一份 preview。
- 每次 preview 一次显示全部可定位 diagnostics 和完整 Prompt summary；error 会阻止确认，warning 不触发自动修复。

## 唯一产品问题

用户能否在应用前，准确复述残基成员与顺序，以及 sequence、coordinates、secondary structure、absolute SASA（Å²）和 function annotation tuples 的全部变化？

## 运行

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-3-residue-operations/serve.py
```

打开 <http://127.0.0.1:4181/?variant=A>。也可以直接双击 `index.html`；点击底部箭头或使用键盘 `←` / `→` 切换 A/B/C。

所有状态只存在内存中，刷新即重置。1CRN sequence 用于真实研究语境；结构几何、function labels、具体 SASA / SS8 / coordinate values 与编辑参数均为示意。

## 建议走查

### 明确选择与六态

1. 选择“不连续 8–12 + 23–25”。
2. 在条件模式中设置 Sequence=`G`、Coordinates=`Mask`、SS8=`H`、SASA=`保留`。
3. 生成 preview：核对逐轨道 `changed` / `cleared` / `current`，并确认残基成员与顺序不变。
4. 应用后撤销，确认整次编辑一起恢复。

### 新增与删除

1. 在成员模式选择一个 chain / position locator 后新增两个残基。
2. 核对 backend preview stub 返回的实际插入位置；Sequence 必须明确选择指定或 Mask，其余轨道逐项列出。
3. 预览删除不连续选择：删除 exact endpoint 时，完整 source tuple 显示 `pending-delete` 并从当前 collection 移除；只删除 interval 内部成员时保留 exact tuple，并显示 membership 重对齐后果。
4. 删除本次 session 新增的残基时，它只从 final collection 消失，不显示 source `pending-delete` tombstone。

### 随机 Mask 与随机插入

1. 切换“后端随机操作”，选择随机 Mask，数量 6、链 A / 位置 6–34、seed 1701。
2. 请求 preview，核对实际位置、effective randomness 与唯一被 Mask 的轨道；确认前 Prompt 不变。
3. “换 seed 重抽预览”，核对实际位置变化；确认并应用当前 preview。
4. 改为随机插入，重复 preview → 重抽 → 确认路径，核对新增位置四条轨道的指定 / Mask 状态。
5. 在 preview 矩阵中从临时插入位置 Shift-click 现有残基，应按 projected residue axis 定位且不取消 preview。
6. 取消 preview 应恢复 preview 前的选择与 anchor；随机插入 Apply 后再 Undo，也应恢复同一份 preview 前选择。

### Function tuple correspondence

1. 进入 Function intervals，选择来源 `binding region`、链 A / 位置 12–20，并保持 label 不变后执行“修改”；preview 应显示完整 tuple 未变的 `source / no-op`。
2. 再改变 label 或端点并 preview；此时应同时显示旧完整 tuple `pending-delete` 与新完整 tuple `inserted`，而不是 `changed` 或稳定 annotation ID。
3. 删除一个 source tuple 并应用，再添加完全相同的 tuple；final exact correspondence 应恢复为 `source`，而不是硬编码 `inserted`。
4. 添加、拆分与删除沿用相同 exact correspondence；Function annotations 不提供逐残基 Mask。

### 一次返回全部 diagnostics

1. 在条件模式把 Sequence 指定值改为 `GG`，同时把 SASA 指定为负数。
2. 生成一次 preview；账本同时显示两条可定位 error diagnostics，并阻止确认。
3. 点击 diagnostic 定位操作对象，修正值后重新 preview。

## 原型边界

- 这是轻量 backend preview stub，不实现网络、持久化、生产错误恢复或第二套正式 sampling 语义。
- 三维导航的显示 / 隐藏不属于 Prompt 编辑；Coordinates 的 Mask 才会清除结构 conditioning。
- 缺失轨道值是合法状态，不被原型猜测或自动补齐。
- 最终颜色、图标、function vocabulary 和科学默认值仍未裁决。
