# SoluProt-next

项目维护的 Python 3.12+ SoluProt 移植，用于预测蛋白在 *Escherichia coli* 中的可溶性表达。包版本为 `soluprot 1.1.0`，不声称是上游官方 SoluProt 1.1.0 发布版，也不承诺与某个上游发布版逐字节或逐行为相同。

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

`soluprot_assets/tmhmm-2.0d/` 随包提供第三方脚本、模型及两组 decoder。[随附 README](soluprot_assets/tmhmm-2.0d/README)载有禁止再分发的说明，本项目的分发授权依据仍待核实。本地材料尚未找到相应授权或解释，文件已被打包不能证明获得授权，也不能据此断定不存在其他授权。

## 输入与两种运行方式

输入为 FASTA 序列。标准字母表是大写 `ACDEFGHIKLMNPQRSTVWY`；最短长度为处理后 20 个残基。

独立 CLI 的 `--check_unknown` 默认关闭：它会删除所有不在上述字母表中的字符，包括非标准残基符号和小写字符，再检查长度并计算。这会改变实际评价序列。若要求遇到这类字符立即失败，应明确传 `--check_unknown`；它不是允许工具原样评价任意符号的开关。

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

独立 CLI 优先使用显式 `--usearch`、`--tmhmm` 路径，否则查找 `PATH`。相对显式路径按安装包根目录解析，而非输入 FASTA 所在目录。CLI 不会自动选择 wheel 内的 TMHMM 文件。

模型与资源入口包括：

- `data/models/grad_clf_v1_tc/`：full 模型。
- `data/models/grad_clf_v1_tc_notmhmm/`：no-TM 模型。
- `data/Ecoli_xray_nmr_pdb_no_nesg.fa`：USEARCH 参考数据库。
- `soluprot_core/`、`feature_scripts/`：实现及特征处理代码。

输出 CSV 包含运行行标识、FASTA 标识及 `soluble` 值；具体列名和命令参数以 [`cli.py`](soluprot_core/cli.py)为准。模型读取和预测实现见 [`model.py`](soluprot_core/model.py)与 [`features.py`](soluprot_core/features.py)。

