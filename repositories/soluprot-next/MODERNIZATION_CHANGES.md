# SoluProt 现代化修改说明

本文档记录本次对当前目录项目的主要修改内容。

## 修改目标

本次修改的目标是将项目从旧版 Python / 旧版依赖运行方式迁移为仅依赖现代 Python 包栈运行，并移除旧版兼容层。

作为独立 package/CLI 使用时，当前项目目标环境：

- Python 3.12 或 3.13
- 现代 Biopython、NumPy、pandas、tqdm
- 不再依赖旧版 scikit-learn/joblib/pickle 模型文件进行运行时预测

Protein Workbench Provider 部署是更窄的合同：使用 Python 3.12，并要求
`PROTEIN_WORKBENCH_SOLUPROT_ROOT` 下的固定 runtime/USEARCH 布局。独立 package 的
Python 3.13 支持不扩大该 Workbench Provider 合同。

## 主要改动

### 1. 项目结构现代化

- 引入标准 Python 包结构 `soluprot_core/`
- 使用 `pyproject.toml` 管理项目元数据、依赖和 console script
- 提供现代命令行入口：

```bash
soluprot --i_fa seqs.fasta --o_csv out.csv --tmp_dir tmp
```

源码目录中也可以直接使用：

```bash
python -m soluprot_core.cli --help
```

### 2. 移除旧版兼容路径

已删除旧版运行和转换相关内容：

- 顶层兼容脚本 `soluprot.py`
- 旧版 pickle 模型文件
- 旧版 scikit-learn wrapper 文件
- legacy model export 工具
- legacy export 相关测试
- 运行依赖中的 `joblib`

打包配置也已同步清理，不再包含 `.pkl` 文件或旧版导出脚本。

### 3. 模型运行方式更新

运行时模型已改为使用 `data/models/` 下的 JSON/NPZ 模型资产：

- `data/models/grad_clf_v1_tc/model.json`
- `data/models/grad_clf_v1_tc/trees.npz`
- `data/models/grad_clf_v1_tc_notmhmm/model.json`
- `data/models/grad_clf_v1_tc_notmhmm/trees.npz`

这些模型由项目内置推理逻辑直接加载，不需要 scikit-learn、joblib 或 pickle 文件。

模型元数据也已清理：

- 删除旧 pickle 来源字段
- 将模型类型改为中性的导出模型类型
- 保留 float32 树阈值语义，以保证导出模型输出稳定

### 4. Biopython 兼容现代版本

旧版 Biopython API 已替换为现代兼容写法，包括：

- 移除已废弃的 `Bio.Alphabet` 依赖
- 替换旧版氨基酸百分比 API
- 保持现代 Biopython 下特征计算结果稳定

### 5. 外部工具处理

项目仍依赖为目标平台单独安装的 USEARCH 完成部分特征计算。full Method 还会执行
wheel-bundled TMHMM 2.0d asset closure；它不是另一个 Workbench 外部安装前提。

命令行会按以下顺序解析工具路径：

1. 显式传入的 `--usearch` / `--tmhmm`
2. 系统 `PATH`

上面的顺序描述 standalone CLI 的路径解析；Workbench 直接提供已经接纳的 USEARCH 与
wheel-bundled TMHMM 路径。源码和 wheel 不包含 USEARCH；TMHMM 2.0d 作为 Workbench
Provider 资产随包提供，
仅支持 `Darwin_arm64` 与 `Linux_x86_64` decoder。Intel macOS 与 Linux ARM64 不属于
当前 full Method 支持范围。

## 测试与验证

以下验证可在源码树外的临时构建环境中执行：

```bash
export SOLUPROT_BUILD_ROOT="$(mktemp -d)"
cp -R . "$SOLUPROT_BUILD_ROOT/source"
python3.12 -m venv "$SOLUPROT_BUILD_ROOT/environment"
"$SOLUPROT_BUILD_ROOT/environment/bin/python" -m pip install build pytest
"$SOLUPROT_BUILD_ROOT/environment/bin/python" -m build --wheel \
  --outdir "$SOLUPROT_BUILD_ROOT/dist" "$SOLUPROT_BUILD_ROOT/source"
"$SOLUPROT_BUILD_ROOT/environment/bin/python" -m pip install \
  "$SOLUPROT_BUILD_ROOT/dist/soluprot-1.1.0-py3-none-any.whl"
(
  cd "$SOLUPROT_BUILD_ROOT/source"
  "$SOLUPROT_BUILD_ROOT/environment/bin/python" -m pytest -q tests
)
```

还执行了完整 CLI 示例，使用显式配置的 USEARCH/TMHMM 对 `data/test.fa` 进行预测，并确认输出与 `data/test.csv` 一致。

构建产物检查结果：

- clean wheel 中不再包含旧 `.pkl` 模型
- 不再包含 legacy exporter
- 不再包含旧 scikit-learn wrapper
- package metadata 中不再声明 `joblib`
- USEARCH 由部署环境提供；Workbench 从 wheel 中选择与目标平台匹配的 TMHMM decoder

wheel 保留 `py3-none-any` 文件名，是因为 Python 包不含 CPython ABI extension，且同一
wheel 有意携带两组 decoder 数据文件；该文件名不表示任意平台均受支持。Readiness 仍只
接受 `Darwin_arm64` 与 `Linux_x86_64`。若将来改变 decoder inventory 或拆分平台 wheel，
必须形成新的明确 packaging contract。

## 当前状态

当前项目已经转为仅现代版本运行。

保留的核心运行资产为：

- `soluprot_core/`
- `data/models/`
- `feature_scripts/`
- `data/test.fa` / `data/test.csv`
- 由部署环境提供的 USEARCH，以及 wheel 内的 TMHMM 资产

不再维护 Python 3.7 legacy 运行路径。历史 `.venv37` / `.venv37-legacy`
目录若存在，仅作为迁移残留，不参与当前构建或验证。
