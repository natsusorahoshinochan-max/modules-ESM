# PROTOTYPE 7 — Results Workbench 与候选关系（一次性原型）

> 三种 Results Workbench 信息结构在同一页面中用 `?variant=` 切换；原型只回答候选比较、来源、筛选作用域与导出 Run 归属是否清楚。

## 决定 — 2026-08-30 采用方案 B

**原型 7 采用方案 B「谱系工作台」作为后续正式界面设计的 Results Workbench 整体信息结构方向。** 父结构 Candidate → ProteinMPNN 子代序列 Candidate → 再次折叠结构 Candidate 构成主要科学来源轴；候选账本保留为相邻索引，用于聚焦、排序、临时筛选和明确勾选比较 / 导出集合。

这是用户的明确选择；未提供额外选择理由，因此本文不推断理由。方案 A「候选账本」与方案 C「审阅篮」只作为一次性比较证据保留，不再是同等候选。本决定裁决整体信息层级，不裁决默认 Metric、Metric Definition、显示方向与单位、默认比较数量、最终三维布局、筛选表达能力、最终颜色或视觉密度。

## 唯一产品问题

研究人员是否能准确说出当前比较的是哪些 Candidate、它们从何而来、表格筛选是否改变了 Workflow，以及导出的固定 ZIP 属于哪次 Run？

本原型只对应 `docs/2026-08-29-webui-functional-spec.md` 第 5 节，并继承第 4.7 节已经采用的“来自修改前的流程”持续标记。它不裁决默认 Metric、Metric Definition、默认列、正式科学数值、最大比较数量、最终结构视图布局、筛选表达能力或生产实现。

## 运行

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-7-results-workbench/serve.py
```

打开 <http://127.0.0.1:4185/?variant=B>。方案 B 现在是默认方案。

- `B` — **已采用。谱系工作台**：父结构 → ProteinMPNN 子代序列 → 再折叠结构成为主轴，候选表退到下方。
- `A` — 仅供比较。**候选账本**：候选表是主索引，比较台和来源 dossier 保持在右侧。
- `C` — 仅供比较。**审阅篮**：筛选后的候选先进入同一个比较/导出篮，再在中央完成并排或已有对齐结果叠加。

所有状态只存在内存中，刷新即重置。示例 Candidate 身份、序列变化、结构几何、Method、Score Observation 与 Metric 数值均为交互示意；界面持续标出这一点。原型不连接真实 Run，也不会写回 Workflow 或生成真实 ZIP。

## 正常走查路径

1. 初始单候选模式查看 `SF-STR-031`，核对表格焦点、结构、序列、分数和三段谱系同步。
2. 勾选 `SF-STR-031` 与 `SF-STR-032`，切换“并排比较”，确认比较台明确列出两个稳定 Candidate ID。
3. 切换“已有对齐结果叠加”，核对界面引用已有 `Structure Alignment Evidence · SAE-P01`，而不是把临时摆放冒充科学计算。
4. 在谱系上依次打开 ESM-3 父结构、ProteinMPNN 子代序列和 SimpleFold 再折叠结构，确认三者靠角色、稳定身份与 Method 连接，而不是靠相似名称或列表位置。
5. 按示意分数排序并应用临时筛选；核对“仅当前视图，Workflow 未改变”。
6. 点击“保存为流程筛选”，先看将新增的可编辑筛选 Node Instance 摘要，再确认；当前 Workflow revision 改变，但旧 Run 结果不重算。
7. 勾选候选并导出；核对固定 ZIP 内容与 `Run 017 / Workflow v11` 来源后确认模拟导出。

## 容易误解路径

1. 勾选来自不同父结构、没有共同 Structure Alignment Evidence 的候选，然后尝试叠加；叠加被阻止，并说明需要 Workflow 已产生的对齐结果。
2. 临时筛选隐藏一个已勾选 Candidate；选择仍保留，筛选区与导出区都明确显示“有已选项被当前视图隐藏”。
3. 在已经显示“来自修改前的流程”时继续排序、比较和导出；来源提示必须持续伴随页面、比较台和导出确认，而不是只出现一次。
4. 保存临时筛选后核对：它新增 Workflow 筛选 Node Instance，但不会改变当前旧结果，也不会把当前表格排序保存为科学筛选。

## 原型边界

- 表格排序和临时筛选只影响当前视图；只有明确确认“保存为流程筛选”才改变 Workflow。
- 当前焦点 Candidate、勾选集合和当前过滤后的可见行是三个明确状态；过滤不会暗中取消勾选。
- 并排比较只是布局；叠加只在共同的已有 Structure Alignment Evidence 可用时开放。
- 父结构、ProteinMPNN 子代序列和再次折叠结构始终以 Candidate 身份、角色和来源关系表达。
- 导出始终是固定 ZIP；候选 PDB、合并 FASTA、分数 CSV 和记录身份、谱系及 Run 信息的说明文件没有格式选择对话框。
- 最近一次 Run 属于 Workflow v11，而当前 Workflow 已是 v12；旧结果仍可查看、筛选、比较和导出。

## 走查记录

浏览器走查完成于 2026-08-30：

- 初始状态只勾选并聚焦 `SF-STR-031`。候选账本、单结构查看、76-residue sequence（示意）、三个 Score Observations（示意）、`RUN-2026-08-30-017` 和 `E3-STR-007 → MPNN-SEQ-031 → SF-STR-031` 三段谱系同步显示。
- 加入 `SF-STR-032` 后，并排模式明确写出两个稳定 Candidate ID，且标记“并排比较 · 不执行结构叠加”。切换叠加时只使用两者共同的已有 `Structure Alignment Evidence · SAE-P01`，同时声明当前视图没有发起新的对齐计算。
- 在共同 `SAE-P01` 的集合中加入属于 `E3-STR-012 / SAE-P02` 的 `SF-STR-044` 后，界面自动退出叠加；再次尝试时显示“没有共同的已有 Structure Alignment Evidence”，未产生新的科学对齐结果。
- 谱系点击分别显示父结构 Candidate、ProteinMPNN 子代序列 Candidate 和再次折叠结构 Candidate 的独立身份、角色、数据类型与 Method（示意），不依赖相似名称或表格位置解释关系。
- `父结构 Candidate = E3-STR-007` 的临时筛选把表格从 6 行缩到 3 行，同时保留被隐藏的 `SF-STR-044` 勾选状态；选择摘要明确显示 `1` 个已勾选 Candidate 被临时筛选隐藏。
- “保存为流程筛选”确认面板把“现在的临时视图”和“确认后新增筛选 Node Instance”并列说明；确认后当前 Workflow 从 v12 变成 v13，当前 Results 继续标记来自 Run 017 / Workflow v11，且没有自动重算。
- 固定 ZIP 确认面板列出每个 Candidate 的 PDB、合并 FASTA、分数 CSV 和记录 Candidate 身份、谱系及 Run 信息的说明文件。模拟导出包含 3 个明确勾选 Candidate，并持续记录 `RUN-2026-08-30-017 / Workflow v11`。
- 点击示意 Solubility 表头后首行变为 `SF-STR-052 / 0.82`，状态检查器明确记录这只是当前视图排序。输入框聚焦时方向键不会切换方案；其他控件聚焦时 `←/→` 会更新 `?variant=`。重载 `?variant=B` 后仍打开方案 B，内存交互状态按原型约定重置。
- A/B/C 页面在 1280×720 视口内无页面级溢出，最终浏览器 console 无 error 或 warning。

截图：

- `variant-a-single-candidate.jpg` — A 的表格主索引、单候选结构、分数与来源 dossier 同屏。
- `variant-b-lineage-workbench.jpg` — B 的父结构 → 子代序列 → 再折叠结构横向主轴，以及下方候选账本。
- `variant-c-review-basket-overlay.jpg` — C 的两个 Candidate 审阅篮与 `SAE-P01` 已有对齐结果叠加。

## 仍待裁决

- 默认 Metric 列、Metric Definition、显示方向与单位、默认比较数量和最终三维布局仍按规格保持未决。
- “保存为流程筛选”的正式表达能力仍未裁决；本原型只演示一个明确的示意条件，不把它变成正式语法。

## 功能规格影响

本次走查没有发现必须立即修改第 5 节的功能缺口：现有“同步表格 / 结构 / 序列 / 分数 / 来源、并排与已有对齐结果叠加区分、临时筛选与流程筛选区分、固定 ZIP、旧 Workflow 来源持续提示”的基线足以支持这条旅程。

方案 B 的采用决定已经回写权威功能规格。本次选择只冻结“谱系主轴 + 相邻候选账本 + 明确比较 / 导出集合”的整体信息层级，不改变第 5 节既有的 Candidate、结构对齐、筛选、导出或旧 Results 语义。后续若裁决默认 Metric、比较数量、最终三维布局或筛选表达能力，再单独回写规格；原型代码本身不成为生产实现基线。
