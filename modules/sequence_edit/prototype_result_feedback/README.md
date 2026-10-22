# 可丢弃原型：筛选结果重新成为设计模板

问题：用户选中的真实序列或结构，经过重新选择条件、增删位置、预览与确认，交付哪些公开信息，才能进入下一轮设计？

打开 `index.html` 即可交互。页面包含真实结果数据、自由操作和三个引导演习：结构回流、预览取消、纯序列建立模板。状态在内存中；每次动作显示当前完整目标位置、条件、已有坐标和交付预览。页面不调用模型。

## 实际入口

在原型 worktree 根目录，用现有项目 Python 环境执行：

```sh
/Users/sorachan/Documents/modules-ESM/.venv/bin/python modules/sequence_edit/prototype_result_feedback/run.py structures --source-root /Users/sorachan/Documents/modules-ESM
```

此入口复用 `modules/esm3/prototype_file_input/evidence` 的两条真实 58 位序列，分别调用 ESM3 生成结构。随后运行相邻的[评价与抽取原型](../../filtering/prototype_evaluation_handoff/README.md)，取得其实际选中包；本原型继续读取该包：

```sh
/Users/sorachan/Documents/modules-ESM/.venv/bin/python modules/sequence_edit/prototype_result_feedback/prepare_inputs.py --selection modules/filtering/prototype_evaluation_handoff/evidence/PROTOTYPE_WIPE_ME/selected/manifest.json
/Users/sorachan/Documents/modules-ESM/.venv/bin/python modules/sequence_edit/prototype_result_feedback/run.py feedback --source-root /Users/sorachan/Documents/modules-ESM
/Users/sorachan/Documents/modules-ESM/.venv/bin/python modules/sequence_edit/prototype_result_feedback/run.py round2-structures --source-root /Users/sorachan/Documents/modules-ESM
```

`prepare_inputs.py` 将实际结构嵌入 HTML，并通过 `export.cjs` 执行 HTML 内的同一纯逻辑。导出的目标位置及条件写成实际 `target.cif` 和 `request.json`，由真实工具调用读取。运行需要本地现有 ESM3 权重、Node 和项目固定依赖，不安装或下载资源。

## 数据路径与结果

本例按评价原型事前确定的“原 1PGA A 全链、参考长度归一化 TM-score ≥ 0、降序最多 1 项”选中 `feedback-candidate-1`，读取独立抽取包中的序列和结构，重建模板。

- 第一轮明确复用已有两条 58 位真实序列；新生成两个结构。
- 新模板固定目标前五位 `MTYKL`，选择原位置 1–5、30–35 的 N/CA/C 坐标。
- 在目标位置 11 后插入两个位置，再删除增补后位置 27（原位置 25），确认后长度为 59。骨架条件正确移动到 1–5、31–36。
- 新增位置 12、13 保留在完整目标 mmCIF 中，原子记录为空。`label_seq_id` 表达当前目标位置，保留原子的 `auth_seq_id` 保持所选结构编号。文件中其他保留坐标并未自动成为条件。
- 另一条同源操作路径在预览后取消，完整保留 58 位、原字符及条件。
- 使用该 59 位模板真实生成两个新序列，保留五个固定字符；随后分别真实生成结构，供第二次评价与筛选。
- 同一已选结果仅采用序列时，也能增删并建立 59 位模板；实际调用原生编码器，坐标和结构 token 均为空。这条路径没有额外采样。

结构生成参数为 ESM3 open small、4 步、temperature 0.5、不退火，第一轮 seed 81/82、第二轮 seed 181/182。第二轮序列生成使用 1 步、temperature 0.5、不退火、coordinates-only=true、seed 101/102。采样次数用于验证交接；本例没有研究生物学设计质量。

本例所有新结构均为 ESM3 的序列条件结构生成及原生结构 decoder 解码；没有执行独立折叠模型。decoder 自然产生的 pLDDT/pTM 随结构保留。序列生成返回的原坐标轨道只是输入条件，单独的结构生成调用才产生新结构。

## 这条交接需要的信息

| 交接 | 已经足够的内容 |
|---|---|
| 抽取包 → 编辑器 | 明确对象标识、序列和包内结构文件；结构可用位置和原子由文件读取 |
| 编辑器 → 工具 | 完整当前目标文件、明确链、当前目标位置上的固定字符和骨架选择；纯序列使用目标位置文件 |
| 工具 → 操作模块 | 新生成的序列或结构、自然产生的置信度，以及输出与本次请求的对应 |

编辑器在编辑过程中维护来源位置与当前目标位置的对应；对下游交付的 mmCIF 已经表达完整目标位置，因此这个请求不需要额外的历史位置映射。工具内部使用的 atom37、token 偏移和 decoder 留在 `run.py` 中。筛选和抽取模块没有替用户建立下一轮条件，条件来自本原型的明确编辑动作。

结论限于这个单链、蛋白骨架条件、变长后回流的实际调用。完整应用的画布执行、循环调度和文件持久接收由相邻原型分别验证。

## 证据与资源

- `evidence/candidates/manifest.json`：两条第一轮序列、实际生成结构、工具参数和自然置信度。
- `evidence/structures-summary.json`：第一轮两次真实结构调用摘要。
- `evidence/editing-summary.json`：实际读取的抽取包、确认/取消和条件位置结果。
- `evidence/native-input-recheck.json`：最终目标文件保持作者编号，重建原生坐标与实际生成输入逐值一致。
- `evidence/feedback/`：HTML 动作及导出、完整目标 mmCIF、实际请求、原生输入和第二轮序列结果。
- `evidence/cancel/`：取消后恢复原模板的实际 HTML 状态及交付。
- `evidence/sequence-only/`：纯序列模板及请求；真实编码结果在 `feedback/result.json`。
- `evidence/round2-candidates/manifest.json`：第二轮两个新对象及真实结构，使用独立新标识。
- `evidence/round2-structures-summary.json`：第二轮结构调用摘要。
- `evidence/*native-output.npz`：实际结构 token 与解码坐标，仅供工具证据检查。

所有重模型调用经过现有全机资源监督器。CPU 使用 float32；已有权重逐 tensor 转入匿名 scratch mmap，计算完成后随进程释放。worker 在连续三秒可用内存低于 384 MiB 或单阶段超过 600 秒时退出。模型先采样结构 token，释放主模型后再加载结构 decoder，序贯执行。

工具依据是固定上游 `repositories/esm/esm/models/esm3.py` 的 `encode/generate`、`esm/utils/generation.py` 的原生采样、`esm/utils/decoding.py` 的 `decode_structure` 和 `esm/models/vqvae.py` 的结构 decoder。没有更改上游源码。
