# 首次使用与工具配置

**中文** · [English](getting-started.en.md) · [返回 README](../README.md)

先按 README 启动应用。首次启动会安装官方模块，并打开一个带序列输入的结构预测教学示例。它用于完成第一次折叠；README 截图展示的是另外搭建的多阶段工作流。

## 完成第一次折叠

### 1. 安装计算依赖

在仓库根目录执行：

```bash
uv sync --locked --extra providers
```

完成后重启后端。这个依赖组包含模型 SDK 和 PyTorch 等计算库；本地模型权重需要另行准备。

### 2. 配置 Biohub

1. 点击左上角项目名称，打开**模块管理**。
2. 展开**结构预测**，在**部署设置**中填写 **Biohub 凭据**，点击**保存设置**。默认服务地址为 `https://biohub.ai`。
3. 回到画布，在**预测结构**节点的工具下拉框选择 **ESMFold2 · Biohub**。

其他 Biohub 工具在各自的模块中配置凭据：

| 工具 | 设置所在模块 | 用途 |
|---|---|---|
| ESMFold2 · Biohub | 结构预测 | 从完整序列预测三维结构 |
| ESM3 · Biohub | ESM3 工具 | 根据已有轨道的值与空缺补全或生成蛋白质 |
| ESMC · Biohub | 序列表征 | 计算序列表征 |

模块设置用于服务连接和模型部署；候选数量、采样步骤等计算参数在节点内设置。

### 3. 保存、运行和查看

点击顶栏**保存**，将教学示例保存为自己的项目，再点击**运行**。打开**结果**，选择运行记录和节点，查看生成的三维结构及输出文件。

## 使用本地工具

在节点工具下拉框选择本地实现，并在对应模块的部署设置中填写已有资源的绝对路径。

| 工具 | 需要配置的资源 |
|---|---|
| ESMFold2 | Python 路径、ESMFold2 模型目录、ESMC 6B 语言模型目录、计算设备 |
| ESM3 | Python 路径、ESM3 模型目录、计算设备 |
| ESMC | ESMC 模型目录、计算设备；使用后端的 Python 环境 |
| ProteinMPNN | `source` 源码目录、`weights` 权重根目录、`python` 可执行文件、`device` 计算设备 |

例如，Python 路径可以填写本项目 `.venv/bin/python` 的绝对路径，模型目录填写你自己的权重位置。设备填写工具支持的 `cpu`、`cuda` 或 `mps`，根据模型大小和可用硬件选择。

各工具的资源要求见 [ESMFold2](../modules/folding/TOOL.md)、[ESM3](../modules/esm3/TOOL.md)、[ESMC](../modules/esmc/TOOL.md)、[ProteinMPNN](../modules/proteinmpnn/TOOL.md) 与 [SimpleFold](../modules/simplefold/TOOL.md)。

## 编辑与组织自己的流程

- **项目：**点击左上角项目名称，通过**新建 / 打开**管理项目。项目文件和计算结果保存在启动时设置的数据目录中；使用同一目录启动即可继续工作。
- **画布：**通过**添加节点**选择任务，拖动端口圆点接线，在节点内选择工具、展开参数。
- **Studio：**从**编辑蛋白质**节点打开 Protein Studio。五条轨道独立编辑，三维视图与轨道选区联动。完成后点击**完成并返回画布**，再保存项目。操作细节见 [Protein Studio](../modules/sequence_edit/FORMAT.md)。
- **结果：**在结果面板选择运行记录和节点，可查看、下载 ZIP，或将结果用于节点及其他项目。

## 功能与数据格式

| 功能 | 说明 |
|---|---|
| 序列导入 | [FASTA、批量序列与空缺](../modules/sequence_io/FORMAT.md) |
| 三维结构导入 | [PDB、mmCIF、链与残基选择](../modules/structure_io/FORMAT.md) |
| 蛋白质编辑 | [Protein Studio 与五条轨道](../modules/sequence_edit/FORMAT.md) |
| 生成与骨架设计 | [ESM3、ProteinMPNN 的输入输出与序列提取](../modules/generation/FORMAT.md) |
| 结构预测 | [预测结果与置信度](../modules/folding/FORMAT.md) |
| 结构比较 | [叠合、TM-score 与 RMSD](../modules/structure_comparison/FORMAT.md) |
| 评价 | [结构置信度](../modules/structure_confidence/FORMAT.md)、[可溶性](../modules/solubility/FORMAT.md)、[序列与骨架适配性](../modules/sequence_backbone_evaluation/FORMAT.md) |
| 表征 | [ESMC 输出](../modules/esmc/FORMAT.md) |
| 筛选与整理 | [指标分析](../modules/metric_analysis/FORMAT.md)、[候选集合](../modules/collection/FORMAT.md)、[筛选](../modules/filtering/FORMAT.md) |
| 格式转换 | [三维结构转换](../modules/structure_conversion/FORMAT.md) |
