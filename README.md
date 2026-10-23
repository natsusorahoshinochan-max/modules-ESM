# Protein Workbench

通过画布组合模块，完成蛋白数据编辑、生成、预测、比较和筛选等研究任务。

功能范围与模块职责见下列入口。

资源受限机器的模型验证范围见 [本地模型与验证](docs/local-models.md)，接口依据和实施分工见 [验证规划](docs/research/biohub-call-plan.md)。

- 开发或审查前读 [AGENTS.md](AGENTS.md)。
- 核对行为范围读 [需求](docs/requirements.md)。
- 设计模块、数据交接和保存读 [架构](docs/architecture.md)。
- 查阅概念读 [术语](GLOSSARY.md)。

模块包安装、环境设置、React 接口及可安装样例见 [模块接入与文件交付](docs/module-authoring.md)。

## 安装

需要 Python 3.12、uv、Node.js 22.15+ 和 npm。以下命令在仓库根目录执行。

```bash
npm ci --prefix webui
uv sync --locked --extra dev --extra providers
```

本地模型位置见 [本地模型路径](docs/local-models.md)。

## 启动

后端：

```bash
PROTEIN_WORKBENCH_DATA_ROOT="$HOME/.local/share/protein-workbench" \
  .venv/bin/protein-workbench-server --host 127.0.0.1 --port 8000
```

另开终端启动前端：

```bash
npm --prefix webui run dev -- --host 127.0.0.1
```

打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。

## 教学实例与项目复制

应用默认打开教学实例。可直接编辑节点、参数、工具选择、输入和布局；草稿暂存在当前页面。使用侧栏的项目名称后点击 **Save project**，首次手动保存会创建自己的项目，教学原件继续保留。**Teaching example** 可重新打开原例。输入传输完成后才能保存；首次保存完成前教学草稿暂时锁定。

打开项目后，填写副本名称并点击 **Copy project**，将当前流程与布局及明确绑定的输入复制为独立项目。副本打开后可从未运行状态开始研究；已有运行列表与未被选作输入的结果不进入副本。

## 构建

前端：

```bash
npm --prefix webui run build
```

Python 源码包和 wheel：

```bash
.venv/bin/python -m build --no-isolation
```

产物分别位于 `webui/dist/` 和 `dist/`。

## 验证

公共应用、HTTP 文件交付、轻量模型资源锁及公共 React 交互测试：

```bash
.venv/bin/python -m pytest tests -q
WORKBENCH_PYTHON="$PWD/.venv/bin/python" npm --prefix webui test
```

前后端测试按上述顺序执行；前端默认逐个测试文件运行，`WORKBENCH_PYTHON` 指向安装了项目依赖的 Python。

真实模型验证统一使用 [模型验证入口](docs/local-models.md)，所有 worktree 共用机器级资源锁。

通过公开接口创建、运行并核对多模板多轮流程，见[长流程验收](docs/workflow-validation.md)。

首次启动附带并启用官方功能模块；在画布的序列输入入口创建单条蛋白序列，在预测节点选择本地或 Biohub ESMFold2、SimpleFold。模块设置填写已有模型路径、Python 程序或远端凭据，工具参数在节点中单独配置。结果查看器读取实际结构与自然产生的置信度文件。接口、默认值及验证入口见 [预测工具说明](modules/folding/TOOL.md)，独立读取格式见 [格式说明](modules/folding/FORMAT.md)。

完整结构使用“Import PDB or mmCIF structure”逐文件导入，选择实际构象编号或全部独立候选。运行导入节点后可查看、旋转及选择完整组分，再指定 PDB/mmCIF 导出为 ZIP；格式与操作见 [完整结构说明](modules/structure_io/FORMAT.md)。

比较时使用“Compare with an independent reference”入口导入一个 PDB 或 mmCIF，将预测输出连接至比较节点的 subject 端口。结果提供可重新打开的完整叠合；支持范围、数值含义和独立消费接口见 [比较格式](modules/structure_comparison/FORMAT.md)。

独立序列入口提供单条序列/FASTA、批量 FASTA 和含显式位置对应的序列 JSON。导入后可连接任意接受序列的操作，也可选择对象导出 FASTA；格式与来源位置见[序列说明](modules/sequence_io/FORMAT.md)。“Import existing prediction results”按清单文件键逐项绑定已有结果文件；参数与结果保留见[预测模块格式](modules/folding/FORMAT.md)。

ESMC 表征节点接受明确选择的序列输入，可选择本地原生 HF 模型或 Biohub 工具，并保存所请求的实际 embedding 与 logits。数值查看器分页显示 token、来源位置和全部实际列；配置及操作见 [ESMC 工具](modules/esmc/TOOL.md)，独立读取见 [表征格式](modules/esmc/FORMAT.md)。

显式转换路径使用“Compare through explicit structure conversion”入口，导入参考后连接预测输出至转换节点的 prediction 端口。该入口插入转换及只接受目标格式的比较节点，操作与目标格式见 [转换模块说明](modules/structure_conversion/FORMAT.md)。

使用“Save project”手动保存流程与布局；缺少输入、工具或模块的未完成流程也可保存后重开。编辑过程中不自动保存。切换或创建项目时，未保存修改可选择放弃或取消；关闭与刷新页面使用浏览器原生提醒，需要浏览器已记录页面交互。有未保存修改时，“Save and run”会先要求确认，保存失败或取消时不启动。输入文件和运行结果的接收单独持久保存，流程修改仍须手动保存。

在结果包的“Adopt into project”中选择已创建的目标项目，点击“Adopt package”，再打开目标项目选择其包作为输入。每个包的“Download ZIP”下载完整文件及文件键索引；缺少查看器时仍可使用文件链接。项目区的“Delete project”经确认删除当前项目，已采用到其他项目的包继续保留。

已有序列的独立可溶性评价支持明确选择 SoluProt full、no-TM 或 Protein-Sol；配置与数值含义见 [可溶性工具](modules/solubility/TOOL.md)，保存和独立读取见 [评价格式](modules/solubility/FORMAT.md)。

已有结构的独立置信度评价使用 SimpleFold 原几何 latent/head 调用；完整结构和来源预测分数保留，区域只选择报告的残基。输入选择、模型配置、保存及独立读取见[已有结构置信度](modules/structure_confidence/FORMAT.md)和 [SimpleFold 工具](modules/simplefold/TOOL.md)。

已有指标可在画布加入“Existing metric analysis”，选择明确对象、参考、评价及真实残基区域进行统计；数据范围、交互步骤和独立读取见[已有指标分析](modules/metric_analysis/FORMAT.md)。

独立序列与任意所选骨架的 ProteinMPNN 评价支持完整链对应、真实残基编号与插入码、独立区域及评分 mask；输入选择、数值含义和独立读取见[序列与骨架评价](modules/sequence_backbone_evaluation/FORMAT.md)。

ESM3 的补全与受约束生成节点读取当前编辑包中的 Prompt、固定/可变区域和坐标条件，可选择本地原生模型或 Biohub。失败批次保留已完成结果，使用原调用续算；原生结果与显式序列转换见 [生成格式](modules/generation/FORMAT.md)，参数、默认值和公共工具调用见 [ESM3 工具](modules/esm3/TOOL.md)。[联合生成节点](modules/generation/FORMAT.md#workbenchjoint_generation) 先完成序列，再以该序列和原条件生成结构；结构阶段失败后保留序列并从该阶段续算。

筛选使用“Filter existing evaluations”，为当前节点选择明确的候选、已有评价、条件、排序及数量上限。结果页选择所需数据包后，可使用同一模块的临时筛选操作；选择与独立读取见 [筛选格式](modules/filtering/FORMAT.md)。

集合模块提供合并、逐对象拆分、显式选择及序列/结构提取；输入与输出见[集合说明](modules/collection/FORMAT.md)。使用 **Add Map subflow** 对每个输入包执行子流程，使用 **Add Repeat subflow** 指定轮次和反馈端口。用户声明边界端口并连接内部节点，未接反馈的输入在各轮保持原值；运行区可查看各轮、各项的实际调用与结果。子流程与文件交接约定见[模块接入说明](docs/module-authoring.md)。
