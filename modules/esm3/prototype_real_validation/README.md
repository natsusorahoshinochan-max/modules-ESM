# Throwaway：用真实工具验证模块交接

问题：编辑模块交付的位置与多轨道条件能否完整进入模型；一个工具实现能否供设计和独立评分共用；一个比较操作能否接受方法不同的工具实现并保留各自含义？这里的脚本和证据仅供原型评估。

## 运行

从本原型所在工作树根目录运行：

```sh
/Users/sorachan/Documents/modules-ESM/.venv/bin/python modules/esm3/prototype_real_validation/run.py --source-root /Users/sorachan/Documents/modules-ESM --output modules/esm3/prototype_real_validation/evidence-new
```

`--source-root` 指向已安装项目环境、固定上游源码和模型资产的项目目录。需要 Node.js、该项目 Python 依赖、`repositories/esm`、`repositories/ProteinMPNN`、`.models/esm3/data` 中的 tokenization 资产及 `esm3_structure_encoder_v0.pth`，以及 `.models/proteinmpnn/vanilla_model_weights/v_48_020.pt`。脚本不下载模型。ESM 结构编码子进程和 ProteinMPNN Adapter 均通过已有机器资源监督器串行取得模型资源。

默认保留全部输入、请求、实际输出和日志到 `--output`。再次评估可指定新目录。输入原件为 `fixtures/1PGA.pdb`，来源为 RCSB PDB 的 [1PGA](https://www.rcsb.org/structure/1PGA)。计算明确选取 A 链的标准氨基酸；原始文件中的水保留在输入原件，并在 `explicit-input-selection.json` 列出排除范围。

## 接口与职责

| 边界 | 实际调用及其交付 |
|---|---|
| 编辑表示 → 公开条件 | 调用 `modules/sequence_edit/prototype_conditions/export.cjs`，执行 HTML 中真正的纯逻辑。逐行表示与轨道表表示分别运行，相同结果才写出。 |
| 公开条件 → ESM Adapter | `run.py` 按一次明确顺序读取公开条件，生成序列、坐标、SS、SASA 和区间。采用现有 `modules.esm3.adapters.protein_for`，再调用固定上游 ESM 原生 tokenizer 和学习得到的结构编码器。 |
| 工具边界原型 → ESM SDK | 执行工具边界 HTML 的实际 `compileESM` 函数，明确选用其支持的序列、坐标、SS、SASA 四种轨道，将编译结果交给真正的 ESMProtein、GenerationConfig 和 tokenizer，并与上述路径逐项核对。 |
| 设计操作 / 评分操作 → ProteinMPNN | 两次调用同一个 `create_local` 实现；第一次采样，第二次给出完整链序列进行独立评分。输入解释和 mask 选择分别明确。 |
| 比较操作 → 比较工具 | 同一 `compare_operation(subject, reference, tool, tool_parameters)` 注入 NumPy Kabsch 或 native TM-align。各工具交付方法、对应方式、实际配对、变换和适用指标。 |

ESM 的真实验证覆盖两个 HTML 原型中的条件导出和 ESM 编译函数；工具边界原型中的模拟生成响应仍只用于边界逻辑演习。整个实验不需要应用数据库或画布执行器。

## 检验范围

- 真实 1PGA 的 56 个残基，按公开编辑逻辑在 A11 后插入 3 个位置并删除原 A25，得到 58 个当前位置。每个来源位置保留链、author number 和 insertion code；插入位置没有来源和坐标。序列观察与序列条件分开，只固定原 A1–5；坐标条件明确只采用 N/CA/C/O。
- 按内容逐一核对固定 token、掩码、来源原子坐标、SS、SASA、区间成员和 BOS/EOS 偏移。区域成员原 A10–13 在插入后编译成两个原生区间；新增位置不加入成员。SS、SASA、功能区间为接口检验条件，未作为 1PGA 的实测生物学注释。
- 执行真实 ESMProtein 构建、sequence/SS/SASA/function/residue tokenizer，以及真实约 59 MB 结构编码器推理。保存原始坐标、带特殊位置的坐标和实际结构 token。完整 ESM3 生成模型、结构解码和序列生成没有运行。
- 执行 ProteinMPNN CPU 采样，固定 A1–5，得到 2 个 56 aa 候选；选第一个再执行真实独立评分。设计评分范围是可变位置，独立评分范围为全部位置，记录各自 mask 和随机参数。分别检查真实 Adapter 对缺失主链原子、长度不一致评分输入的拒绝，以及原型操作对插入后缺失骨架的拒绝。
- 对原始 A 链作刚体变换，分别执行 Kabsch 与 TM-align。另删除 A25，比较 55 对 56 个残基。Kabsch 使用显式对应并拟合这些点；TM-align 自己建立结构对应。Kabsch 不提供 TM-score；TM-align 的归一化长度和 RMSD 范围随输出保存。

## 证据入口

`evidence/summary.json` 汇总三个真实计算实验组和一个 HTML 编译桥接组中的 722 项检查，另有 1 项两种编辑表示等价检查。大量检查逐位置和逐原子展开，检查数量应与实验组数量分别阅读。

- `conditions-bridge-input.json`、`conditions-bridge-output.json`：实际 JS 输入与公开导出；`edited-conditions.json`：供 Adapter 编译的条件。
- `esm3-evidence.json`、`esm3-tokens.json`、`esm3-arrays.npz`：断言、实际 token、原子坐标和特殊位置。
- `tool-boundary-compiled.json`、`tool-boundary-evidence.json`：工具边界 HTML 的实际编译结果、原生 SDK 接受检查及与条件路径的数值核对。JSON 中坐标空值明确恢复成 NaN；未调用 HTML 模拟 transport。
- `proteinmpnn/design.json`、`proteinmpnn/independent-score.json`、`proteinmpnn/request-config.json`：真实模型结果、评分范围和请求参数；子目录保存实际 worker 请求、结果和日志。
- `comparison-inputs.json`、`comparison-results.json`：两种方法的完整输入、对应与指标。

这里只验证以上公开交接和计算；候选折叠、完整画布、长流程循环及用户研究目标的效果另需实测。

## 需要继续验证的模型语义

实测发现，三个全 NaN 的新增位置经真实结构编码器得到 token `2246`，而 ESM 的结构 mask token 为 `4096`。缺失坐标没有直接转换成结构 token mask；原型保存了原生输出。

固定上游 `repositories/esm/esm/utils/generation.py:368–369` 在 `condition_on_coordinates_only=True` 且提供坐标时，会在采样前清除整条结构 token 轨道。原生 GenerationConfig 默认启用该参数。这一行为由源码核对和默认参数检查确认；完整生成过程尚未执行。下一步需要针对部分坐标，分别验证启用和关闭该参数时的生成输入及语义，再确定工具 Adapter 的完整承诺。仅凭张量长度一致不能完成这项验收。
