# PROTOTYPE 8 — 项目、自动保存与命名版本（一次性原型）

> 三种项目信息结构在同一页面中用 `?variant=` 切换；原型只回答当前项目身份、保存边界，以及复制、版本分支与恢复所得对象是否清楚。

## 唯一产品问题

研究人员是否始终知道自己正在编辑哪个项目、哪些内容已经保存，以及复制、从旧命名版本继续修改和从“最近删除”恢复分别会得到什么？

本原型对应 `docs/2026-08-29-webui-functional-spec.md` 第 1.1–1.2 节与第 6 节，并把第 3.12 节 Prompt Studio 的明确保存边界放入同一旅程中验证。保存模拟同时对齐 `docs/2026-08-31-prompt-authoring-layer-and-parameter-ownership-spec.md`：编辑使用 `open → preview → apply`，确认后的 `apply intent=replace` 在当前 Project 的最新 Workflow Draft 上工作。它不决定默认示例的具体 PDB、预生成结果、科学参数、个人项目默认排序、最终颜色、图标或生产持久化实现。

## 运行

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-8-project-versioning/serve.py
```

打开 <http://127.0.0.1:4186/?variant=A>。

- `A` — **上下文画布**：项目身份、自动保存和版本来源持续伴随 Workflow；项目库按需从左侧打开。
- `B` — **版本时间线**：命名版本、打开前的当前工作和从旧版本分出的当前工作成为主轴，Workflow 退到相邻预览。
- `C` — **实验项目库**：项目搜索与操作、当前 Workflow、保存边界三列常驻，强调对象之间的差别。

所有状态只存在内存中，刷新即重置。示例项目名、PDB、模型、参数、ProteinPrompt 内容与 Run 信息均为示意；原型不写磁盘、不连接真实 Workflow 或 Run，也不决定个人项目默认排序。

## 正常走查路径

1. 从每次启动的干净默认示例开始，点击“修改生成步数（示意）”；核对界面无阻断地创建个人副本，默认示例保持不变，随后显示自动保存中与已保存。
2. 打开“项目”，搜索并打开“抗体 CDR 条件生成”；重命名它并核对当前项目身份与自动保存提示同步更新。
3. 创建命名版本“调整 Prompt 后”，核对版本明确包含 Workflow、参数、ProteinPrompt 和画布布局。
4. 打开 Prompt Studio，模拟编辑 ProteinPrompt；项目自动保存不得声称已保存这份 Studio 草稿。点击“生成保存 Preview”，核对 backend 返回的完整 ProteinPrompt 摘要与全部可定位 diagnostics；此时仍未保存 Draft。点击“确认 Preview 并保存”后，模拟 `apply intent=replace` 写回当前 Project 的最新 Workflow Draft，并触发项目当前工作的自动保存。
5. 打开较早命名版本“第一次生成参数”，再修改 Workflow；核对旧命名版本和打开旧版本前的当前工作都保留，当前工作明确标记为从旧版本分出。
6. 复制当前项目；先核对复制摘要，再确认新项目只包含当前 Workflow、参数、ProteinPrompt 和画布布局，不含命名版本与最近一次 Run / Results，并以尚未运行状态打开。

## 容易误解路径

1. 在 Prompt Studio 有未保存更改时尝试切换项目；原型必须要求“预览并保存 ProteinPrompt / 放弃 / 继续编辑”，不能让项目自动保存暗中吞掉 Studio 草稿。选择保存后仍须核对并确认 backend preview，不能绕过确认直接 apply。
2. 删除当前个人项目；确认摘要必须说明整个项目（含命名版本与最近一次 Run / Results）进入“最近删除”，随后回到干净默认示例。
3. 从“最近删除”恢复项目；项目的命名版本与最近一次 Run / Results 一起恢复，恢复不是复制，也不会产生新的项目身份。

## 原型边界

- 默认示例不可变；第一次 Workflow 修改自动建立个人副本，不弹复制确认。
- 个人项目的当前工作自动保存；命名版本是不可覆盖快照。
- Prompt Studio 的编辑会话不受项目自动保存覆盖；`preview` 只返回 normalized projection、摘要与 diagnostics，不保存 Draft。只有用户确认该 preview 后，`apply intent=replace` 才更新当前 Project 的最新 Workflow Draft。
- 从旧命名版本继续修改时，旧版本和打开前当前工作都保留；原型把这种来源关系显式呈现，但不裁决正式分支命名、排序或长期导航方式。
- 复制产生新项目身份，且明确排除命名版本和 Run / Results。
- 恢复保持原项目身份和项目内容；它不是复制。

## 走查记录

浏览器基础走查完成于 2026-08-30；Prompt authoring 保存路径于 2026-08-31 重新走查：

- 干净默认示例初始身份为 `DEFAULT-ESM3`，重命名、复制、删除和创建命名版本均不可用；首次修改生成步数时无阻断地建立 `PRJ-30` 个人副本。界面先显示“正在自动保存”，随后显示保存时间，并在项目来源中持续声明默认示例保持不变。
- 项目菜单搜索 `CDR` 时只保留“抗体 CDR 条件生成”，同时展示它的两个命名版本；打开、重命名和自动保存后，顶部项目名、稳定项目 ID 与右侧当前对象同步。
- 创建“联合条件复核”命名版本后，项目菜单同时保留三个命名版本；创建摘要明确列出 Workflow、参数、ProteinPrompt 和画布布局，不把 Run / Results 说成版本内容。
- Prompt Studio 草稿修改后，顶部和 Studio 内同时显示“尚未写回 Workflow”；尝试切换项目时出现“预览并保存 ProteinPrompt / 放弃 Studio 草稿 / 继续编辑”三种明确选择。保存路径先显示 backend preview 的 ProteinPrompt summary、diagnostics 和 `intent=replace` 目标，用户确认后才关闭 Studio、更新最新 Workflow Draft revision，并进入项目当前工作的自动保存。Workflow 页脚保留 `confirmed preview / diagnostics / apply replace` 的轻量回执。
- 2026-08-31 的 1280×720 浏览器烟雾走查确认：项目自动保存完成后，未确认的 Studio 草稿仍显示“尚未写回 Workflow”；从 Workflow v4 命名版本打开 Studio 时，确认 apply 后发布的是项目最新 Draft 的下一版 Workflow v9，而不是从 v4 直接写出 v5；timeline 同时保留旧命名版本、打开前的 Workflow v8 current head，并把 v9 来源标记为该命名版本；Studio 与页面均无宽高溢出。
- 根据浏览器批注补齐 Prompt Studio：同一残基选区现在完整显示并可从联合编辑区分别操作 sequence、coordinates、secondary structure、absolute per-residue SASA（Å²）与 function annotations interval collection。`ResidueLayout` 只作为后端内部科学身份轴，不作为前端可见或可编辑的 ProteinPrompt 内容；visibility 也只作为界面状态说明，不冒充 ProteinPrompt 科学内容。
- ESM-3 生成节点现在明确写出“参数摘要（示意）”和“仅作示例；未完整体现可调整参数”；按钮改为“修改示例参数”，不再让单一 steps 值看起来像完整参数编辑器。
- 打开“第一次生成参数”时，身份变为 `PRJ-019 / VER-019-01`，保存提示改为“命名版本不可覆盖”。继续修改后，当前工作明确标记为从该版本分出，`VER-019-01` 与 `HEAD-30`（打开旧版本前的 Workflow v9）同时保留。
- 复制确认先并列“复制 / 不复制”：新 `PRJ-31` 只带当前 Workflow、参数、ProteinPrompt 和画布布局；命名版本为 0，最近 Run 显示“尚未运行 · 没有 Results”，来源持续指向 `PRJ-019`。
- 删除 `PRJ-019` 前，确认摘要列出两个命名版本与 `RUN-019-08 / Results`；确认后完整项目进入最近删除，工作区回到干净默认示例。恢复后仍为原 `PRJ-019`，两个命名版本和最近 Run / Results 全部保留，没有创建副本。
- A/B/C 浮动箭头、键盘 `←` / `→` 与 `?variant=A/B/C` 均可切换方案；输入框聚焦时方向键不会切换。三种布局在 1280×720 视口下页面级宽高均无溢出，最终浏览器 console 无 error 或 warning。

截图：

- `variant-a-auto-saved-copy.png` — 默认示例首次修改后建立的个人副本、自动保存状态，以及 ESM-3 参数摘要的“不完整示意”标注。
- `prompt-studio-explicit-save.png` — 2026-08-30 保存边界走查截图；五类可编辑 conditioning 内容与联合编辑入口同屏，不暴露内部 `ResidueLayout`。2026-08-31 增加的 preview 确认步骤请以当前可运行原型为准。
- `variant-b-version-branch.png` — 从“第一次生成参数”分出的当前工作、旧命名版本与打开前当前工作同屏。
- `variant-c-independent-copy.png` — 独立副本没有命名版本、Run 或 Results；来源项目 ID 持续可见。
- `variant-c-recently-deleted.png` — 完整项目进入最近删除，版本和 Run / Results 作为同一项目内容等待恢复。

## 仍待裁决

- 打开旧命名版本后，“打开前的当前工作”在正式界面中的名称、排序和返回入口仍需依据原型反馈裁决。
- 个人项目列表默认排序继续按规格保持未决。
- 本原型不把任何示例项目名、时间、版本名、PDB、模型或参数变成产品默认值。

## 功能规格影响

当前原型继续把 `ResidueLayout` 保留为后端内部科学身份轴，不作为前端可见或可编辑的 ProteinPrompt 内容；Studio 只呈现五类 conditioning 内容。保存路径现已明确表达 backend `open → preview → apply`：preview 显示摘要与 diagnostics 但不保存 Draft，确认后以 `intent=replace` 更新当前 Project 的最新 Workflow Draft。现有基线仍足以区分默认示例、个人项目当前工作、Prompt Studio 草稿、命名版本、复制项目和最近删除恢复。

仍有一个需要用户选择后单独裁决的表达问题：规格要求打开旧命名版本继续修改时保留“旧版本”和“打开前的当前工作”，但尚未规定后者的正式名称、排序、返回入口以及多个编辑分支存在时哪个被称为“当前”。本原型的 `HEAD-*` 只是为了让状态可见的占位表达，不能直接写回功能规格。删除当前项目后显示默认示例也只是走查占位行为，不构成产品决定。

本次只直接更新当前原型的契约表达，不新建原型，也不修改权威功能规格。A/B/C 或组合方向与上述版本表达仍待裁决；原型代码不成为生产实现基线。
