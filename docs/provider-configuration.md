# Provider 配置

本文说明后端目前如何找到服务凭据、模型、程序和运行环境。节点的温度、步数等计算参数见[参数开放审查](tool-parameter-exposure-audit.md)；模块职责见[模块能力](module-capabilities.md)。

## 应用内设置要求与当前状态

[Q47](documentation-governance-decisions.md#模块运行配置入口q47)要求提供应用内模块设置：配置项由模块声明，载体负责展示、保存和提供给模块；模块负责使用。项目用户应能配置远程服务凭据、后端可访问的已有模型位置、服务地址和外部程序位置。该要求不包含自动下载模型或安装计算环境。

应用的“模块管理 → 运行设置”按已安装模块的 Binding 声明展示配置。点击“保存设置”后立即用于后续 Run，并在重开应用后保留；计算进行中不能保存设置。可以逐项保存尚不完整的配置，缺少必需字段时运行在 Readiness 阶段失败，不进入 Provider。

设置保存在应用数据根的私有 `module-settings.json`，不进入 Workflow、计算参数导出或版本库。凭据只显示是否已配置；留空保留，勾选清除才删除。项目用户无需修改启动脚本或 Provider 环境变量。前端输入的路径必须是后端机器上的绝对路径；不会自动下载模型或安装环境。

## 当前配置入口

后端使用 Python 3.12，依赖由根目录 [`pyproject.toml`](../pyproject.toml)管理；Provider Python 依赖位于 `providers` 可选依赖组。源码、模型和 checkpoint 不随 Workbench 主 wheel 安装，SoluProt 使用项目维护源码构建的独立 wheel。

| 功能路线 | 应用内配置字段 | 内容 |
|---|---|---|
| Biohub ESMC、ESM-3、ESMFold2 | `credential_handle`、可选 `service_url` | API token 与服务地址；未设置地址时使用官方 SDK 默认 `https://biohub.ai`。 |
| 本地 ESM-3 | `model_snapshot_path` | 完整模型快照目录。 |
| 本地 ESMFold2 | `model_snapshot_path`、`language_model_snapshot_path` | 折叠模型与 ESMC 语言模型目录。 |
| SimpleFold 折叠及 confidence | `model_root`、`esm2_source_root`、`esm2_model_root` | 模型、Facebook ESM 源码和 ESM-2 模型目录。 |
| ProteinMPNN | `provider_root` | 包含 `protein_mpnn_utils.py` 与 `vanilla_model_weights/v_48_020.pt` 的源码根。 |
| DSSP | `dssp_binary` | mkdssp 可执行文件。 |
| SoluProt full / no-TM | `python_executable`、`site_packages_root`、`usearch_executable` | 独立运行环境的 Python、site-packages 与 USEARCH；full 另需 `perl_executable`。 |
| Protein-Sol | `source_root`、`bash_executable`、`perl_executable` | wrapper 与参考文件的源码根，以及 Bash、Perl 可执行文件。 |

每条路线分别保存设置。模块声明字段，载体负责保存与提供值；Adapter 使用这些值调用工具。Biohub 的三类 SDK 构造函数都接收设置的 `service_url` 和凭据，不改写每次计算的 Node/Binding 参数。设置值不应放入项目文件或文档。数据根与项目存储见[工作区说明](workspace.md)。

## SoluProt 当前目录布局

以下是可使用的部署布局；将实际 Python、site-packages 与 USEARCH 的绝对路径分别填写到应用设置：

```text
<provider-root>/
└── var/
    ├── environments/
    │   └── soluprot/
    │       ├── bin/python
    │       └── lib/python3.12/site-packages/
    │           ├── soluprot_core/
    │           ├── feature_scripts/
    │           ├── data/
    │           └── soluprot_assets/tmhmm-2.0d/
    └── tools/
        └── soluprot/usearch
```

将从 [`repositories/soluprot-next`](../repositories/soluprot-next/README.md)构建的 wheel 安装到上述 Python 3.12 环境，并在图示位置提供目标平台的 USEARCH 12 可执行文件。当前 Adapter 直接传入这些路径，不搜索其他项目的环境。

SoluProt wheel 当前包含 full 与 no-TM 的两套模型、参考数据库和第三方 TMHMM 文件。full 路线从已安装 wheel 选择 `Darwin_arm64` 或 `Linux_x86_64` decoder，当前不支持 Intel macOS 或 Linux ARM64；no-TM 不使用 TMHMM，仍需要 USEARCH。资产随包存在不代表其分发依据已经核实：TMHMM 随附说明限制再分发，本地文档未定位相应授权解释，详见 [SoluProt 资产说明](../repositories/soluprot-next/README.md#第三方运行资产)。

## SimpleFold 的两种资源范围

资源声明由 [`simplefold_asset_closure.py`](../modules/folding/simplefold_asset_closure.py)持有：

- 两条路线共用 `ccd.pkl`、`plddt.ckpt`、`simplefold_1.6B.ckpt`、`esm2_t36_3B_UR50D.pt`，以及 ESM-2 源码。
- 折叠路线额外使用 `simplefold_100M.ckpt` 和 `esm2_t36_3B_UR50D-contact-regression.pt`。
- 已有结构 confidence 直接运行对应评价路径，不重新折叠，不要求仅为折叠使用的上述额外文件。

Adapter 绑定已配置的目录，调用时使用临时工作目录容纳 Provider 所需工作文件。它不为资源建立新的隔离资产副本或从其他位置下载替代文件。

## Readiness 与设备

当前 Binding 的首次 Cache miss 或显式 bypass 进入 Provider 前执行 Readiness；同一 Run 中复用该 Binding 的结论。启动 Availability 是独立诊断，不替代这一运行前检查。检查限制于所需文件、目录、可执行文件、源码或包的可发现性及该路线所需设备等前提。

Readiness 不负责 Git revision、PEP 610 安装来源或模型哈希证明，也不通过运行模型来宣称科学输出已正确。调用与模型加载属于实际 Provider 入口。环境配置通过其责任边界接纳后，内部组件按契约使用，不重复开展防御性验证或搜索备用资源。

当前采用[本地 Torch 设备策略](../core/local_torch_device.py)的路线在 Linux/Windows 上使用 CUDA，在 macOS 上使用 CPU；CUDA 路线不自动退回 CPU。本地 ESMFold2 的 ESMC 使用 FP32。设备和安装形式不是新科学 Method 的自动划分依据，也不增加跨设备数值等价验证。此处描述已有策略，不扩展为未确认的用户设备切换功能。

