# 可丢弃原型：标准结构文件与最少任务参数交给 ESM3

问题：保留原始 PDB，只交接长度编辑的对应关系、序列条件和坐标选择，能否在工具边界正确构造输入并完成真实 ESM3 序列生成？

## 运行

在原型 worktree 根目录执行：

```sh
/Users/sorachan/Documents/modules-ESM/.venv/bin/python modules/esm3/prototype_file_input/run.py --source-root /Users/sorachan/Documents/modules-ESM --output /private/tmp/prototype-esm-file-input
```

脚本调用 `modules/sequence_edit/prototype_file_handoff/export.cjs`，执行同一个交互 HTML 的纯逻辑：在原 A11 后插入三个位置，删除原 A25，得到 58 个目标位置。随后实际读取 PDB、调用本地已存在的模型权重并保存证据；不下载模型或调用远端。需要 Node、项目现有 Python 环境及 `.models/esm3`。

仅重做轻量接口检查：

```sh
/Users/sorachan/Documents/modules-ESM/.venv/bin/python modules/esm3/prototype_file_input/run.py --source-root /Users/sorachan/Documents/modules-ESM --inspect-only
```

默认检查本目录 `evidence/html-request.json`。更换证据目录时同时指定 `--output` 或 `--request`。

## 实际交接

公开请求只包含文件名、作者链标识、目标位置到原残基的映射、固定序列字符和坐标选择。`target_index` 从 0 开始；原残基通过作者编号和插入码定位。新位置映射为 `null`。目标长度等于映射条目数。

`compile_request()` 在工具内部读取原文件，创建原生 `ESMProtein` 与 atom37。序列未选位置为原生 `_`，坐标未选位置为 NaN。观察到的氨基酸与本次选择的序列条件分别处理。本原型的 ESM 坐标条件只接纳完整的 N、CA、C 骨架三原子；CA 单原子、O 单原子和重复选择均拒绝。

输入是从 1PGA 明确选择的蛋白链 A 残基；原文件保留全部原始内容。单模型检查、明确作者残基对应与原子存在检查发生在适配器。宿主和公开请求无需定义 atom37。把文件和请求复制到独立临时目录后，也能构造相同的原生输入，无需生产者路径。

## 验证结果

`evidence/generation.json` 保存完整结果与检查。实际使用固定上游 `ESM3` 类、`esm3_sm_open_v1` 权重、原生 `encode()` 和 `generate(ESMProteinTensor, GenerationConfig)`。生成的 token 通过原生序列 tokenizer 解码。forward hooks 只读取真实输入和输出，不更改计算。

三种情形均真实完成 58 位序列生成，保留所选前五位 `MTYKL`。参数为 CPU、float32、seed 42、一步采样、temperature 0.5。一步用于验证输入及条件交接；尚未进行候选的结构预测、质量评分或生物学评价。

| 本次条件 | 真实 forward 的完整骨架位置 | 真实 forward 的结构 mask 数 | 结果 |
|---|---:|---:|---|
| 全部对应残基，coordinates-only=true | 55 | 58 | 58 位序列 |
| 全部对应残基，coordinates-only=false | 55 | 0 | 58 位序列 |
| 仅前五位坐标，coordinates-only=true | 5 | 58 | 58 位序列 |

重要发现：

- 直接 `ESMProtein.from_pdb()` 得到 56 位已知序列；待设计位置及序列固定选择仍需任务参数。
- 将编辑结果中实际有坐标的 55 个残基写成 PDB 再读取，原生 `from_pdb()` 只得到 55 位。这个 ATOM-only 写读路径没有保存三个新目标位置。标准文件的表达能力与具体读取入口读取哪些字段，需要分别核对。
- 原生结构转换明确拒绝“58 位序列＋56 行坐标”；显式映射在适配器内生成 58 行稀疏坐标后可以真实采样。
- 学习得到的结构 encoder 给新增无坐标位置的 token 是 2246。默认 `condition_on_coordinates_only=true` 在真实采样时把整个结构 token 轨道改成 mask 4096，同时保留选定坐标。选择 false 时，2246 真正进入模型，实际 logits 和生成序列均发生变化。适配器必须按原生参数含义传递，不能把这些模式视为等价。
- 原生几何路径需要完整 N/CA/C。CA-only 输入产生零个有效几何 frame；仅检查“存在坐标”会夸大工具实际接收的条件。
- `ESMProtein.from_pdb()` 的便利对象没有填入 `residue_index`；适配器通过 `ProteinChain` 的作者编号与插入码建立明确对应。

生成结果仅是序列。原生 tensor 返回的坐标是携带的输入条件，不能作为新的预测结构输出。本原型没有调用结构或功能 decoder。

## 资源与证据

CPU 原生几何 attention 的 bf16 尝试因 dtype 不匹配失败，原始证据保存在 `bf16-cpu-failure.json` 和 `bf16-cpu-worker.log`。成功路径把已有权重逐 tensor 转为 float32，写入匿名 scratch mmap；原生 forward 与采样保持不变。scratch 创建后立即 unlink，进程结束即释放占用。现有模型监督器持有全机资源锁；worker 在可用内存连续三秒低于 384 MiB 或执行超过 600 秒时退出。

- `fixtures/1PGA.pdb`：原始研究输入，复制自上一轮真实工具验证。
- `evidence/html-actions.json` / `html-request.json`：实际 HTML 操作与导出请求。
- `request.json` / `sparse-request.json`：实际两种坐标选择。
- `compiled-inputs.npz`：实际原生输入数组。
- `edited-observed-only.pdb`：重读后丢失新目标槽位的最小复现。
- `preparation.json` / `boundary-findings.json`：读取、对应与工具边界检查。
- `generation.json`：本轮完整生成结果、参数、用时与逐项检查。
- `native-forward-and-output.npz`：三种情形的实际 forward 输入、完整 sequence logits 和输出 token。
- 三个具名 case JSON：每种情形的实际序列、mask 和坐标数量。

检查覆盖当前单模型、单链、蛋白骨架条件。多链、mmCIF 标识转换和混合组分由相邻文件交接原型分别探测。
