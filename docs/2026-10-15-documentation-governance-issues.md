# 当前未解决问题

本清单只维护当前需要实现对齐、范围明确或事实核实的事项。已确认要求以[当前有效决策](documentation-governance-decisions.md)为准，现行说明入口见[文档索引](README.md)。规范文字得到纠正不代表应用代码已经修改。

已解决的文字冲突和已移除的失效材料不保留为历史档案。问题 ID 用于稳定引用，因此不要求连续。文档、研究或代码中的自述不能替代实际核验；未确认事项不自动成为开发需求。

## 核验边界

代码仅只读核对。本清单使用当前源码中的静态证据，不表示已通过运行验收；没有执行测试、构建、浏览器或 Provider。Biohub 资料以固定官方快照和本地 SDK 为核查材料，未复验当前线上接口；专利法律状态与第三方分发授权未重新核验。

下列实现差异在代码修正并完成适用验证之前仍保留。代码文件链接用于定位，具体类、函数和字段比随编辑变化的行号更可靠。

## 实现待对齐

### DOC-007｜结果页仍提供已决定删除的“保存为流程”

- **要求**：删除现有结果页将条件、Top-N、勾选保存为 Workflow 节点的功能。普通筛选、查看、导出及历史结果采用仍保留。
- **当前证据**：[ResultsWorkbench](../webui/src/ResultsWorkbench.tsx)第 195–233、265、282 行仍包含节点生成与保存入口。
- **状态**：现行[结果说明](results.md)已采用当前范围，代码仍待删除对应功能；不新增跨来源合并方案。

### DOC-011｜远程 ESM3 步数范围与固定官方资料不一致

- **当前证据**：[官方 generate 快照](biohub-api-reference/v1/endpoints/generate.md)第 30、53 行限定 1–100；[序列生成声明](../modules/esm3/definitions/generate_sequence.yaml)第 56–63 行及另两种生成节点允许到 2048。
- **状态**：须按实际调用路线核对并正确声明范围，本地与远程不能混用；未复验线上行为，不能声称远端当前必然拒绝。参数开放要求见[参数审查](tool-parameter-exposure-audit.md)。

### DOC-019｜历史运行列表与历史结果采用尚未证实完整

- **要求**：运行列表可打开以前的运行；支持本项目及跨项目结果直接采用，采用后不因来源项目删除而失效。不提供跨运行候选并排查看。
- **当前证据**：[App](../webui/src/App.tsx)第 398–419 行主要读取 latest Run；项目复制或节点级重跑不能证明任意历史采用和输入独立性已提供。
- **状态**：[工作区](workspace.md)和[结果说明](results.md)已明确要求；完整入口、采用与独立持久化路径仍需核查和对齐，不仅凭 Project-local 引用认定不可跨项目使用。

### DOC-020｜用户插件管理与空载体能力尚未完整接入

- **要求**：选择模块包安装并启用，支持开关和卸载；官方与外部模块同等接入，无科学模块时载体独立可用；运行配置可在应用界面完成。
- **当前证据**：[bootstrap](../protein_workbench_public/bootstrap.py)第 24–90 行固定导入和注册功能包；[provider_environment](../protein_workbench_public/provider_environment.py)仍按具体 Binding 与工具装配环境配置。
- **缺失模块打开**：Q14 还要求保留缺失节点、连线和配置并允许打开项目；[前端 authoring](../webui/src/workflow-authoring.ts)第 155、165 行遇到未知 Node Type/Binding 仍直接抛错，缺失占位路径须一并对齐。
- **状态**：现行[架构](architecture.md)与[配置说明](provider-configuration.md)区分目标与当前固定装配。用户安装管理及通用设置未证实完整，不能以仓库目录结构限制外部模块。

### DOC-028｜Prompt 合并要求项目用户维护内部身份

- **要求**：用户选择采用区域、轨道和必要的位置对应，内部标识及映射维护由模块负责。
- **当前证据**：[PromptMergeEditor](../webui/src/PromptMergeEditor.tsx)第 112 行仍提供 `A:new.identity` 输入。
- **状态**：按[Prompt 编辑说明](prompt-editing.md)整改交互；保留用户表达所选对象与位置的能力，不把内部 ID 维护交给项目用户。

### DOC-029｜公共编辑协议直接依赖 ESM3 专用实现

- **当前证据**：[authoring_codec](../protein_workbench_public/authoring_codec.py)第 12–13、87–102 行直接导入 ESM3 Adapter、Operation 并生成 esm3_conditioning；[PromptStudio](../webui/src/PromptStudio.tsx)第 693–704 行固定展示该工具条件。
- **状态**：工具特有投影应按[架构职责](architecture.md)由模块及 Adapter 提供。可保留有用的工具兼容性展示；现有耦合不证明不能保存其他 Prompt 内容。

### DOC-030｜ProteinMPNN 功能须从头重做

- **要求**：评价关系独立于生成来源；有效的独立序列和结构可参与评价，正确满足工具输入要求。不兼容旧接口不构成保留理由。
- **当前证据**：[评分声明](../modules/proteinmpnn/definitions/score.yaml)第 3、10–15 行及[实现](../modules/proteinmpnn/implementation.py)第 264–267 行要求输入结构为序列唯一原始父结构；旧评分调用还固定部分配置。
- **状态**：当前接入不作为新规范。按[模块能力](module-capabilities.md)所列范围从头重做，不逐项修补旧接口、不伪造来源，也不自动新增未确认输出或科学证据体系。

### DOC-033｜ESMC 尚未提供所要求的实际 logits 输出

- **要求**：可选输出整序列 embedding 和实际逐位置 logits，供查看与下游使用。logits 不作为概率表述。
- **当前证据**：[esmc_adapter](../modules/esm3/esmc_adapter.py)第 44–46、64–77 行请求实际 logits 后只保留形状；[表征声明](../modules/esm3/definitions/represent_sequence.yaml)只描述 embedding 与 shape。
- **状态**：现行说明已明确差异，输出、类型、读取及界面仍需对齐。具体模块归属不由当前包名裁定，不新增分析算法。

### DOC-034｜编辑与导航路径仍自动持久化

- **要求**：仅手动保存，流程与布局一起成功；未保存退出提供保存、放弃、取消；运行前明确保存并运行。
- **当前证据**：[workspace-editor](../webui/src/workspace-editor.ts)第 218–226、269 行在接纳编辑后写入；[App](../webui/src/App.tsx)第 369–371、398–399、770 行在导航或运行路径主动保存。
- **状态**：按[工作区约定](workspace.md)修正整个保存流程，不能只改提示文案。已有共同工作区发布基础可以复用，不等于全部失败情形已验证。

### DOC-035｜运行期间未统一限制项目修改

- **要求**：同项目运行期间禁止修改，允许查看；结束或取消后才能编辑。
- **当前证据**：[App](../webui/src/App.tsx)第 741、770 行主要限制再次运行，第 474–480、659–675 行编辑回调未统一受运行锁约束。
- **状态**：按[工作区约定](workspace.md)统一落实，不将查看器切换误当作计算参数修改。本次未验证全部交互路径。

### DOC-036｜模块专用界面与结果读取仍固定分派

- **要求**：统一 React 接口，官方与外部模块同等提供编辑器及查看器；同一数据可有多个查看器，允许切换。
- **当前证据**：[App](../webui/src/App.tsx)固定导入和分派 Prompt/Selection 编辑器；[PublishedOutputs](../webui/src/PublishedOutputs.tsx)按固定类型选择展示；[published_results](../protein_workbench_public/published_results.py)第 27–32 行及 value() 固定专用读取种类。
- **状态**：后端专用读取与前端加载须一起修正，不能要求自定义数据伪装成蛋白类型。已有 Port Type 注册及编解码不等于专用界面接入完整，见[架构](architecture.md)和[结果说明](results.md)。

### DOC-037｜通用区域比较、处理与指标分析的组合覆盖不足

- **要求**：相关模块共用明确的链、残基与不连续区域表达，正确传递所选对象和位置；项目用户不维护内部映射。
- **当前证据**：[align_pairs](../modules/structure_comparison/definitions/align_pairs.yaml)第 1–16 行只接收完整轴，[轴解析声明](../modules/structure_transform/definitions/resolve_candidate_residue_axes.yaml)未提供区域选择；已有专用 inserted-loop 评价不能证明通用组合已完整覆盖。
- **状态**：按[架构](architecture.md)与[模块能力](module-capabilities.md)核对真实场景覆盖。不同表示本身不证明残基错配，不把模块内部区域处理放进载体。

### DOC-039｜ESM3 适用生成参数仍隐藏或缺乏限制依据

- **当前证据**：[Adapter](../modules/esm3/adapter.py)第 435–444 行未开放 invalid_ids 并固定 condition_on_coordinates_only；生成节点 temperature 上限 10 未找到官方依据，top_p 允许 0 而固定远程快照为 `(0,1]`；paired 两次调用共用配置。
- **状态**：按当前功能和调用路线开放适用参数，正确传入。默认温度 1 有固定 SDK 依据；远端未支持的 seed 不能伪造。细节见[参数审查](tool-parameter-exposure-audit.md)，步数范围另见 DOC-011。

### DOC-040｜ESMFold2 适用推理参数仍固定

- **当前证据**：[远程调用](../modules/folding/esmfold2_remote.py)第 77–85 行及[本地调用](../modules/folding/esmfold2_local.py)第 125–136 行固定步数、循环、dropout、mask 和 MSA 配置；[节点声明](../modules/folding/definitions/fold.yaml)第 22–44 行仅开放部分参数。
- **状态**：按各官方入口的适用条件整改，不因参数开放新增模型路线或全部输出模式；本地其他参数的适用性和默认步数依据仍需核对。见[参数审查](tool-parameter-exposure-audit.md)。

### DOC-041｜SimpleFold 的 tau 与步数范围仍受封装限制

- **当前证据**：[运行时](../modules/folding/simplefold_runtime.py)第 260–268 行固定 tau=.1；[Binding](../modules/folding/package.py)第 424–435 行将步数限制在 1–50，固定上游 CLI 公开步数及 tau，示例采用 500 步。
- **状态**：开放适用参数并移除无依据限制。tau=.1 有默认依据；不将折叠采样参数套用于不重新采样的已有结构 confidence 操作。见[参数审查](tool-parameter-exposure-audit.md)。

### DOC-042｜单条 FASTA 入口仍拼接多条记录

- **要求**：单条入口只接收一条记录，多条时提示改用批量入口。
- **当前证据**：[fasta.py](../modules/protein_io/fasta.py)第 87–89 行仍拼接记录。
- **状态**：文档已按[序列输入约定](results.md#序列输入)明确要求；单条入口及相应用例待修正，不删除正常批量功能。

### DOC-043｜随机插入残基仍受编辑限制

- **要求**：随机插入残基可像其他残基一样继续编辑、删除和作为插入锚点。
- **当前证据**：[PromptStudio](../webui/src/PromptStudio.tsx)第 236–239、422–434、681 行仍对随机残基施加交互限制。
- **状态**：按[Prompt 编辑约定](prompt-editing.md)对齐，模块维护内部对应；随机来源不是限制后续编辑的理由。

### DOC-044｜教学实例首次编辑即持久复制并保留结果引用

- **要求**：首次手动保存才创建个人项目；此前在内存中编辑，教学原件保持不变，副本不自动复制运行记录和结果。
- **当前证据**：[workspace-editor](../webui/src/workspace-editor.ts)第 229–244 行的复制路径和[后端 authoring](../core/workflow/authoring.py)第 508–519 行仍采用编辑复制及结果引用路径。
- **状态**：按[教学与项目约定](workspace.md)同时修改持久化时机和复制范围；默认教学实例仍保留。一般自动保存另见 DOC-034。

### DOC-045｜结构导入导出仍只覆盖 PDB

- **要求**：导入与导出均支持 PDB/mmCIF，工具所需表示由 Adapter 转换。
- **当前证据**：[输入检查](../modules/protein_io/inspection.py)仅提供现有格式；[结构导出声明](../modules/protein_io/definitions/structure_export.yaml)仅列 PDB，[结果导出](../webui/src/result-explorer.ts)第 86–98 行只生成 .pdb。
- **状态**：[结果说明](results.md)已区分目标与当前接口。补齐输入、转换与两条导出路径，不据此要求内部 canonical 表示必须改为 mmCIF。

### DOC-046｜现有节点级重跑不能实现批内保留与续算

- **要求**：批内保留已成功请求；一个请求用完适用重试后失败，停止剩余请求；用户可在相同输入和参数下继续失败及未开始请求，失败节点下游仍阻塞。
- **当前证据**：[折叠实现](../modules/folding/implementation.py)第 77–112 行全部请求完成后返回，[节点执行](../core/execution/node_attempt.py)第 417–468 行整体操作正常返回后发布；[失败发布](../core/execution/_node_attempt_publication.py)第 67–86 行只记录失败。[重跑派生](../core/execution/_run_runtime_derived.py)第 102–144 行按节点重跑。
- **状态**：按[执行约定](execution.md)补齐批内行为。已有原子持久化与节点级继续本身不是错误，不增加自动重试或接纳残缺响应。

### DOC-047｜科学教学实例仍成为启动必要条件

- **要求**：空载体独立可用；默认模块与教学实例仍按产品要求提供。
- **当前证据**：[bootstrap](../protein_workbench_public/bootstrap.py)第 104–130 行无条件安装科学教学 Workflow，第 142–147 行的另一分支也安装示例。
- **状态**：按[架构](architecture.md)解除特定科学模块、Workflow 对基本启动的硬依赖，不能通过取消教学实例或吞掉本地程序错误规避要求。

### DOC-050｜结果 ZIP 缺少已记录的计算参数

- **要求**：导出附带已经记录的计算参数，供离开软件后查看。
- **当前证据**：[导出 manifest](../webui/src/result-explorer.ts)第 19、110 行未包含节点或 Binding 参数；[published-results](../webui/src/published-results.ts)第 259–261 行读取 Commit 后只保留 scientific_definitions，prepareExport 未传原 Workflow 参数。
- **状态**：按[导出约定](results.md)补齐已有参数，不把定义或 Run/Commit ID 当作实际参数，不补造未记录信息或新增日志体系。

### DOC-051｜多构象选择及拆分尚未提供

- **要求**：单文件多个构象可以选取或分别拆成候选；一次只导入一个文件不限制构象数量。
- **当前证据**：[结构导入声明](../modules/protein_io/definitions/structure_import.yaml)输出单候选，[导入实现](../modules/protein_io/implementation.py)第 118–131 行整文件生成一个候选，[结构处理](../modules/structure_transform/residue_axis.py)第 98–101 行拒绝多个 MODEL。
- **状态**：按[结构输入约定](results.md#结构输入与组分)补齐选择与拆分；[结构值](../datatypes/structure.py)第 104–137 行可保留多 MODEL 原文，不能写成完全不接受此类文件。

## 范围与事实待核实

### DOC-010｜部分输入字符与长度限制的官方依据仍需核对

- **当前证据**：[共用元素规则](../modules/residue_data/elements.py)第 16 行允许 `ACDEFGHIKLMNPQRSTVWYBXZJUO`，具体工具的可表示范围不同。
- **待核实**：[模块能力](module-capabilities.md)已分别说明共用值和各工具入口的当前字符范围，但代码现状不证明全部额外限制均有官方依据。折叠入口的标准 20 字母限制、Protein-Sol 的最短 21 残基限制等仍需核对适用依据；不能以 ESM3 的限制缩小所有模块用途，也不要求工具处理其不支持字符。

### DOC-012｜原始 ESM3 研究记录的实际源码身份未独立核实

- **当前材料**：[原始 observations](biohub-api-reference/research/2026-07-21-esm3-generation-outputs/observations.json)及同目录结构数据保持原样；[数据说明](biohub-api-reference/research/README.md)限定其用途。
- **待核实**：数据内自述的源码身份不等于已经独立核实的实际执行版本。不得由此证明当前实现通过验收，不为消除不确定性改写原始数据。

### DOC-021｜all-atom 请求快照的联合类型标签尚未裁定

- **当前材料**：[fold_all_atom 快照](biohub-api-reference/v1/endpoints/fold_all_atom.md)第 40–50 行及对应 JSON 在字段路径中列出 ProteinInput 等类型名。
- **待核实**：这些是否只是展示分支标签，须核对官方原始定义，不猜测为 JSON 键。当前未提供该端点功能，不据此认定现有折叠失效；见[Biohub 说明](biohub-api-reference/product-contract-supplement.md)。

### DOC-027｜TMHMM 随附资产的分发依据未核实

- **当前证据**：[随附 README](../repositories/soluprot-next/soluprot_assets/tmhmm-2.0d/README)包含不得再分发的文字；[SoluProt 打包声明](../repositories/soluprot-next/pyproject.toml)第 47–51 行包含相关资产。
- **待核实**：实际适用的另行授权或分发依据。现行说明应客观区分代码维护归属与第三方资产权利；本清单不认定不存在其他授权，也不作法律结论。

### DOC-031｜ProteinMPNN 逐残基输出范围尚未确认

- **当前事实**：[逐残基指标定义](../modules/proteinmpnn/definitions/native_residue_nll_metric.yaml)存在，但[Provider](../modules/proteinmpnn/provider_runtime.py)第 256–262 行和公开评分节点只输出标量。
- **范围边界**：定义存在不等于项目用户可以取得逐残基数值；这是否成为重做后的额外公开输出尚未确认，不作为必须实现的新功能。现行能力说明已明确这一限制。

### DOC-032｜ProteinMPNN 采样概率的所需公开范围尚未确认

- **当前事实**：[Provider](../modules/proteinmpnn/provider_runtime.py)第 210–225 行只取 sample_out 的 S；固定上游同时返回 probs 和 decoding_order。独立 NLL 评分另有前向计算，不能称为已经丢失同一份 NLL。
- **范围边界**：工具自然产生的所需分数随结果保留，但不自动要求公开所有内部数组。重做的具体输出范围须符合已确认功能；见[模块能力](module-capabilities.md)。

### DOC-052｜非蛋白组分的查看、选取与导出完整路径待核实

- **要求**：Q36 明确支持结构中配体、金属、水、核酸等组分的查看、选择和导出；计算工具只接收其接口支持的内容，不自动新增对接等计算。
- **当前边界**：[结构检查](../modules/protein_io/inspection.py)保留原始结构并列出 ATOM/HETATM 链；[残基轴](../modules/structure_transform/residue_axis.py)只处理其专用蛋白解释范围；[结果说明](results.md#结构输入与组分)已明确完整组分操作仍需核对。
- **待核实**：从输入、显示、选择到导出的各组分覆盖，不能仅由原文保留认定全部功能完成，也不能因蛋白轴排除水或配体就断言通用结构操作丢失这些内容。此项是覆盖核查，不是已证实的数据丢失缺陷。
