# PROTOTYPE 3 — 残基操作、预览与变化状态（一次性原型）

> 在继承原型 2 已采用的“残基账本 / 共享轴优先”层级下，用 `?variant=` 切换三种变更预览语言。

## 决定 — 2026-08-30 采用方案 A

**原型 3 采用方案 A「变更账本」作为后续正式界面设计的残基变更预览方向。** 当前残基矩阵、联合操作编辑器和逐轨道 transaction ledger 同屏；预览逐项列出 ResidueLayout 与各轨道的保留、指定、Mask、新增或删除，再由用户统一确认或取消。

方案 B「前后对照」与方案 C「操作配方」只作为一次性比较证据保留，不再是同等候选。本决定只裁决残基操作的预览信息结构，不把原型代码提升为生产实现，也不裁决最终视觉样式、function interval 端点失效处理或来源参考几何的视觉地位。

## 唯一产品问题

用户能否在应用前，准确复述将发生的残基布局变化，以及 sequence、coordinates、secondary structure、absolute SASA（Å²）和 function annotation intervals 各自会发生什么变化？

本原型对应 `docs/2026-08-29-webui-functional-spec.md` 第 3.6–3.9、3.12 节。它不重新裁决原型 2 的整体信息架构，也不验证导入对齐、残基级结构变换、provider 协议或生产实现。

## 运行

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-3-residue-operations/serve.py
```

打开 <http://127.0.0.1:4181/?variant=A>。

也可以直接双击本目录的 `index.html`。文件直开模式会加载普通延迟脚本，并显示同一个浮动切换器；点击箭头或按键盘 `←` / `→` 会在 `?variant=A/B/C` 之间切换。

- `A` — **已采用。变更账本**：当前矩阵 + 右侧编辑器 + 逐轨道 transaction ledger。
- `B` — 仅供比较。**前后对照**：当前态与拟应用态同轴并列。
- `C` — 仅供比较。**操作配方**：先组成一条可朗读的操作配方，再用确认清单核对。

所有状态只存在内存中，刷新即重置。1CRN 序列身份是真实研究语境；结构几何、function labels、具体 SASA / SS8 / coordinate values 与操作参数均标注为示意，不形成产品或科学决定。

## 走查路径

正常路径：

1. 用“明确选择”选择 `A:8–12 + A:23–25`。
2. 在条件模式中同时把 Sequence 指定为 `G`、Coordinates 设为 Mask、SS8 指定为 `H`、SASA 设为保留。
3. 生成预览，先在矩阵和逐轨道摘要中核对，再一次应用；用撤销回到应用前。
4. 进入 Function intervals，依次预览并应用添加、修改、拆分、删除。

容易误解的路径：

1. 使用“可复现随机选择”：数量 6、允许范围 A:6–34、种子 1701。
2. 核对实际位置、数量、范围与种子同时出现在选择区、结构导航和矩阵中；换种子后实际位置变化但 Prompt 不变。
3. 预览删除，确认它改变 ResidueLayout 并会移除所有轨道值、影响 function intervals。
4. 取消预览，确认 Prompt 未变化；再预览仅 Mask Coordinates，确认 residue identities 与其他轨道被保留。

## 原型边界

- 残基操作只接受：`保留`、`指定`、`Mask`、`新增（指定 / Mask）`、`删除`。不提供“恢复来源值”操作。
- Function annotations 始终按 interval 添加、修改、拆分或删除，不把它们伪装为可逐残基 Mask 的 scalar track。
- 三维导航中的显示/隐藏不属于本原型操作；Coordinates 的 Mask 才会清除结构 conditioning。
- 新增 residue identity 使用 `A:newN` 这样的原型占位身份，不裁决正式重编号规则。
- 最终颜色、图标、function vocabulary、科学默认值与兼容性文案仍未裁决。

## 走查记录

浏览器走查完成于 2026-08-29：

- 默认不连续选择 `A:8–12 + A:23–25` 同时出现在选择区、结构导航和矩阵。联合条件预览准确列出：Sequence 7 个值改为 G、Coordinates 8 个值变为 Mask、SS8 6 个值改为 H、SASA 8 个值明确保留；ResidueLayout 保留 47，实际会改变 21 个逐轨道值。
- 应用上述联合编辑后 Coordinates 已指定数从 45 降到 37；一次撤销回到 45。预览取消不改变 Prompt。
- 2026-08-29 用户校正了残基操作模型：删除原型中的“恢复来源值”，统一采用 `保留、指定、Mask、新增（指定 / Mask）、删除`。保留是逐轨道明确 no-op；撤销仍是整体编辑历史操作，不属于残基操作类型。
- 数量 6、范围 `A:6–34`、种子 1701 抽得 `A:14, A:24, A:25, A:30, A:32, A:33`；种子加一后改为 `A:7, A:14, A:18, A:19, A:25, A:30`。两次抽取都没有改变 Prompt，各实际位置同时高亮在矩阵与结构导航。
- 删除预览把 6 个 residue identities 标成待删除，显示布局 `47 → 41`、四条逐残基轨道各丢失 6 个已指定值、2 条 function intervals 受影响；取消后仍为 47 residues。
- 在 `A:16` 后新增 2 个残基的预览显示布局 `47 → 49`、2 个新 residue identities、8 个新增轨道位置；新增 Sequence 可明确选择指定或 Mask。应用后四条轨道计数同步更新，撤销回到 47 residues。
- Function interval 的添加应用后数量 `3 → 4`，撤销回到 3；修改、拆分与删除都产生同一套未应用预览语言。删除预览把 interval ribbon 标为待删除，同时明确 ResidueLayout 与四条逐残基轨道保留当前值。
- 原型 2 样本中既有 `A:new1` 位于 A:18 与 A:19 之间。第一次走查发现“连续 A:12–20”预设漏选新增身份；现已改为按当前 ResidueLayout 的端点选取，得到包含 `A:new1` 的连续 10-residue 区间。
- 已 Mask Coordinates 的残基现在以空心来源参考点留在结构导航，并明确标记其不再是结构 conditioning；这使随机选择的实际位置不会在三维区悄然消失。
- A 的变更账本、B 的同轴前后对照、C 的可朗读操作配方均保留同一 Prompt 与选择状态。C 在逐项勾选前禁止应用，勾选完成后允许应用；Function 删除后数量 `3 → 2`，撤销回到 3。
- URL `?variant=A/B/C`、浮动箭头和键盘左右键均可切换方案。最终浏览器 console 无错误。

截图：

- `variant-a-initial.png` — 变更账本方案的初始状态与五种变化标记。
- `variant-a-multitrack-preview.png` — 8-residue、多轨道联合预览；21 个值变化，布局不变。
- `variant-b-function-delete-compare.png` — Function interval 删除的当前态 / 拟应用态同轴对照。
- `variant-c-function-delete-recipe.png` — Function interval 删除的可朗读操作配方与确认清单。

## 采用后的观察与仍待裁决

- 用户已选择变更账本，因为它在矩阵优先结构中最紧凑地逐轨道列出 `保留 / 指定 / Mask` 与布局上的 `新增 / 删除`。B、C 不再参与整体方案选择。
- 功能规格尚未决定：删除残基使 function interval 端点失效时，应在确认删除前强制用户处理、允许暂时形成不可保存状态，还是执行某个明确的 interval 变换。原型采用最保守的表达：不自动修复，预览失效端点并让保存继续受格式检查约束；这只是为了暴露分歧，不是产品决定。
- 已 Mask Coordinates 是否应继续以“来源参考几何”显示，以及来源参考几何的视觉地位，仍需与三维选择心智模型一起验证。

## 功能规格影响

方案 A 的采用决定已经回写权威功能规格。若用户裁决上述 function interval 端点处理方式，应继续回写第 3.7、3.9 或 3.12 节；预览方案的选择不改变 `ProteinPrompt` 科学语义。

## 文件直开修复 — 2026-08-30

文件直开时无法切换方案的原因有两个：`index.html` 使用了可能被 `file://` 安全策略拒绝的模块脚本，同时原型控制条只允许 `localhost` 与 `127.0.0.1`。现在脚本使用普通 `defer` 加载，并将 `file:` 明确视为原型环境。源代码反馈环验证文件直开的两个必要条件；HTTP 浏览器走查验证点击切换器 A→B、键盘 B→C、URL 参数同步且 console 无错误。
