# 按当前科学契约重组回归测试

- 状态：已实施并验证
- 日期：2026-09-07
- 领域词汇：`../CONTEXT.md`
- 当前科学规格：`2026-09-02-clean-scientific-data-flow-refactor-spec.md`
- 补充约束：2026-09-06 residue element admission、ESM3 conditioning Adapter、
  Workflow Commit admission 规格
- 已完成的测试基础设施：2026-09-07 Contract Test Kit、Workflow / Run test support

## 1. 范围与原则

整理以下三份按历史修复背景聚合的测试，以及明确接收其契约的 owner tests：

- `tests/test_workflow_usability_repairs_v2.py`
- `tests/test_prompt_authoring_contract_repairs_v2.py`
- `tests/test_prompt_authoring_review_regressions_v2.py`

目前没有证据支持整组删除这些文件中的科学行为测试。逐项判断保留、迁移、改写或
删除，以当前契约及等价覆盖为依据；不按文件名、历史日期或减少测试数量作判断。
当前科学、公共协议与明确架构契约继续有效。其他全仓架构检查和 Provider 测试重组
不扩展进本轮；不改变生产科学行为或新建生产 interface。

## 2. 契约归属

| 契约 | 接收 owner |
|---|---|
| primary source、source identity、target layout、轨道 edits、annotations、merge correspondence | `tests/test_prompt_authoring_recipe_v2.py` |
| Catalog 参数与公共 Prompt Document schema 一致性 | `tests/test_prompt_authoring_document_v2.py` |
| Open / Preview / Apply / Run 一致性、baseline 修复、display axis、随机 trace | `tests/test_prompt_authoring_public_v2.py` |
| ProteinPrompt SASA nominal codec 与 aggregate 语义 | `tests/test_residue_track_closure_v2.py` |
| Observed track 的 structure Candidate subject admission | `tests/test_structure_annotation_v2.py` |
| FASTA parser 只解析、来源 Port 拥有 scientific admission | `tests/test_protein_io_v2.py` |
| 2EMO normalization、residue identity、segment topology 与 masks | `tests/test_structure_transform_residue_axis_v2.py` |
| structure → resolved axis → ProteinPrompt 的跨 Node 组合 | `tests/test_prompt_structure_source_v2.py` |

现有 `tests/test_prompt_assemble_materialize_v2.py` 继续拥有 decompose / assemble
的 exact Layout 与 optional track 契约。schema、recipe、公共交互测试按实际被测
interface 归属，跨 Node 科学组合继续保留完整 Workflow journey。

## 3. 必须保留的科学覆盖

- 2EMO 的 CSH parent span、residue identity、segment topology、CA / backbone
  masks 和 normalization provenance。已有 axis owner 中等价的细节断言集中维护；
  Workflow journey 仍验证实际输出的 normalization 关联及传入 Prompt 的 Layout / values。
- 5G53 插入前后保留所有 modeled residues、四轨 values 和 optional track 缺失状态。
- primary source 不歧义；显式 source identity 与 chain layout；source 相对顺序；
  可移动的 explicit insertion；完整单调 merge correspondence；target gaps。
- absent 与 present-all-null 不同；annotation 按 Layout 定位和排序；重叠合法而完全
  重复非法；explicit / inherited / merged 三种来源路径均保留。
- SASA codec 的既有 wire normalization，以及 Observed subject 必须引用 structure。
- 来源先 admission，下游 edits 不掩盖非法来源；合法来源上的 baseline 可独立失败，
  有效候选仍可修复并 Apply；stale preview digest 阻止写入。

禁止 source residue 重排与允许 explicit inserted residue 移动是不同规则。公共
`residue_order`、`action=replace` 和普通删除不额外报告 order change 是现行契约。
`composition_id` / `overlap_policy` 的 schema 拒绝也是现行契约，继续保留负例。

## 4. 改写与删除

### 随机性通过实际 trace 验证

两次相同 seed 的 insert 操作通过公共 Open / Preview 的 `random_selections`
取得 operation index、kind 和 realized handles，再经返回 residues 的显式
handle → residue ID 关联核对实际生成 identity。验证两次操作 index 为 0 / 1、
每次生成一个不同的新 identity、生成残基实际位于候选轴中，以及相同 Document / source
重复求值的有序 identity 与 trace 稳定。保留与实际 recipe 结果的科学关联。

删除 `:masked.` 来源猜测、固定生成 ID 格式断言及仅为取得 trace 而导入的私有
`_evaluate_prompt_recipe`。现有公开 recipe 只返回 ProteinPrompt 的 interface 保持不变。

### Display axis 通过真实 Preview 验证

原四组 before / after / expected 输入全部可以用合法 Document 和 target residues
表达。通过返回的 residues 验证原预期显示顺序、identity union 无重复，以及过滤
pending-delete 后精确等于候选顺序。保留同链 tombstone 与整链删除情形，删除对私有
`PromptAuthoringService._display_axis` 的直接调用。

### 删除有证据的重复控制与诊断残留

公共回归测试中两段直接执行 `_DecomposeOperation` / `_AssembleOperation` 的控制
代码，逐条对应到现有 owner tests 后删除。公共 Preview / runtime parity 继续保留；
需要验证 aggregate 时从真实 Run 读取 Typed Output，覆盖两个 optional tracks。
移除因此产生的 `tests.test_prompt_assemble_materialize_v2` 导入。

合并两组 overlapping annotation 场景的重复 setup，保留 explicit / inherited / merged、
nested、相同区间不同 label、partial overlap，以及 Apply → Run 的有效断言。
删除 cloud-only 错误注释、print 与诊断性的条件 Apply 分支，改为明确契约断言。

## 5. 来源科学错误的明确分类

本轮补充并同步写入 September 2 科学规格的规则：上游 assembly 的轨道 Layout
不一致，以及 FASTA 来源包含非法序列字符，均使 Preview 返回 HTTP 400 structured
error。检查错误属于对应来源契约；不再接受 200 加 diagnostics 作为这两例的替代结果。

Apply 不写入 Document，实际 Run 在对应 source / assemble Node 失败。验证 Apply
拒绝时使用符合请求 schema 的请求，并核对 Draft 不变；不能仅用 malformed request
证明写入被阻止。合法来源上的无效 baseline 继续使用 `baseline_diagnostics`，有效
候选可以修复。上述分类不泛化为所有运行或 Provider 故障的 HTTP 规则。

## 6. 迁移与验证

记录原用例的接收位置；每项删除注明等价 owner 覆盖或诊断残留依据。同步迁移 fixtures、
imports、markers 与显式 verification selectors，删除三份被替代的历史文件和孤立 helpers，
不留兼容转发。优先使用现有 Workflow / Run support，科学场景与断言留在所属测试。

验证实际收集的参数化场景和原科学断言去向。重点运行上述所有接收 owner 的 focused
tests，包含两个错误分类负例、四组 Preview display 场景、随机 trace 与三种 annotation
来源，再运行：

```bash
.venv/bin/python -m verification.backend routine
.venv/bin/python -m verification.backend deterministic-acceptance
```

测试行为重写须经 Standards 与 Spec 审查。迁移不以行数下降或测试数量下降替代契约
覆盖证据；默认门禁通过不代表完整 Provider Acceptance Campaign 已执行。

逐原用例的实际去向及删除依据见 `2026-09-07-scientific-regression-test-migration.md`。
本轮 focused tests 共 140 项通过，routine 1506 项通过，deterministic-acceptance
6 项通过。Standards 与 Spec 审查均通过；35 个原用例全部具有明确去向。本轮未改
生产代码，也未执行完整 Provider Acceptance Campaign。
