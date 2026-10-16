# 当前未解决问题

本清单只维护当前需要实现对齐、范围明确或事实核实的事项。已确认要求以[当前有效决策](documentation-governance-decisions.md)为准，现行说明入口见[文档索引](README.md)。规范文字得到纠正不代表应用代码已经修改。

已解决的文字冲突和已移除的失效材料不保留为历史档案。问题 ID 用于稳定引用，因此不要求连续。文档、研究或代码中的自述不能替代实际核验；未确认事项不自动成为开发需求。

## 核验边界

本清单依据当前源码与固定官方接口资料记录实现差异。现有测试组件和门禁已废弃，不作为需求或交付依据，见 [AGENTS.md](../AGENTS.md#测试)。专利法律状态与第三方分发授权未重新核验。

下列实现差异在业务实现对齐之前仍保留。代码文件链接用于定位，具体类、函数和字段比随编辑变化的行号更可靠。

## 实现待对齐

### DOC-011｜ESM3 路线步数声明的调用链待核对

- **当前实现**：[Binding 声明](../modules/esm3/package.py)按官方远程快照限制 Biohub 1–100 步，本地正整数不套用远程上限，保留 SDK 有效步数处理。
- **待核对**：路线步数及 SDK 有效步数在当前业务调用方中的传递。

### DOC-019｜历史结果采用与来源删除独立性尚未证实完整

- **要求**：运行列表可打开以前的运行；支持本项目及跨项目结果直接采用，采用后不因来源项目删除而失效。不提供跨运行候选并排查看。
- **当前证据**：[运行历史](../webui/src/RunHistoryDialog.tsx)与[公共 Run 路由](../protein_workbench_public/http/run_routes.py)支持项目运行列表及单 Run 查看，查看选择独立于流程保存和活动运行锁。项目复制或节点级重跑不能证明任意历史采用和输入独立性已提供。
- **状态**：[工作区](workspace.md)和[结果说明](results.md)已区分历史查看与输入采用；完整采用入口及独立持久化路径仍需核查和对齐，不仅凭 Project-local 引用认定不可跨项目使用。

### DOC-020｜用户插件管理与空载体能力尚未完整接入

- **要求**：选择模块包安装并启用，支持开关和卸载；官方与外部模块同等接入，无科学模块时载体独立可用；运行配置可在应用界面完成。
- **当前证据**：[bootstrap](../protein_workbench_public/bootstrap.py)第 24–90 行固定导入和注册功能包；[provider_environment](../protein_workbench_public/provider_environment.py)仍按具体 Binding 与工具装配环境配置。
- **缺失模块打开**：[前端 authoring](../webui/src/workflow-authoring.ts)以缺失占位呈现未知 Node Type/Binding；配置保持未解释状态，已保存端口仅用于展示连线，不猜测端口契约。个人项目打开与手动保存路径已实现，缺失模块的教学副本首次保存仍依赖 Catalog 发现输入，须完善输入依赖持久化；不能猜测引用或丢失所需输入。
- **状态**：现行[架构](architecture.md)与[配置说明](provider-configuration.md)区分目标与当前固定装配。用户安装管理及通用设置未证实完整，不能以仓库目录结构限制外部模块。

### DOC-028｜Prompt 合并要求项目用户维护内部身份

- **要求**：用户选择采用区域、轨道和必要的位置对应，内部标识及映射维护由模块负责。
- **当前证据**：[PromptMergeEditor](../webui/src/PromptMergeEditor.tsx)第 112 行仍提供 `A:new.identity` 输入。
- **状态**：按[Prompt 编辑说明](prompt-editing.md)整改交互；保留用户表达所选对象与位置的能力，不把内部 ID 维护交给项目用户。

### DOC-029｜公共编辑协议直接依赖 ESM3 专用实现

- **当前证据**：[authoring_codec](../protein_workbench_public/authoring_codec.py)第 12–13、87–102 行直接导入 ESM3 Adapter、Operation 并生成 esm3_conditioning；[PromptStudio](../webui/src/PromptStudio.tsx)第 693–704 行固定展示该工具条件。
- **状态**：工具特有投影应按[架构职责](architecture.md)由模块及 Adapter 提供。可保留有用的工具兼容性展示；现有耦合不证明不能保存其他 Prompt 内容。

### DOC-033｜ESMC 尚未提供所要求的实际 logits 输出

- **要求**：可选输出整序列 embedding 和实际逐位置 logits，供查看与下游使用。logits 不作为概率表述。
- **当前证据**：[esmc_adapter](../modules/esm3/esmc_adapter.py)第 44–46、64–77 行请求实际 logits 后只保留形状；[表征声明](../modules/esm3/definitions/represent_sequence.yaml)只描述 embedding 与 shape。
- **状态**：现行说明已明确差异，输出、类型、读取及界面仍需对齐。具体模块归属不由当前包名裁定，不新增分析算法。

### DOC-036｜模块专用界面与结果读取仍固定分派

- **要求**：统一 React 接口，官方与外部模块同等提供编辑器及查看器；同一数据可有多个查看器，允许切换。
- **当前证据**：[App](../webui/src/App.tsx)的 Selection 已改为模块声明的 React 编辑器入口，外部包使用同一发现和资源接口（见[模块 UI 契约](module-ui.md)）；Prompt 编辑器尚有固定分派；[PublishedOutputs](../webui/src/PublishedOutputs.tsx)按固定类型选择展示；[published_results](../protein_workbench_public/published_results.py)第 27–32 行及 value() 固定专用读取种类。
- **状态**：后端专用读取与前端加载须一起修正，不能要求自定义数据伪装成蛋白类型。已有 Port Type 注册及编解码不等于专用界面接入完整，见[架构](architecture.md)和[结果说明](results.md)。

### DOC-037｜通用区域比较、处理与指标分析的组合覆盖不足

- **要求**：相关模块共用明确的链、残基与不连续区域表达，正确传递所选对象和位置；项目用户不维护内部映射。
- **当前证据**：[align_pairs](../modules/structure_comparison/definitions/align_pairs.yaml)第 1–16 行只接收完整轴，[轴解析声明](../modules/structure_transform/definitions/resolve_candidate_residue_axes.yaml)未提供区域选择；已有专用 inserted-loop 评价不能证明通用组合已完整覆盖。
- **状态**：按[架构](architecture.md)与[模块能力](module-capabilities.md)核对真实场景覆盖。不同表示本身不证明残基错配，不把模块内部区域处理放进载体。

### DOC-039｜ESM3 参数接入的调用链待核对

- **当前实现**：`invalid_ids`、坐标条件开关与各路线采样设置已由 Binding 声明并传给 Adapter；两阶段分别配置，Biohub 不声明无效 seed。默认温度 1 保留固定 SDK 依据。
- **待核对**：当前调用方、示例与参数记录是否完整对齐官方接口，见[参数审查](tool-parameter-exposure-audit.md)。

### DOC-040｜ESMFold2 参数接入的调用链待核对

- **当前实现**：[Binding](../modules/folding/package.py)已声明六项适用推理参数，由远程和本地 Adapter 分别传入官方接口；范围、默认值和 null 语义按各路线区分。未展示标准本地模型实际忽略的 sampler overrides。
- **待核对**：非默认参数的调用方与官方接口语义，见[参数审查](tool-parameter-exposure-audit.md#esmfold2-当前参数接入与适用范围)。

### DOC-041｜SimpleFold 折叠参数已接入

- **当前实现**：[Binding](../modules/folding/package.py)公开 tau 与无额外上限的正整数步数，默认值分别为固定官方 CLI 的 0.1 和 500；[运行时](../modules/folding/simplefold_runtime.py)原样传入官方 wrapper。
- **范围**：独立 confidence 操作不新增不适用的采样参数，见[参数审查](tool-parameter-exposure-audit.md)。

### DOC-045｜结构导出格式转换待完整核验

- **要求**：导入与导出均支持 PDB/mmCIF，工具所需表示由 Adapter 转换。
- **当前实现**：[输入检查](../modules/protein_io/inspection.py)与导入支持 PDB/mmCIF；[结构值](../datatypes/structure.py)以 text/format 保存原文。[结构导出声明](../modules/protein_io/definitions/structure_export.yaml)和[结果导出](../webui/src/result-explorer.ts)提供 PDB/mmCIF 目标选择；模块拥有转换逻辑，同格式保持原文，结果页通过注册的只读结果 action 调用。
- **待核对**：结果 action 与浏览器格式选择入口的完整业务路径。

### DOC-046｜跳过批内成功请求的主动续算仍缺

- **要求**：批内保留已成功请求；一个请求用完适用重试后失败，停止剩余请求；用户可在相同输入和参数下继续失败及未开始请求，失败节点下游仍阻塞。
- **当前实现**：[折叠](../modules/folding/implementation.py)与 [ESM3](../modules/esm3/implementation.py)在已定义失败时保留完成请求，联合生成也保留结构失败前已完成的序列；[失败发布](../core/execution/_node_attempt_publication.py)持久发布保留输出和失败结论，不写成功缓存或传给下游。[重跑派生](../core/execution/_run_runtime_derived.py)仍按节点重跑。
- **状态**：Q41 跳过成功请求的主动续算接口仍未完成，不增加自动重试或接纳残缺响应。

### DOC-047｜空载体生产启动与项目使用路径待核对

- **要求**：空载体独立可用；默认模块与教学实例仍按产品要求提供。
- **当前实现**：[bootstrap](../protein_workbench_public/bootstrap.py)读取安装清单，空 Catalog 不安装教学项目；有教学文件且所需节点与 Binding 存在时才安装，编译错误不被吞掉。前端无教学项目时可进入个人项目或创建入口。
- **待核对**：空载体与应用内模块管理的完整业务路径；保留默认教学入口、原件保护及首次手动保存副本行为。

### DOC-050｜结果 ZIP 的计算参数关联

- **要求**：导出附带已经记录的计算参数，供离开软件后查看。
- **当前实现**：[参数读取](../webui/src/result-parameters.ts)按输出的 producer Run 读取原 Commit，保留 Workflow 节点/Binding 参数与已保存 admitted 参数；[ZIP 导出](../webui/src/result-explorer.ts)以输出位置关联离线 JSON，缺少原记录明确标为 unavailable，不使用当前工作区或补造默认值。
- **待核对**：混合导出、缓存原来源及原记录缺失时的业务路径。格式及导出边界见[导出约定](results.md#导出)。

### DOC-051｜多构象选择及拆分尚未提供

- **要求**：单文件多个构象可以选取或分别拆成候选；一次只导入一个文件不限制构象数量。
- **当前证据**：[结构导入声明](../modules/protein_io/definitions/structure_import.yaml)输出单候选，[导入实现](../modules/protein_io/implementation.py)第 118–131 行整文件生成一个候选，[结构处理](../modules/structure_transform/residue_axis.py)第 98–101 行拒绝多个 MODEL。
- **状态**：按[结构输入约定](results.md#结构输入与组分)补齐选择与拆分；[结构值](../datatypes/structure.py)第 104–137 行可保留多 MODEL 原文，不能写成完全不接受此类文件。

## 范围与事实待核实

### DOC-053｜浏览器退出三项选择仍需产品裁定

- **要求**：Q13 禁止自动保存，未保存退出时提供保存后退出、放弃和取消；Q17 的后端 Run 生命周期独立。
- **当前证据**：[App](../webui/src/App.tsx) 的应用内 `askUnsaved('leave')` 提供三项，浏览器 `beforeunload` 处理器仅请求原生确认。[官方限制、数据影响与可行选择](workspace.md#浏览器退出边界与未决要求)已核实，原生确认不能添加保存动作，也不保证所有关闭路径都会触发。
- **未决边界**：是否批准网页关闭/刷新仅提供尽力原生提醒、需取消离开后手动保存的例外，或另行扩展可控窗口的宿主形态。两者均未获批准；不得将技术限制写成新需求。
- **交付与验收**：[#123](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/123)只交付核实结论；[#124](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/124)须保留 Q13 浏览器部分未完成的结论，待产品裁定。应用内退出选择不等同于浏览器关闭行为。

### DOC-010｜部分输入字符与长度限制的官方依据仍需核对

- **当前证据**：[共用元素规则](../modules/residue_data/elements.py)第 16 行允许 `ACDEFGHIKLMNPQRSTVWYBXZJUO`，具体工具的可表示范围不同。
- **已核实**：[输入限制核实](tool-input-restrictions.md)记录 Protein-Sol 官方入口确实要求过滤后至少21个标准残基；当前拒绝非标准字符避免上游静默删除。ESM-3 SDK 词表和 SoluProt-next 自身 Provider 契约亦已区分。
- **待核实**：折叠三条路线标准20种检查的完整依据、Biohub ESMC 特殊字符语义仍未证实；词表包含未知类型不等于任意特殊残基可原样通过完整计算。不能以某一工具限制缩小所有模块用途，也不猜测转换。

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
