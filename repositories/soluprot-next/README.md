# SoluProt-next

项目维护的 Python 3.12+ SoluProt 移植，用于预测蛋白在 *Escherichia coli* 中的可溶性表达。包版本为 `soluprot 1.1.0`，不声称是上游官方 SoluProt 1.1.0 发布版，也不承诺与某个上游发布版逐字节或逐行为相同。

独立 CLI 与 Protein Workbench 接入使用同一计算包，但输入处理和环境入口有区别。Workbench 后端使用 Python 3.12；其当前部署方法见[Provider 配置](../../docs/provider-configuration.md)，不能把独立虚拟环境路径直接填作 `PROTEIN_WORKBENCH_SOLUPROT_ROOT`。

## 安装与运行资产

源码由 [`pyproject.toml`](pyproject.toml)打包，包含 Python 实现、JSON/NPZ 梯度提升模型、E. coli 参考数据库，以及下节列出的第三方 TMHMM 文件。运行预测不依赖 scikit-learn、joblib 或 pickle 模型；USEARCH 12 由部署环境提供。

从本目录执行以下构建步骤，将源码副本、构建环境与产物放在当前 checkout 之外：

```bash
export SOLUPROT_BUILD_ROOT="$(mktemp -d)"
cp -R . "$SOLUPROT_BUILD_ROOT/source"
python3.12 -m venv "$SOLUPROT_BUILD_ROOT/environment"
"$SOLUPROT_BUILD_ROOT/environment/bin/python" -m pip install --upgrade pip build
"$SOLUPROT_BUILD_ROOT/environment/bin/python" -m build --wheel \
  --outdir "$SOLUPROT_BUILD_ROOT/dist" "$SOLUPROT_BUILD_ROOT/source"
```

将生成的 `soluprot-1.1.0-py3-none-any.whl` 安装到需要使用它的环境。具体用户部署路径由其后端机器决定。

`py3-none-any` 文件名描述当前无 CPython ABI extension 的 Python 包和数据打包方式，不承诺 full 模式可以在任意平台运行。full 模式目前随包提供 `Darwin_arm64` 和 `Linux_x86_64` decoder，不支持 Intel macOS 或 Linux ARM64。no-TM 使用另一套模型，不运行 TMHMM，仍依赖目标平台可用的 USEARCH。

## 第三方运行资产

`soluprot_assets/tmhmm-2.0d/` 是随包提供的第三方文件，包括脚本、模型及两组 decoder。其[随附 README](soluprot_assets/tmhmm-2.0d/README)载有禁止再分发的说明；本地材料中尚未定位说明本项目相应分发依据的授权或解释。文件已经被打包是实现事实，不能称为项目拥有这些第三方资产的授权。该依据缺口仍待核实，见[治理问题清单](../../docs/2026-10-15-documentation-governance-issues.md)；这里不作是否存在其他授权的结论。

## 输入与两种运行方式

输入为 FASTA 序列。标准字母表是大写 `ACDEFGHIKLMNPQRSTVWY`；最短长度为处理后 20 个残基。

独立 CLI 的 `--check_unknown` 默认关闭：它会删除所有不在上述字母表中的字符，包括非标准残基符号和小写字符，再检查长度并计算。这会改变实际评价序列。若要求遇到这类字符立即失败，应明确传 `--check_unknown`；它不是允许工具原样评价任意符号的开关。

Workbench 当前在模块入口拒绝非标准残基，并在调用时明确传 `--check_unknown`，不会使用独立 CLI 默认的删除行为。两种入口不能据默认值混同；参数是否进一步开放按[参数审查](../../docs/tool-parameter-exposure-audit.md#soluprot-非标准字符处理)核对，不能直接关闭检查而静默改变输入。

full 模式运行示例明确开启输入检查：

```bash
soluprot \
  --i_fa sequences.fasta \
  --o_csv predictions.csv \
  --tmp_dir work \
  --usearch /absolute/path/to/usearch \
  --tmhmm /absolute/path/to/tmhmm \
  --check_unknown
```

no-TM 模式使用独立的无 TMHMM 特征模型：

```bash
soluprot \
  --i_fa sequences.fasta \
  --o_csv predictions.csv \
  --tmp_dir work \
  --usearch /absolute/path/to/usearch \
  --no_tmhmm \
  --check_unknown
```

独立 CLI 先使用显式 `--usearch`、`--tmhmm` 路径，否则查找 `PATH`；相对显式路径按安装包根解析，不按输入 FASTA 所在目录解析。提供 wheel 内的 TMHMM 文件并不表示独立 CLI 会自动选择它；Workbench Adapter 会传入已解析的准确路径。

模型与资源入口包括：

- `data/models/grad_clf_v1_tc/`：full 模型。
- `data/models/grad_clf_v1_tc_notmhmm/`：no-TM 模型。
- `data/Ecoli_xray_nmr_pdb_no_nesg.fa`：USEARCH 参考数据库。
- `soluprot_core/`、`feature_scripts/`：实现及特征处理代码。

输出 CSV 包含运行行标识、FASTA 标识及 `soluble` 值；具体列名和命令参数以 [`cli.py`](soluprot_core/cli.py)为准。模型读取和预测实现见 [`model.py`](soluprot_core/model.py)与 [`features.py`](soluprot_core/features.py)。

