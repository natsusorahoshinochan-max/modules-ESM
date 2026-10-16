# 当前未解决问题

更新日期：2026-10-16

本清单只维护当前需要实现对齐、范围明确或事实核实的事项。已确认要求以[当前有效决策](documentation-governance-decisions.md)为准，现行说明入口见[文档索引](README.md)。规范文字得到纠正不代表应用代码已经修改。

已解决的文字冲突和已移除的失效材料不保留为历史档案。问题 ID 用于稳定引用，因此不要求连续。文档、研究或代码中的自述不能替代实际核验；未确认事项不自动成为开发需求。

## 核验边界

本清单依据当前源码与固定官方接口资料记录实现差异。旧测试组件和门禁已废弃，不作为需求或交付依据，见 [AGENTS.md](../AGENTS.md#测试)。专利法律状态与第三方分发授权未重新核验。

下列实现差异在业务实现对齐之前仍保留。代码文件链接用于定位，具体类、函数和字段比随编辑变化的行号更可靠。

## 业务路径待核对

### DOC-045｜结构导出格式转换待完整核验

- **要求**：导入与导出均支持 PDB/mmCIF，工具所需表示由 Adapter 转换。
- **当前实现**：[输入检查](../modules/protein_io/inspection.py)与导入支持 PDB/mmCIF；[结构值](../datatypes/structure.py)以 text/format 保存原文。[结构导出声明](../modules/protein_io/definitions/structure_export.yaml)和[结果导出](../modules/protein_io/ui/result-explorer.ts)提供 PDB/mmCIF 目标选择；模块拥有转换逻辑，同格式保持原文，结果页通过注册的只读结果 action 调用。
- **待核对**：结果 action 与浏览器格式选择入口的完整业务路径。

### DOC-050｜结果 ZIP 的计算参数关联

- **要求**：导出附带已经记录的计算参数，供离开软件后查看。
- **当前实现**：[参数读取](../webui/src/result-parameters.ts)按输出的 producer Run 读取原 Commit，保留 Workflow 节点/Binding 参数与已保存 admitted 参数；[ZIP 导出](../modules/protein_io/ui/result-explorer.ts)以输出位置关联离线 JSON，缺少原记录明确标为 unavailable，不使用当前工作区或补造默认值。
- **待核对**：混合导出、缓存原来源及原记录缺失时的业务路径。格式及导出边界见[导出约定](results.md#导出)。

## 范围与事实待核实

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

### DOC-053｜作者残基编号与插入码的已有身份歧义

- **当前事实**：残基轴的既有字符串身份串接作者编号与插入码；`auth_seq_id=12A, ins=''` 与 `auth_seq_id=12, ins=A` 会形成相同身份。两者同时存在时轴解析失败，不任取其一。原结构仍保存、可读。
- **保全边界**：已保存 Prompt 的 target_residues 可能再次解析其原结构来源；全局改写非数字作者标签会使这些已保存编辑失效。当前保持既有身份，不加别名或旧解析器。比较/提取额外核对独立实际作者位置；不宣称消除了底层身份歧义。
- **待解决**：在保持已保存编辑与来源可用的前提下，确定无歧义身份方案。不可仅遇到文件内碰撞时更换ID，也不可盲改保存数据。
