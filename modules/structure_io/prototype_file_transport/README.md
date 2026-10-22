# 标准结构文件交接实验（一次性原型）

运行真实 ESM SDK loader、ProteinMPNN parser/featurizer、Gemmi 和 Bio.PDB，观察标准文件经过工具读取后的序列、位置和坐标。这里没有生成模型推理。

从此工作树根目录运行：

```sh
/Users/sorachan/Documents/modules-ESM/.venv/bin/python modules/structure_io/prototype_file_transport/run.py --source-root /Users/sorachan/Documents/modules-ESM --output /private/tmp/protein-file-transport-recheck
```

`--source-root` 指向已有 `repositories/esm`、`repositories/ProteinMPNN` 的项目；Python 环境需安装项目现有依赖。本实验只读取它们。省略 `--output` 时重新生成此目录的 `evidence/`。

| 资源 | 用途 |
|---|---|
| `run.py` | 构造挑战文件、执行实际读取与转换、记录结果，并核对本实验的预期观察 |
| `fixtures/1PGA.cif` | [RCSB 原始 mmCIF](https://files.rcsb.org/download/1PGA.cif)，离线重跑使用 |
| `../../esm3/prototype_real_validation/fixtures/1PGA.pdb` | 上一原型已保存的 RCSB 原始 PDB |
| `evidence/summary.json` | 11 个独立场景的实测观察、设计影响和边界 |
| `evidence/inputs/` | 本次真实传入各 parser 的原始文件和挑战文件 |
| `evidence/01-*.json` 至 `11-*.json` | 原生返回值，包括序列、位置、mask、坐标及实际异常 |
| `evidence/explicit-*.pdb` | 已明确选择模型、author 链和蛋白组分的工具临时文件 |
| `evidence/explicit-*-mapping.json` | 临时工具位置到所选来源位置的对应 |
| `evidence/explicit-insertion-fixed-positions.json` | 固定来源 A11A 经映射进入 ProteinMPNN 第 12 位的原生 featurizer 结果 |

挑战文件均从 1PGA 通过脚本改造；新增插入码、缺失原子、altloc、编号跳跃、平移构象及配体用于暴露接口行为。这些构象未经过物理优化或实验测定。完整输入保留，工具临时 PDB 只包含明确选择的蛋白。JSON 中的非有限坐标写为 `null`，原生 mask 同时保存。

连续编号转换是针对这些已选择蛋白单链的具体操作。文件中仍需保留的其他组分、多链组装和一般性格式转换未在此实现。
