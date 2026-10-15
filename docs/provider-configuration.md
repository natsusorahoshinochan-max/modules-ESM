# Provider 配置

本文说明后端目前如何找到服务凭据、模型、程序和运行环境。节点的温度、步数等计算参数见[参数开放审查](tool-parameter-exposure-audit.md)；模块职责见[模块能力](module-capabilities.md)。

## 应用内设置要求与当前状态

[Q47](documentation-governance-decisions.md#模块运行配置入口q47)要求提供应用内模块设置：配置项由模块声明，载体负责展示、保存和提供给模块；模块负责使用。项目用户应能配置远程服务凭据、后端可访问的已有模型位置、服务地址和外部程序位置。该要求不包含自动下载模型或安装计算环境。

当前应用内模块设置尚未实现。现有启动入口从后端进程环境变量生成 Binding 配置，详见 [`provider_environment.py`](../protein_workbench_public/provider_environment.py)。下列变量及目录结构是当前部署方法，不是要求未来项目用户编辑环境变量的产品规范。前端选择的本地路径不能直接等同于后端可访问路径。

## 当前配置入口

后端使用 Python 3.12。安装依赖由根目录 [`pyproject.toml`](../pyproject.toml)及锁文件管理；ESM 与 SimpleFold Python 依赖位于 `providers` 可选依赖组。Provider 源码、模型和 checkpoint 不随 Workbench 主 wheel 安装；SoluProt 使用从项目维护源码构建的独立 wheel。

所有配置路径必须是后端机器上的绝对路径；入口展开 `~`，不以工作目录猜测资源位置。只配置所选功能实际需要的资源。

| 功能路线 | 当前环境变量 | 路径所指内容 |
|---|---|---|
| Biohub ESMC、ESM-3、ESMFold2 | `PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE` | 私有凭据文件，入口读取后提供 credential handle。 |
| 本地 ESM-3 | `PROTEIN_WORKBENCH_ESM3_MODEL_ROOT` | SDK 使用的完整模型快照目录。 |
| 本地 ESMFold2 | `PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT`、`PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT` | 折叠模型与 ESMC 语言模型目录，必须成对配置。 |
| SimpleFold 折叠及已有结构 confidence | `PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT`、`PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT`、`PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT` | SimpleFold 模型、可导入的 Facebook ESM 源码、ESM-2 模型目录；三个入口必须一起配置。 |
| ProteinMPNN | `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT` | 当前要求包含 `protein_mpnn_utils.py` 与 `vanilla_model_weights/v_48_020.pt` 的源码根。该配置描述现有实现，后续功能按当前决定重做。 |
| DSSP | `PROTEIN_WORKBENCH_MKDSSP_BINARY` | 当前支持的 mkdssp 可执行文件。 |
| SoluProt full / no-TM | `PROTEIN_WORKBENCH_SOLUPROT_ROOT` | 下节定义的独立运行环境与外部 USEARCH 根目录。 |
| Protein-Sol | `PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT` | 包含已接入 wrapper、Perl 脚本与参考文件的源码根；所需文件由 [Adapter](../modules/solubility/protein_sol.py)列明。 |

SoluProt full 还从后端 `PATH` 解析 Perl；Protein-Sol 从 `PATH` 解析 Bash 和 Perl。Biohub 凭据文件须由当前后端用户拥有、仅该用户可读，具体格式及检查由[凭据读取边界](../core/provider_support.py)管理。不要把凭据值写入文档、项目文件或版本库。

当前 CLI 会构造这些 Binding 配置；普通部署不需要另写调用 `create_application(...)` 的启动程序。服务器保持单用户、loopback 访问边界。数据根与项目存储参见[工作区说明](workspace.md)。

## SoluProt 当前目录布局

`PROTEIN_WORKBENCH_SOLUPROT_ROOT` 指向下列父目录，而不是直接指向虚拟环境：

```text
<PROTEIN_WORKBENCH_SOLUPROT_ROOT>/
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

Readiness 不负责 Git revision、PEP 610 安装来源或模型哈希证明，也不通过运行模型来宣称科学输出已正确。调用与模型加载属于实际 Provider 入口；真实 Provider 验证按[后端验证规范](backend-verification.md)。环境配置通过其责任边界接纳后，内部组件按契约使用，不重复开展防御性验证或搜索备用资源。

当前采用[本地 Torch 设备策略](../core/local_torch_device.py)的路线在 Linux/Windows 上使用 CUDA，在 macOS 上使用 CPU；CUDA 路线不自动退回 CPU。本地 ESMFold2 的 ESMC 使用 FP32。设备和安装形式不是新科学 Method 的自动划分依据，也不增加跨设备数值等价验证。此处描述已有策略，不扩展为未确认的用户设备切换功能。

开发中的测试、构建和 Provider 验证只能在指定远端验证机执行，并遵循完整[执行政策](backend-verification.md#execution-policy)。用户部署路径由其后端环境决定，不能用验证机的私有绝对路径代替。
