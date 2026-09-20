# 批量序列导入与流程筛选合同

本文落实 WebUI 全量集成计划的 D04、D11 以及已确认的条件分组、精确手动候选引用。科学定义由各 Module Package 发布，界面仅编辑并展示相同合同。

## 独立 FASTA 记录

`protein_io.import_sequences` 消费一个不可变 Project Input，输出一个 `sequence_candidates` Candidate Collection。每条 FASTA 记录是独立 ProteinSequence；保留记录顺序，相同名称和相同序列均不去重。它与已有的 `protein_io.import_sequence`（按顺序连接记录作为一个序列）是不同的科学操作；批量入口必须选择前者。

记录的完整 header（不含 `>`）、一开始的源文件行号、从 1 开始的记录序号和文件名写入 Candidate metadata。缺失 header 允许：显示名为 `Record N`，原 header 保持空字符串。没有 header 的纯序列按一条记录处理。Candidate identity 由正常 Typed Output 发布生成，不由名称或序列去重产生。

解析支持 UTF-8、空行、序列内空白和 ASCII 小写规范化。空记录、非法氨基酸以及误置 header 报出记录与行号；一条非法记录使整个操作失败，不发布部分集合，不跳过记录。氨基酸字母表沿用 ProteinSequence 科学合同。原始输入字节保持不可变并由生产结果关联。

## Project Input 只读检查

`POST /api/v2/projects/{project_id}/inputs/{project_input_ref}:inspect` 接受 `{format: "fasta" | "pdb"}`。用户明确选择格式，不按文件扩展名、内容或 MIME 猜测。输入来自已发布的不可变 Project Input；返回 `project_id`、`project_input_ref`、该原始输入的 `content_digest` 和所选 `format`。检查不创建 Draft、Run、Candidate、Typed Output 或 Cache，也不改写已上传字节。

- FASTA 返回按源顺序的 `records`：每项包含从 **1** 开始的 `record_index`、完整 `header`、`display_name`（空 header 显示 `Record N`）、从 **1** 开始的源 `line_number` 与 `length`，以及全部记录长度之和 `total_length`。检查与批量运行共用 `protein_io` 的 FASTA parser 和单条 ProteinSequence admission；不去重。一条非法记录使整个检查返回 `project_input_invalid`，消息保留记录与行号，不返回部分成功记录。
- PDB 沿用 `protein_io` 导入的换行规范化和 ProteinStructure 的 canonical PDB admission，返回坐标记录中首次出现顺序的唯一 `chain_ids`。只检查文本和枚举 `ATOM`/`HETATM` 中明确的链身份，不解析残基对应、不推断序列、不筛除非蛋白链、不进行 Resolved Structure Residue Axis admission。因此尚未选中的核酸、配体或水链不会阻止用户选择蛋白链。后续可见的普通链选择/残基轴 Nodes 仍拥有各自的科学执行合同。

读取不存在的项目或输入分别使用已有 `project_not_found` / `project_input_not_found`。内容解释失败统一返回 HTTP 422 `project_input_invalid`，details 指明 `project_input_ref` 与显式 `format`。协议只验证请求结构；内容检查只由 `protein_io.inspection` 执行，不在 HTTP 或前端重复实现。

## 分组筛选

`selection.filter` 的 `selector_ids` 是有序、不重复的 Workflow Observation Selector ID 数组。所有 Selector 绑定同一个 Candidate 输入；`scores` 是多重输入，覆盖其全部精确 Score Collection 来源。Compiler 按 Selector 顺序解析 Score 输入，因此多个 Selector 可以引用同一 Score 来源。每个 Selector 的 Metric、Method、Context、partition、`exactly_one` 和 `missing_policy=error` 保持原科学含义。

`expression` 为后序表达式数组；界面展示可嵌套的 AND/OR 分组，保存时无损转换。比较项为 `{selector_index, operator, threshold}`，其中索引从 0 开始，比较符为 `> >= < <= == !=`，阈值使用 Metric 的 canonical unit。分组项为 `{operator: "and" | "or", operand_count: N}`，N 至少为 2，合并前 N 个表达式结果。最终必须恰好保留一个结果；索引、栈操作和全部声明 Selector 的使用由筛选操作这一合同所有者一次核验。

例如 `(A > 0.5 AND B <= 2) OR A == 0` 表达为两个比较项、一个二元 AND、第三个比较项、一个二元 OR。索引替代表达式内的 Workflow ID，保留 Result Identity 对纯 locator 重命名的不变性。

先解析所有被声明的观察值并核对完整 Candidate Data Reference，再求布尔结果；AND/OR 短路不得隐藏缺失观察值、重复观察值或旧内容的分数。`out_of_scope_policy` 相对于该 Score 来源上全部被声明 Selector 的并集；`error` 拒绝该并集外的观察值，`ignore` 明确忽略。结果保留原 Candidate 对象、身份、metadata、谱系和输入相对顺序。

排序和 Top-N 使用已有 `selection.sort` / `selection.top_k` 以及 Workflow Selection Objective 的显式 Utility Transform；权重排序使用 `selection.weighted_rank`。比较 Metric 原值不隐式转为 Utility，排序平局沿用 Candidate ID 升序。

## 手动候选选择

`selection.manual` 仅消费 Candidate Collection。参数 `selected_candidates` 保存完整 `{candidate_id, data_type_id, content_digest}` 数组，不保存行号、显示名称或序列字符串。不读取旧 Run；全部引用必须在当前输入集合中完全匹配，否则报告缺失数量及首个精确引用并使操作失败。相同 Candidate ID 但数据类型或内容摘要改变视为缺失。空选择得到空集合。结果保留当前输入顺序和原 Candidate 对象，不由勾选先后顺序排序。

## 验证

FASTA 记录定位和 Selection 不满足条件的原因属于有意公开的科学操作诊断，通过 `OperationDiagnosticError` 保留到 Run 的结构化错误消息。手动选择缺失时，消息包含数量及首个 Candidate，`details.operation_diagnostic` 保留缺失数量及首个完整引用；全部请求引用仍保存在 Commit 的节点参数中，编辑器可与输入集合核对。该诊断不随候选数量增大，遵守 Ledger 的消息及 public details 大小合同。只有操作所有者明确发布的这类诊断使用该类型；任意 Provider 异常和本地不变量错误仍使用通用执行错误，不转发异常原文。此边界不增加输入校验或重试。

用户要求全部测试在远端运行。本地只修改代码、规范与测试；远端需运行对应 protein I/O、Selection、Compiler、评分与公开协议测试，再运行 backend routine 和 deterministic-acceptance。前端需验证分组编辑保存、刷新后等价回显、精确手动引用缺失提示以及重复 FASTA 名称/序列保留。

手动 Selection 的 Binding 显式声明 `candidate_selection_consumption`。Compiler 固定 Candidate 输入和输出 Port，Ledger 为它产生与其他 Selection 同等地位的终局记录。其成功结论使用第三种互斥的 `selected_candidate_references` 证据分支，保存输出顺序的完整引用；空数组是合法空选择，区别于没有手动证据分支的 `None`。局部 Run 必须同样标记范围外的手动 Selection。

## 直接匹配与编辑投影

候选与观察的关联以完整 Candidate Data Reference 为准，不要求当前候选输入与评分时的 subject_source 是同一 Workflow 输出端点。不增加 restrict_scores 辅助节点或 population 选择。Metric、Method、Context、partition、成对引用及缺失／歧义规则保持原义。

编辑器通过 `workflow:observation-options` 读取编译器的能力投影，不在 TypeScript 重做推导。排序只匹配一次 Observation，直接计算效用；不构造临时 ScoreCollection 再匹配。Output Admission 信任内部传播操作，不反向计算输出并逐项比较。操作结果正确性由行为测试保证。

观察选项请求只提交 `workflow.nodes`、`workflow.edges` 与 `ranking`。Selector/Objective 编辑值不参与来源能力查询；未完成的 Utility、权重或筛选条件不会阻止列出可选观察。完整科学配置仍在 Commit 边界准入。

结果页从临时筛选或排序保存为流程时，设置 `out_of_scope_policy: ignore`，沿用完整原始评分集合，并只匹配明确选定的观察范围。预览展示此选择且可编辑；范围内缺失、重复或候选内容不符仍按既有合同报错。
