# Candidate–Residue Axis 精确关联：有序科学值与删除型改造设计

- 日期：2026-09-21
- 状态：已实现并验收；见 `docs/2026-09-21-exact-resolved-axis-acceptance.md`。
- 审查基线：`34c1bc47`，全项目审查后继续追踪全部直接消费者。
- 决策来源：用户明确接受破坏性 Port 替换、引用作为科学主体/父身份，以及有序 axis 主导的方案。
- 词汇：`CONTEXT.md`；历史 ADR 仅解释背景。
- 范围：Candidate-associated Resolved Structure Residue Axis 的生产、运输、消费与必需的身份准入调整。

## 1. 已确认的设计决策

1. 允许替换现有 Port 和开发期结果格式，按整体 implementation 净减少选择，不建立兼容路径。
2. 已准入的完整 Candidate Data Reference 足以确立科学主体与父 Candidate 身份；它不包含完整 Candidate 的 lineage/metadata，不能代替完整值进行原样透传。
3. resolver 输出按其输入 Candidate Collection 的顺序排列的 `subject + residue_axis`。普通消费者不再同时接收同一批结构 Candidates。
4. 真正读取 Candidate 父代信息或原样输出 Candidate 的消费者保留完整 Candidate 输入，使用一个小型精确关联 interface。

以下保持现有科学规则，不借重构另行扩张：非空 axis population、每个 population 内 Candidate ID 唯一、完整三元引用匹配、各 Method 的 cardinality、显式 Candidate Relation 顺序、Prediction Residue Axis 与 Resolved Structure Residue Axis 的区分。

## 2. 根因与证据

当前值已含完整的 subject 和 axis；axis 本身又含原始 `ProteinStructure`。多数调用方多接一个 Candidate Collection，仅为了 population、顺序或 Candidate ID。

| 位置 | 实际摩擦 |
|---|---|
| `modules/structure_transform/domain.py:128` | association constructor 按完整引用排序，丢弃源 Candidate Collection 的语义顺序 |
| `modules/proteinmpnn/implementation.py:70` | 排序引用、比较 population、`axis_for` 线性查询、再次查询 axis evidence |
| `modules/folding/implementation.py:194` | Candidate/axis/evidence 三张索引及集合覆盖检查 |
| `modules/structure_comparison/implementation.py:59` | 两侧分别 join，并另建 scientific-axis 索引 |
| `modules/structure_annotation/implementation.py:73` | 单例 Candidate 与单例 association 再次匹配 |
| `modules/structure_transform/candidate_transforms.py:119` | 提序列时重复 Candidate ID 索引与完整 reference 校验 |
| `core/catalog/builder.py:595` | Produced Observation subject 被限定为 `candidate.collection`，尽管 runtime 已消费 `candidate_data` 投影 |
| `core/execution/output_admission/candidate_identity.py:190` | 新 child 的父身份和 Score subject 都额外依赖完整 Candidate 对象 |

两个重要例外不能删：

- `structure_comparison/inserted_loop.py:360` 最终原样输出 `passing_candidates`，需要完整 Candidate 内容、lineage 和 metadata。
- `structure_comparison/three_way.py:230` 读取两种预测 Candidate 的 `parent_ids`，验证它们确实来自同一个 sequence parent。精确引用本身不证明这段 lineage。

前一轮“所有消费者都可只接 axis”的粗略推断因此收窄。减法以实际用途为依据。

## 3. 三种设计比较

| 方案 | interface | depth / locality / leverage | 代价与结论 |
|---|---|---|---|
| A：最小共享 join | 两个 AdmittedPort → 按 Candidate 顺序的 exact-reference mapping | 关联算法集中；五个 Module Packages 复用 | 删除重复 Python 算法，但所有冗余 Port、连线和 population 一致性要求仍保留 |
| B：有序科学值 | 一个有序 subject + axis Port → 直接科学计算 | 科学 population、顺序、axis 和证据投影归一个 owner；多数 join 从需求上消失 | 必须改 Node Definitions、core 身份准入、examples、结果包；采用 |
| C：操作期消费视图 | 两个 Ports → items/by_subject/one 的 typed view | 常见调用直观，隐藏多张索引 | 仍保留双输入，新增 view、索引及便利方法；相比 A 的增加未产生足够额外 leverage，不采用 |

最终采用 B，只有上述真实需要完整 Candidate 的地方保留 A 的一个窄入口。它们是不同职责，不是旧新格式并存。拒绝完整 Candidate 大聚合：现有普通消费者不用其 metadata/祖先信息，复制进去只会扩大 interface。

## 4. 目标数据流与 module 分工

```mermaid
flowchart LR
  C[Candidate Collection] --> R[resolve_candidate_residue_axes]
  N[可选 normalization associations] --> R
  R --> A[有序 subject + resolved axis]
  A --> M[MPNN / confidence / DSSP / sequence extraction]
  A --> L[alignment + explicit Candidate Relation]
  A --> J[窄 exact join]
  C --> J
  J --> E[原样透传 / 真实 lineage 检查]
  C --> S[Selection / collection operations]
  M --> O[Score Observations]
  O --> S
```

- `structure_transform` module 拥有 resolved axis 的产生、名义值合同、顺序与证据投影。
- `datatypes` 保留 Provider-independent scientific values；不放 `AdmittedPort` 或执行编排。
- `core` 通过已有 candidate-data/scientific-axis projections 理解身份，不 import extension module。
- 各 Method module 拥有自身 scientific restrictions；Provider adapter 继续只翻译其输入/输出。
- 新消费 seam 是一个完整科学 population；不是 `Any + capabilities`，不增加 registry、通用 join policy、全局缓存或新运行框架。

## 5. 有序值的完整 interface

### 5.1 形状与名字

保留已有 Python 名称、Port Type ID 和字段，避免纯改名扩大改动：

```python
@dataclass(frozen=True, slots=True)
class CandidateResolvedResidueAxisAssociation:
    subject: CandidateDataReference
    residue_axis: ResolvedStructureResidueAxis

@dataclass(frozen=True, slots=True)
class CandidateResolvedResidueAxisAssociations:
    entries: tuple[CandidateResolvedResidueAxisAssociation, ...]
```

Port Type：`structure_transform.candidate_resolved_residue_axis_associations`。

这不是兼容承诺：其顺序合同发生变化，旧开发期 Commit、Cache 与 bundled results 必须同步失效或重生成；不提供旧排序 parser。constructor 只冻结 tuples，不再排序，也不增加一套 nominal validation。

每个 entry 只存一份 subject 与一份 axis。不增加 `Candidate`、`parent_ids`、metadata、collection_id、平行 subject 列表或额外 PDB 字段。axis 中已有的 structure 是这个 entry 唯一的结构 payload。

### 5.2 不变量与唯一 owner

| 不变量 | 唯一负责处 |
|---|---|
| entries 非空；一个 population 内 Candidate ID 唯一 | 此名义 Port admission |
| subject 是 `protein.structure` 的完整 Candidate Data Reference | 此名义 Port admission；已闭合 reference 的字符/摘要语法不在消费者重验 |
| axis structure 的 canonical content digest 等于 subject digest | 此名义 Port admission |
| axis 的 layout、segments、coordinates、mask、component dispositions、normalization 科学一致 | 已有 resolved-axis admission；聚合复用该 owner |
| entries 顺序等于 resolver 输入的 Candidate Collection 顺序 | resolver producer；codec 保留该顺序 |
| projected Candidate references 与 entries 对应；axis evidence 的 source/layout/digest 来自同一 entry | 此 Port 的现有 projection implementation |
| Method 的单例、sequence/layout、CA 坐标等条件 | 相应 Method implementation |
| relation 的 membership、完整覆盖、顺序及 cardinality | 消费该 relation 的 Method module |

每个 population 仍禁止相同 Candidate ID 的两个 data versions；不把“关联键为三元组”误解为此次放宽该限制。不同 Candidate IDs 可以对应内容相同、scalar axis digest 相同的结构，二者仍是不同 subject。

### 5.3 三种身份不合并

1. `subject.content_digest`：`protein.structure` canonical bytes 的 digest。
2. `axis_reference.axis_content_digest`：独立 scalar `ResolvedStructureResidueAxis` 的 codec digest。
3. population content digest：有序 collection 的 canonical bytes digest。

改变 entries 顺序改变第 3 项，前两项各自不变。ProteinMPNN parent slot 从 entries 顺序产生；使用相同源顺序、seed、结构和参数时，保留每个 parent 的有效调用 seed 与输出顺序。由于 Node 输入集合和 Result Identity 改变，不承诺旧 Candidate ID、Run ID、Cache key 或旧字节产物相同。

### 5.4 普通消费者如何读取

不新增“已关联行”公共 transport 或每个 scalar 都带一遍 evidence 的字段。需要 evidence 时，直接读取同一个 admitted value 的 owner-defined projection：

```python
port = call.inputs["structure_residue_axes"]
associations = cast(CandidateResolvedResidueAxisAssociations, port.value)

for parent_slot, (entry, axis_reference) in enumerate(
    zip(associations.entries, port.scientific_axes, strict=True)
):
    # subject = entry.subject
    # axis = entry.residue_axis
    # axis_reference 直接来自 admission，不再次 hash、parse 或 validate。
    ...
```

此 zip 是单个 nominal value 与其自身投影的已定义关系，不是两个独立科学集合的位置猜测。该 interface 只针对一个 scalar collection Port；不把多值 Port flatten 的偶然次序升级为科学规则。

不需要 evidence 的 design/extraction 直接遍历 entries。single-axis projection 只检查 entries 数量为一，返回已有 axis；不再要求第二个 Candidate Port。

## 6. 真实完整 Candidate 消费者的窄 interface

保留一个共享入口，放在 `modules/structure_transform/candidate_axes.py`；该位置是拟新增 implementation 文件，不是新 Module Package。

```python
@dataclass(frozen=True, slots=True)
class CandidateWithResolvedResidueAxis:
    candidate: Candidate
    residue_axis: ResolvedStructureResidueAxis
    axis_reference: ResidueAxisReference


def join_candidate_residue_axes(
    candidates: AdmittedPort,
    residue_axes: AdmittedPort,
) -> Mapping[CandidateDataReference, CandidateWithResolvedResidueAxis]:
    ...
```

约定：

- 两个参数是各自已经 admitted 的 scalar collection records；不再验 nominal types、digest、内部 projection closure。
- 跨输入唯一关系要求：完整 Candidate Data Reference 的集合相等。拒绝缺失、额外或旧 digest，失败为 `ValueError`，不 repair、不截断、不 fallback。
- 以 candidate_id 在同一个可信 Candidate record 内定位完整 reference；跨 Port 一律用完整 reference。
- 返回不可变 mapping，迭代顺序来自完整 Candidate Collection；保留其筛选透传行为。axis entries 可以是另一顺序，关联不靠位置，两个顺序不必相等。
- 对 reference 与 axis 建局部索引，O(n) 时间与空间；复用输入对象，不重新读取 PDB、算 hash、做 admission。
- `one()`、`allow_extra`、`coverage`、`order`、任意 associated-value 类型参数均不加入 interface。单例要求由对应 Method 明确写出。

此处 Candidate Collection 顺序用于其真实透传工作；普通 axis-only Method 的顺序由 axis collection 拥有。顺序 owner 不交给全局 flag。

## 7. 每个 Node Type 的最终 Port 变化

保留已有 axis Port 名字；删除冗余输入，不为统一拼写重新命名所有 Ports。

| Node Type | 删除输入 | 保留的关键输入与规则 |
|---|---|---|
| `structure_transform.resolve_candidate_residue_axes` | 无 | structure_candidates + optional normalization；输出改为有序 |
| `structure_transform.extract_sequence_candidates` | structure_candidates | residue_axes；按 entries 顺序生成 child，parent 为 entry.subject.candidate_id |
| `structure_transform.project_single_residue_axis` | structure_candidates | residue_axes，恰好一项 |
| `proteinmpnn.design` | structure_candidates | structure_residue_axes + optional sequence/constraints；按 entries 产生 parent slot |
| `proteinmpnn.score` | structure_candidates | structure_residue_axes 单例 + sequence_candidates 单例；保留 sequence.parent_ids 与结构 subject 的关系 |
| `folding.simplefold_confidence` | structure_candidates | structure_residue_axes；第一项 Provider 调用前完成全 population 的 CA 条件检查 |
| `structure_annotation.dssp_compute` | structure_candidates | residue_axes 单例 |
| `structure_annotation.secondary_structure_agreement` | subjects | subject_residue_axes 单例 + references + expected + observed；保留 track/reference/layout 新关系 |
| `structure_comparison.align_pairs` | subjects、references | subject_residue_axes + reference_residue_axes + relation；relation 顺序决定 alignment 输出 |
| `structure_comparison.evaluate_inserted_loop` | 无 | subjects 为完整 Candidate 透传源；subject_residue_axes 经共享 join；references/counterparts 仍有真实范围与配对用途 |
| `structure_comparison.classify_three_way_consistency` | input_structures | input_residue_axes 单例给 source identity；sequence_parents、esmfold2_structures、simplefold_structures 保留真实 lineage；两组 prediction axes 经共享 join |

`rmsd` / `tm_score` 等只消费已有 alignment evidence 的 Nodes 不为配合本次设计额外引入 axes。它们现有 relation、subjects/references 的范围声明也不顺手重写。

三向一致性仍明确验证：sequence 的 parent 是 input axis.subject；ESMFold2/SimpleFold Candidate 的 parent 是同一 sequence Candidate。不能用“有一个 pairing”替代这个真实 lineage 事实。

## 8. core 最小改动：身份引用、完整值、声明的科学范围分开

### 8.1 父身份与 Score subject

`candidate_identity.py` 分清三种事实，使用现有 admitted inputs，不新增持久化模型：

- 输入完整 Candidate values：仅用于原样透传的完整值匹配。
- 输入完整 Candidate Data References：用于精确主体 membership 和新 child 的父身份。
- Binding 声明的 subject/reference Port：由 Observation Admission 限制本次 Metric 的科学 population。

新 child 父检查接受已准入输入引用的 Candidate ID，或同一 operation 中可解析的新输出父 Candidate；未知父、cycle 仍失败。父身份字段仍是现有 Candidate ID，不趁此次改成另一 lineage wire schema。

Fresh Score 不新增另一套全局 membership 校验。当前 `_normalized_score` → `require_exact_input_subject` → `exact_input_candidate_facts` 先要求完整 Candidate，成功后只是把相等的引用原样 `replace`。后续已有 `admit_produced_observations` 按声明 source Port 核验 subject/reference；nominal Score admission 已负责 pairwise context.subject 与 score.subject 一致。

因此删除 fresh Score 的这段重复检查与无变化的复制，保留 Score Collection identity 构造；新生成的 Score 由既有 nominal admission + Produced Observation admission 各自负责不同不变量。未声明输出、错误 Method/Context、声明范围外 subject、same-operation 尚未准入输出的 subject 仍不能通过。

Propagation 必须单独保留：`admit_produced_observations` 的 propagation 分支会提前返回，不能误删 `require_exact_propagated_subject` 的来源闭合。它可成为 propagation 专用检查，不再顺带承担 fresh Score 的准入。

父身份 membership 来自输入已准入完整引用；只在实际解析某个 parent ID 时要求它对应唯一完整 reference。多个 inputs 中相同 reference 可重复出现；同 ID 对应不同 digest 时不得 dictionary last-wins。Fresh Score 使用其声明 Port 内的完整引用，不因为另一个 Port 同 ID 的不同数据版本而被无关地拒绝。

完整值透传继续使用实际完整 Candidate 输入。只在请求复用该 identity 时检查来源与输出完整 data/lineage/metadata 相同；同 ID 有相互冲突的完整值不能任选一个。只有引用、没有完整值时，不能把新构造的对象当作原输入 Candidate 保留旧身份：拒绝这种透传身份复用；新生成的 Candidate 应使用 producer-local identity，再正常赋予新身份。

Candidate Relation 的已有传播路径保持：它当前还有从 admitted relation 输入取得 reference 的规则，不能随 fresh Score 清理被删除，也不扩成通用身份解析 framework。

### 8.2 Produced Observation 的来源声明

Catalog builder 不再要求 subject Port 的 nominal ID 一定是 `candidate.collection`；要求 exact registered Port Type 拥有现有、配对完整的 `candidate_data_projection` 和 runtime projection。继续验证 subject grain/source role、Metric、Method、axis source、multiplicity 等合同。

关键含义：这是“该声明明确选择的 Port 所投影的完整 Candidate population”，不是从任意 value 的字段猜 subject。例如 alignment evidence 的 projection 含两侧 Candidate references；若将其声明成 subject source，含义就是整个投影 population，不能偷偷只取 `.subject`。当前迁移只将 SimpleFold 与 SS agreement 的 subject source 改为各自 axes Port。

不添加 supports_subject 标志、adapter registry、按 Python 类型的分派或 `core → modules` import。reference source 本轮仍为当前 Candidate Collection 时维持现状，不为未来用途额外放宽。

保留 Builder 的 `subject_direction == "input"` 要求，不以此次重构打开同 operation 输出作为 fresh subject 的新阶段。

运行时 Observation Admission 继续检查：Score 属于**声明 Port 的完整 population**、对应 Metric/Method/Context、规定数量和 axis reference。全体输入中“认识这个 Candidate”并不等于允许任意 Metric 为它产出 Observation。声明来源内的 Candidate ID 唯一性规则继续存在；多值 evidence 投影若重复同一个 reference，不能靠全局去重偷偷变成另一个 subject population。

### 8.3 声明联动

- SimpleFold confidence：subject_port 改为 `structure_residue_axes`，axis_port 同值。
- SS agreement：subject_port 改为 `subject_residue_axes`；reference_port 继续 `references`。
- ProteinMPNN score：subject_port 仍是 `sequence_candidates`；结构 axis Port 不改名。
- selection candidate_input 继续要求 `candidate.collection`；不把 axis carrier 伪装成完整 Candidate population 的可透传值。

## 9. Selection、结果阅读与不引入的额外能力

Selection 继续从原始 Candidate 分支取完整值，从 score 分支取精确 Observation：

```text
结构 Candidates ───────────────→ Selection.candidates
      └→ resolve → confidence → Selection.scores
```

编译时 Observation capability 记录真实 axis subject_source；不伪装成原先 Candidate 输出。已查看 `selection_capabilities.py`：objective 匹配使用 Metric/Method/Context/partition，不要求 candidate_input 与 subject_source 为同一个 Port。运行期按完整 Candidate Data Reference 选择。

WebUI 已分别选择 Candidate 来源与 Score 来源，`selectionSources` 按实际名义 Port 列出完整 Candidate 输出，不需要让新 carrier 支持泛型 selection。须增加真实图回归来证实这条链，而不是只修改手写 UI fixture。

若用户要先筛选或重新排序，再执行对顺序敏感的 Method：先操作 Candidate Collection，再接 resolver。此次不提供 axis subset/reorder Node，不提供“从 axis 重建完整 Candidate”Node，也不引入跨请求 axis cache。resolver 的重复工作若成为真实需求，另行证明再设计；不预建机制。

Results 的原 Candidate 页面仍来自原始 Candidate outputs；其 sequence evidence 由完整引用关联 axis，不从 PDB/parent 猜。`published-results.ts` 当前消费同样的 entries/subject/residue_axis 字段，shape 保留；更新顺序相关 fixture 并验证行为即可，不借机实施整个 ResultBrowser 重构。

## 10. 失败位置、随机性与 evidence

| 场景 | 负责处与结果 |
|---|---|
| 原始结构/axis 不闭合、subject digest 不对应、重复 ID、空 axes | 名义 Port admission 失败 |
| axis-only Node 缺少整个必需 Port | 现有 Workflow/Run required-input 语义；不增加新校验 |
| 完整 Candidate + axes 的两个合法输入范围不等 | 共享 join 在科学计算前失败 |
| DSSP 多项、scoring 多 parent、SimpleFold 无 CA | 对应 Method 条件检查失败 |
| Relation 含范围外 subject、遗漏关系、错误 cardinality | relation 消费 Method 失败 |
| 来自 input reference 的 child parent | identity normalization 接受；新 child 仍获新身份 |
| 只有引用却试图原样透传完整 Candidate | 不获透传资格，不冒用旧身份 |
| 存储加载或 Provider 实际执行失败 | 既有真实错误语义；不加修复、fallback、retry |

不改变 Node Execution Attempt / Operation Attempt / Engine Invocation 的区分。精确关联或明确的 population 预检查应在首次科学引擎调用前完成；不把其他目前逐 parent 的 Method 检查强行改成全局预检，以免悄悄改变失败证据语义。

Cache restore 可以恢复有序值及其投影，消费者不得重新 admission。既有 nested decoder/projection 的重复 scalar validation 是前一报告的另一候选，本轮不以“缓存可信”之名添加新的 trusted/untrusted 运行双路径。

Prediction Confidence Fact / Prediction Key / Prediction Residue Axis 保持独立，不能由输出 PDB 的 resolved axis 替代。Normalization key/materialization 的现有生产流程保留，下游使用 axis 已记录的 normalization provenance。

## 11. 明确删除与保留清单

### 删除

- association constructor 的 reference canonical sorting；`axis_for` 及仅为它保留的 Protocol/测试访问。
- ProteinMPNN `_structure_candidates_with_axes`、`_reference_key`、`_ResolvedAxisAssociations`。
- SimpleFold confidence 本地 candidate/axis/evidence join；保留全 population CA 条件。
- AlignPairs 两侧 Candidate→axis 的完整覆盖 join；保留 relation→axis 的精确匹配。
- extraction、DSSP、single-axis projection、SS agreement 中平行 Candidate/axis 对齐分支。
- inserted-loop 和 three-way 的本地关联算法，改为唯一共享入口；保留它们真实 Candidate 用途。
- 表 7 中冗余输入 Ports、Workflow edges、旧合同描述、对应旧形状测试。
- Score subject 必须完整 Candidate 的额外前提；新 child 父存在性只看完整 Candidate 的额外前提。

### 保留

- scalar resolved-axis codec、axis evidence、nominal content identity。
- Candidate pass-through 的完整 data/lineage/metadata 对比。
- 当前各 Method 算法、真实 Provider adapter、序列/结构单位、masking、residue mapping、有效随机规则。
- normalization associations 与 Prediction Confidence 的独立科学语义。
- generic Candidate selection/collection 操作、不可变 Commit、durable publication。

新增 implementation 限于一个为两个真实消费者复用的小型 join module；不新增 Module Package、继承体系、抽象 adapter 或多模式 join 引擎。实施后用 diff 核实实际删除量，不用预计行数充当收益。

### 实施后的实际删除量（`git diff` 核实）

生产代码（`core/`、`modules/`）净减少：**24 个文件，+300 / −426，净 −126 行**。

| 删除项 | 位置 | 核实方式 |
|---|---|---|
| constructor 排序 | `modules/structure_transform/domain.py` `__post_init__` | `axis_for` 全仓 0 命中 |
| `axis_for` | 同上 | 同上 |
| ProteinMPNN `_structure_candidates_with_axes` / `_reference_key` / `_ResolvedAxisAssociations` | `modules/proteinmpnn/implementation.py` | `_structure_candidates_with_axes` 全仓 0 命中 |
| SimpleFold 三索引 join | `modules/folding/implementation.py` | 改为单一有序读取，CA 全 population 预检保留 |
| AlignPairs 两侧覆盖 join | `modules/structure_comparison/implementation.py` | `_axis_associations` 已删；relation→axis 精确匹配保留 |
| inserted-loop `_axes_by_subject` | `modules/structure_comparison/inserted_loop.py` | `_axes_by_subject` 全仓 0 命中 |
| extraction / DSSP / single-axis / SS agreement 平行分支 | `candidate_transforms.py`、`structure_annotation/implementation.py` | 见 §7 表 |
| fresh Score 完整 Candidate 前提 | `core/execution/output_admission/candidate_identity.py` | `exact_input_candidate_facts`、`require_exact_input_subject` 全仓 0 命中 |
| `builder.py` subject Port 名义类型限制 | `core/catalog/builder.py` | 改为要求成对 `candidate_data_projection` |

新增：`modules/structure_transform/candidate_axes.py`（1 个 join、1 个 dataclass）。

删除的 Node 输入 Port 实际为 **11 个**（§7 表：`structure_candidates` ×6、`subjects` ×2、`references` ×1、`input_structures` ×1，其中 `align_pairs` 一次删除 `subjects` 与 `references`）。

**实施期间发现并顺带修复的既有缺陷**：`tests/support/generate_workflow_stress_fixtures.py` 仍在 `selection.filter` 上写已不存在的顶层 `threshold` 参数（该节点只声明 `selector_ids` 与 `expression`）。按合同重新生成 fixture 会让 `multi_selection` 无法编译，因此生成器改为写 `expression[0].threshold`；重新生成的 `multi_selection` / `prompt_conditioning` 与提交版本一致，`multi_parent_batch` / `provider_downstream_commit` 只减少本次删除的边。

## 12. 原子迁移清单与依赖顺序

这些步骤是同一替换批次内部工作顺序，不允许任一步作为长期双轨兼容版本发布。

1. **建立行为基线**：当前 focused cases 的科学结果、parent seed/order、scalar axis identity、lineage、Selection exact-reference 行为。
2. **值与 core 身份**：有序 owner 合同、projection 顺序、父/Score 引用语义、窄 join。
3. **全部 Node consumers 与声明同时替换**：11 个相关 YAML 文件；不要只改最显眼的 5 个 Python helper。
4. **当前 Workflows 与测试迁移**：删除冗余 edges；明确 resolver 放在 order-sensitive Candidate 操作之后。
5. **结果与文档更新**：当前规格、README/例子说明、WebUI fixture、canonical bundled results。
6. **运行验收与独立审查**：通过当前 interface 验证科学行为，检查没有残留旧排序/旧输入/兼容 parser。

主要 implementation 触点：

- `modules/structure_transform/{domain.py,_candidate_association_codecs.py,candidate_transforms.py,package.py}`
- `modules/structure_transform/candidate_axes.py`（拟新增）
- `modules/proteinmpnn/implementation.py`
- `modules/folding/{implementation.py,package.py}`
- `modules/structure_annotation/{implementation.py,package.py}`
- `modules/structure_comparison/{implementation.py,inserted_loop.py,three_way.py}`
- 上述 Modules 的相关 `definitions/*.yaml`、Method 描述与 registration facts。
- `core/catalog/builder.py`、`core/execution/output_admission/candidate_identity.py`。

七个当前例子全部检查：canonical-3gb1、webui-3gb1、source-bound-1pga、source-bound-2emo、source-bound-5g53、prompt-downstream-interfaces、repository-capabilities。

生成与持久结果：`tools/generate_webui_example.py`、`tests/support/generate_workflow_stress_fixtures.py`、相关 workflow_stress fixtures；`examples/v2/webui-3gb1.results.zip` 必须按新合同重生成，不能手改五个命中字串的 JSON 后保留旧 digest/ledger。

结果包生成必须满足 `protein_workbench_public/example_results.py` 的真实安装合同：在受保护示例 Project 上执行原始完整 Workflow，active Commit 与 Draft 均等于 shipped Workflow；所有 Node 都成功且 `resolution=executed`。不能用 derived Run 或 Cache replay 拼出验收包。保留 `tests/test_webui_example_results_resource.py` 的资源检查。

旧开发期状态可失效；实施时明确废弃作用域或使用干净数据根，不直接删除用户工作目录来“清缓存”。无旧 constructor alias、迁移 parser 或新旧 Port 并存。

## 13. 验证矩阵：interface 是 test surface

| 契约 | 必需用例 |
|---|---|
| 有序 nominal value | 输入 B,A，roundtrip 仍 B,A；交换 entries 只改变 population digest，不改变 scalar axis/reference identity |
| Admission | empty、duplicate Candidate ID、同 ID 不同 digest、错误结构 digest；错误在 owner 拒绝 |
| 身份分离 | 两个不同 subjects 可共享相同结构/axis；两个主体都保留，不能按 axis digest 去重 |
| 同值投影可信 | 消费者直接使用 admission 给出的 axis_reference；不重新 hash/parse/validate |
| 真实双输入 join | 独立合法输入的 missing、extra、stale digest 分别拒绝；顺序不同仍关联正确；不向 join 输入伪造 broken AdmittedPort 要求它二次校验 |
| Parent | 仅 axes 输入的新 child 可引用 admitted subject；未知父与 cycle 仍拒绝；仅在所用 parent ID 对应不同内容时拒绝歧义 |
| Pass-through | 完整 Candidate A 与另一 Port 的同 ID/不同 digest 引用并存时，透传 A 使用其自身 record 的引用；不能 last-wins，也不重算 hash |
| Score | 仅 axes 输入可产出合法 subject Score；全局已知但不在声明 source Port 的 subject 仍拒绝；错误 Method/Context/axis 保持拒绝 |
| Projection 范围 | alignment 等含多个角色的 projection 不得被暗中当成只有一个 subject；按 Binding 明确声明的完整 population 验证 |
| ProteinMPNN | B,A parent order、派生 seed、child parent/sample order；score 单例及 sequence.parent_ids/layout |
| SimpleFold / DSSP / SS agreement | CA 全体预检、单例要求、SS8 present-pair、subject/reference 与 layout 精确关系 |
| Comparison | relation 顺序、many-to-one reference、axis evidence digest；inserted-loop 原样透传、three-way 真正 lineage |
| Selection | 原 Candidate 分支 + axes 评分分支能编译、执行、选择；旧 digest 不冒充新内容 |
| Cache / restart | 新版值的命中与重启保留 entries 顺序和 scalar identity；不依赖旧开发包兼容 |
| Current examples / WebUI | 7 个例子连线合法、bundled result 可读、结果序列证据关联不变、Selection 来源可编辑 |

当前测试应迁移或保留的重点：

- `test_structure_transform_candidate_axis_v2.py`、`test_structure_transform_v2.py`、`test_port_types_v2.py`
- `test_proteinmpnn_v2.py:1192`（顺序/精确关联）、`:2911`（多 parent child lineage）
- `test_simplefold_confidence_v2.py:1085`、`:1211`、`:1334`（evidence、顺序、缺失）
- `test_structure_annotation_v2.py:785`、`:884`（admitted axis identity、完整 participant）
- `test_structure_comparison_v2.py:168`、`:768`、`:835`、`:1076`（真实消费、旧 digest、投影、shared reference）
- canonical/source-bound examples 与相应真实 acceptance。

旧 axis-only consumers 的“双 Port 错配”测试随被删除的输入关系删除；其科学内容移到 nominal admission 或保留双输入的 join，不能继续伪造已不存在的接口。保留 Method 特有拒绝测试，不以相同检查名为由一并删除。

执行：focused pytest + `.venv/bin/python -m verification.backend routine` + `.venv/bin/python -m verification.backend deterministic-acceptance`；相关真实 ProteinMPNN、SimpleFold confidence、DSSP 与 source-bound tiers不可用 mock 替代。WebUI 按 `webui/README.md` 在远端 verification host 跑规定检查。

## 14. 完成标准与当前状态

完成标准：普通消费者不再同时收同一结构 population 的 Candidate 与 axes；只有真实 Candidate payload 用途保留平行输入；共享 join 只有一个；core 不依赖 extension；身份、单位、axis、lineage、Method 与有效随机语义通过对应验收；旧实现和开发期示例产物全部同步替换。

设计已经过科学运输方案比较、运行时身份链审查及全栈迁移审查；已据审查修正完整 Candidate 的真实例外、fresh Score 重复准入、source projection 唯一性与 bundled ZIP 的生成条件。

本轮交付是设计，不是 implementation：只更新已确认领域语义及设计文档，未改运行代码、未运行测试或真实 Provider。性能判断来自算法与数据流分析，没有 benchmark，未声称运行速度提升百分比。
