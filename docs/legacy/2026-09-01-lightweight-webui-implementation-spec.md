# Protein Workbench 轻量 WebUI 首个实现切片规格

- **状态**：`ready-for-agent`
- **日期**：2026-09-01
- **交付形式**：本地 Markdown 规格，不发布到 issue tracker
- **目标用户**：不写代码的蛋白质研究人员
- **交付目标**：建立在现有后端与 public v2 protocol 上的简单、轻量、可运行 WebUI
- **产品功能基线**：`2026-08-29-webui-functional-spec.md`

## Problem Statement

Protein Workbench 已经拥有可执行蛋白质设计 Workflow、ProteinPrompt authoring、Run、Candidate、
Score Observation、结构比较、Selection 和结果证据，但不写代码的蛋白质研究人员无法直观使用
这些能力。他们需要一个图形界面来连接或断开 Node Instance、调整参数、编写 ProteinPrompt、
运行 Workflow，并查看 Candidate 的结构、分数与谱系。

过去的前端已经退役。当前项目需要的是现有后端的一层轻量图形界面，而不是新的应用平台、
第二套科学模型或前端专用后端。首个实现必须优先证明一个真实、可修改、可运行、可查看结果的
端到端研究过程，不能只交付互不连通的页面外壳。

## Solution

建立一个单页 WebUI，直接消费现有 public v2 protocol 和 active Catalog。用户启动后直接进入一个
完整的 3GB1 局部重设计示例 Workflow；Node Instance 采用 Blender 风格的可收起卡片，参数在卡片
内部编辑。用户也可以新建空白画布并自行搭建 Workflow。

“编写 ProteinPrompt”作为 Specialized Composition 从画布进入专用 Prompt Studio。Prompt Studio
以残基矩阵为主要编辑表面，允许用户从空白、FASTA、PDB 或已有 ProteinPrompt 开始，并直观编辑
sequence、coordinates、secondary structure、absolute SASA 和 function annotations。科学身份、
残基重新对齐和 materialized graph 继续由后端拥有。

首个实现切片必须闭合以下默认研究旅程：

```text
3GB1 ProteinPrompt composition
→ ESM-3 生成 7 个 Candidate
→ 按 ESM-3 mean-residue pLDDT 选择 Top 4
→ ESMFold2 折叠 4 个 Candidate
→ mean-residue pLDDT 50% + 相对各自 ESM-3 父结构的 TM-score 50%，选择 Top 2
→ ProteinMPNN 为每个父结构生成 3 条序列，共 6 条
→ ESMFold2 折叠 6 条序列
→ mean-residue pLDDT 50% + 相对各自 ProteinMPNN 输入父结构的 TM-score 50%，选择 Top 3
```

默认示例携带一组由真实后端 Workflow 产生并保留完整 provenance 的已完成结果，使用户无需先等待
模型运行便能检查谱系、分数和结构。所有示例参数都是可修改的默认值。除明确冻结的数量、Top-N
和权重外，参数来自 active Catalog 中相应 Node 与 Execution Binding 的公开参数合同默认值。

本规格只定义首个可用实现切片。已完成的八个原型仍是后续功能与视觉方向的依据，但不会为了
一次交付而把全部高级项目管理、合并、对齐和结构编辑功能同时塞入首个切片。

## User Stories

1. As a protein researcher, I want the WebUI to open directly on a complete example Workflow, so that I can understand the product without reading code or a tutorial.
2. As a protein researcher, I want the full canvas to appear without a walkthrough overlay, so that I can immediately inspect and manipulate the Workflow.
3. As a protein researcher, I want the example to use 3GB1 in a scientifically explicit design task, so that the example represents a real protein-design workflow rather than decorative sample data.
4. As a protein researcher, I want the example to include completed results, so that I can inspect the outcome before spending time or compute on a new Run.
5. As a protein researcher, I want bundled results to show the exact Prompt, parameters, Method, lineage, and Run source that produced them, so that I can interpret them correctly.
6. As a protein researcher, I want every example parameter to be adjustable, so that the example is a starting point rather than a fixed demonstration.
7. As a protein researcher, I want the immutable example to remain unchanged, so that I can always return to a known starting point.
8. As a protein researcher, I want my first edit to create a personal copy without an interrupting dialog, so that experimentation feels immediate.
9. As a protein researcher, I want the bundled result to remain visible after my first edit and be labelled as coming from the earlier Workflow, so that I do not confuse old evidence with my modified Workflow.
10. As a protein researcher, I want to create an empty canvas, so that I can build a Workflow from scratch.
11. As a protein researcher, I want to reopen a saved personal Project, so that I can continue my work later.
12. As a protein researcher, I want to search my personal Projects by name, so that I can find prior work without browsing directories.
13. As a protein researcher, I want the current Project identity and save state to remain visible, so that I know which work I am changing.
14. As a protein researcher, I want personal Workflow Draft changes to save automatically, so that normal editing does not require repeated manual saves.
15. As a protein researcher, I want Workflow scientific content and temporary canvas state to remain distinguishable, so that visual layout does not masquerade as science.
16. As a protein researcher, I want Node Instances to appear as spatial cards, so that I can understand the flow through position and connections.
17. As a protein researcher, I want every Node Instance to open with parameter groups collapsed, so that a large Workflow remains readable.
18. As a protein researcher, I want to expand only the parameter group I need, so that unrelated parameters do not crowd the canvas.
19. As a protein researcher, I want to collapse an entire Node Instance to its name, so that I can review the overall Workflow structure.
20. As a protein researcher, I want a collapsed running Node Instance to show status beside its name without expanding, so that execution does not disrupt my canvas.
21. As a protein researcher, I want parameters to be edited inside the Node Instance card, so that I do not have to match a distant property panel to the selected node.
22. As a protein researcher, I want parameter values to display their scientific units, so that I do not misinterpret numbers.
23. As a protein researcher, I want available controls to match the parameter type, so that numbers, choices, booleans, and bounds are easy to edit.
24. As a protein researcher, I want model choice to appear inside the scientific-operation node, so that I choose how an operation is performed without replacing the operation itself.
25. As a protein researcher, I want one “预测蛋白质结构” operation with an ESMFold2, SimpleFold, or other available model selector, so that each model does not create a separate conceptual node.
26. As a protein researcher, I want saved model choices to remain fixed until I change them, so that reopening a Workflow never silently changes its science.
27. As a protein researcher, I want an unavailable saved model to remain visible with a clear reason, so that the interface does not silently substitute another model.
28. As a protein researcher, I want model-specific parameters to be remembered when I switch models, so that trying another model does not erase my previous settings.
29. As a protein researcher, I want to add Node Instances by dragging from a Palette, so that building a Workflow feels direct.
30. As a protein researcher, I want to add Node Instances by searching from empty canvas space, so that I can work quickly without scrolling a long Palette.
31. As a protein researcher, I want the Palette to classify operations by research purpose, so that I can find an operation by what I want to accomplish.
32. As a protein researcher, I want to switch the same Palette to package or model-provider classification, so that I can locate familiar scientific software.
33. As a protein researcher, I want only one classification scheme displayed at a time, so that the Palette remains simple.
34. As a protein researcher, I want search to cover all ordinary Node Types and Specialized Compositions, so that classification never hides a usable operation.
35. As a protein researcher, I want managed Prompt composition members excluded from normal search and Palette results, so that I do not accidentally construct an invalid partial Prompt composition.
36. As a protein researcher, I want to connect an output Port to a compatible input Port by dragging a line, so that Workflow construction follows Blender-like interaction.
37. As a protein researcher, I want compatible input Ports highlighted while dragging, so that I can see valid destinations before dropping.
38. As a protein researcher, I want incompatible Ports to reject the connection, so that I receive immediate authoring feedback.
39. As a protein researcher, I want a new connection to replace an existing connection on a single-input Port, so that rewiring takes one action.
40. As a protein researcher, I want to disconnect an edge with Delete or Backspace, so that cleanup follows familiar editor behavior.
41. As a protein researcher, I want to disconnect an edge by dragging it from an input Port to empty canvas space, so that mouse-only editing is supported.
42. As a protein researcher, I want to select and delete one or more Node Instances without a confirmation dialog, so that canvas editing stays fast.
43. As a protein researcher, I want deleting a Node Instance to remove its connected edges, so that the canvas does not retain broken visual links.
44. As a protein researcher, I want Ctrl/Cmd+Z to restore deleted Node Instances and their edges, so that immediate deletion remains recoverable.
45. As a protein researcher, I want multi-step undo for node creation, deletion, movement, connection, disconnection, parameters, and model choices, so that I can safely explore.
46. As a protein researcher, I want to copy and paste selected Node Instances with their internal edges and parameters, so that I can reuse a Workflow fragment.
47. As a protein researcher, I want external edges excluded from a copied fragment, so that the pasted fragment can be reconnected deliberately.
48. As a protein researcher, I want copying a ProteinPrompt composition to create a complete new composition, so that no managed member is shared accidentally.
49. As a protein researcher, I want the “编写 ProteinPrompt” entry to open a dedicated editor, so that complex Prompt work is not compressed into a small node card.
50. As a protein researcher, I want to create a blank single-chain or multi-chain ProteinPrompt, so that ESM-3 design does not require a template PDB.
51. As a protein researcher, I want to start a ProteinPrompt from FASTA, so that an existing sequence can become conditioning input.
52. As a protein researcher, I want to start a ProteinPrompt from selected PDB chains, so that existing structures can provide sequence and coordinates.
53. As a protein researcher, I want to reopen an existing ProteinPrompt with all of its content, so that saved conditioning is editable.
54. As a protein researcher, I want sequence, coordinates, secondary structure, absolute SASA, and function annotations visible in one residue-aligned workspace, so that I can understand the Prompt as one object.
55. As a protein researcher, I want SASA values displayed in Å², so that absolute accessibility is never confused with relative accessibility.
56. As a protein researcher, I want function annotations displayed as intervals rather than scalar cells, so that their range semantics remain visible.
57. As a protein researcher, I want the residue matrix to remain the primary Prompt editing surface, so that I retain global sequence context while editing.
58. As a protein researcher, I want a synchronized 3D structure view whenever coordinates exist, so that spatial and residue-level selections stay connected.
59. As a protein researcher, I want the 3D area to collapse when no coordinates exist, so that the interface does not show a fabricated structure or waste space.
60. As a protein researcher, I want to select one residue, one interval, or multiple non-contiguous intervals, so that scientific regions can be edited together.
61. As a protein researcher, I want selection synchronized between the residue matrix and structure viewer, so that I can locate the same region in sequence and space.
62. As a protein researcher, I want to preserve, specify, Mask, insert, and delete residues through visible domain actions, so that I never edit an internal ResidueLayout.
63. As a protein researcher, I want inserted residues to begin with either explicit sequence values or Mask values, so that insertion intent is unambiguous.
64. As a protein researcher, I want sequence and coordinate masks to be independent, so that I can redesign sequence, structure, or both.
65. As a protein researcher, I want layout changes to realign every present track and function interval together, so that the Prompt remains residue-consistent.
66. As a protein researcher, I want all consequences of an insertion or deletion shown before applying it, so that I can see what values or annotations will change.
67. As a protein researcher, I want source, current, changed, cleared, inserted, and pending-delete states to be distinguishable, so that I can audit a Prompt edit.
68. As a protein researcher, I want one current preview of my pending Prompt changes, so that keyboard and button edits do not create competing drafts.
69. As a protein researcher, I want all Prompt format diagnostics returned together and linked to residues or intervals, so that I can correct problems efficiently.
70. As a protein researcher, I want a valid sparse Prompt to be saveable, so that unspecified content is not treated as an error.
71. As a protein researcher, I want model incompatibility to block only the incompatible Run and not damage my ProteinPrompt, so that scientific content remains intact.
72. As a protein researcher, I want saving ProteinPrompt changes to show a normalized final preview before confirmation, so that I know exactly what enters the Workflow Draft.
73. As a protein researcher, I want cancelling Prompt Studio to leave the Workflow unchanged, so that exploratory edits are safe.
74. As a protein researcher, I want unsaved Prompt changes detected when I leave, so that I can save, discard, or continue editing deliberately.
75. As a protein researcher, I want the default 3GB1 Prompt to preserve the original sequence and coordinates outside A37–A41, so that most of the scaffold remains conditioned.
76. As a protein researcher, I want A37, A38, A40, and A41 sequence values masked, A39 deleted, and two masked residues inserted between the original A38 and A40, so that the example demonstrates local loop redesign and length change.
77. As a protein researcher, I want original coordinates in A37–A41 masked and inserted residues to have no coordinates, so that ESM-3 generates the redesigned region rather than copying its original geometry.
78. As a protein researcher, I want the example secondary structure, SASA, and function annotations left empty, so that the example stays focused on sequence and coordinates.
79. As a protein researcher, I want ESM-3 to generate both sequence and structure Candidates for the example, so that subsequent confidence and structural-consistency screening are meaningful.
80. As a protein researcher, I want to run the entire Workflow, so that I can execute the full design experiment.
81. As a protein researcher, I want to run only through a selected Node Instance, so that I can inspect an intermediate scientific result.
82. As a protein researcher, I want to continue from a selected Node Instance when reusable upstream results exist, so that I do not repeat unaffected computation.
83. As a protein researcher, I want the canvas to highlight the exact execution range before a local Run, so that I know which Node Instances will execute.
84. As a protein researcher, I want a Run summary listing scope, models, major parameters, generation counts, randomness, and blockers, so that I can confirm an expensive operation before it starts.
85. As a protein researcher, I want blockers linked to their Node Instance or ProteinPrompt position, so that I can fix the real source of the problem.
86. As a protein researcher, I want waiting, running, succeeded, failed, cancelled, and not-executed states shown on the canvas, so that I can understand Run progress spatially.
87. As a protein researcher, I want an independent Workflow branch to continue if another branch fails, so that one failure does not discard unrelated work.
88. As a protein researcher, I want dependent downstream Node Instances marked as not executed after an upstream failure, so that missing results are explained.
89. As a protein researcher, I want to correct a failed operation and continue from it, so that completed unaffected results are reused.
90. As a protein researcher, I want to cancel the whole Run while preserving completed results, so that stopping future work does not erase evidence already produced.
91. As a protein researcher, I want only the most recent Run presented in the initial interface, so that Run navigation stays simple.
92. As a protein researcher, I want a Candidate table, structure viewer, sequence, scores, and lineage kept in sync, so that I can inspect one scientific subject consistently.
93. As a protein researcher, I want parent ESM-3 structures, ProteinMPNN child sequences, and refolded structures displayed as a lineage, so that I can trace every final Candidate.
94. As a protein researcher, I want score values labelled by Metric Definition, Method, unit, direction, and Observation Context, so that numbers remain scientifically interpretable.
95. As a protein researcher, I want ESM-3 and ESMFold2 confidence displayed as mean-residue pLDDT on 0–100, so that confidence uses one canonical scale.
96. As a protein researcher, I want structural consistency displayed as TM-score to the Candidate's direct parent structure, so that the comparison target is explicit.
97. As a protein researcher, I want second-stage and final ranking to default to 50% normalized mean-residue pLDDT and 50% TM-score, so that confidence and parent consistency contribute equally.
98. As a protein researcher, I want ranking weights to be editable, so that I can change the experimental preference without changing the measured Metrics.
99. As a protein researcher, I want parent-child score association to follow exact Candidate lineage rather than collection position, so that candidates from different parents are never mixed.
100. As a protein researcher, I want the second and final selections not to include similarity to original 3GB1, so that only confidence and direct-parent consistency determine those rankings.
101. As a protein researcher, I want to select multiple Candidates for side-by-side comparison, so that I can compare sequences, structures, and scores.
102. As a protein researcher, I want structural overlay only when the Workflow produced Structure Alignment Evidence, so that visualization does not invent scientific alignment.
103. As a protein researcher, I want temporary table filters and sorting to affect only the current view, so that exploration does not silently modify the Workflow.
104. As a protein researcher, I want stale results clearly labelled after Workflow changes, so that I never mistake them for results from current parameters.
105. As a protein researcher, I want selected Candidates exported directly as one ZIP, so that I can take structures, sequences, scores, identity, lineage, and Run information into downstream analysis.
106. As a protein researcher, I want export to use the same explicit Candidate selection as comparison, so that I know exactly which Candidates are included.

## Implementation Decisions

### Delivery boundary

- The delivery is one first usable end-to-end slice, not a set of disconnected page shells.
- The default 3GB1 journey, basic Project continuation, Workflow authoring, ProteinPrompt authoring, Run lifecycle, Results Workbench, and export must work together before the slice is complete.
- Confirmed prototype behaviors that are not needed to complete this journey remain product requirements for later slices; they do not justify speculative framework work in this slice.
- The existing immutable canonical 3GB1 Workflow used by backend verification must not be changed into the WebUI example. The WebUI receives a separate lightweight example built from current Node Types, Bindings, Selection Objectives, and public authoring contracts.

### Frontend shape

- Build one React + TypeScript + Vite single-page application.
- Use React Flow for the spatial Workflow canvas and Port/edge interaction.
- Use a mature existing protein-structure viewer library; do not build a custom molecular renderer.
- Connect directly to the loopback public v2 protocol. Do not add a BFF, GraphQL layer, server-side frontend framework, or second application service.
- Keep state in React component state and small purpose-specific hooks. Do not add Redux or another global state framework for the first slice.
- Create one thin protocol client boundary for REST, WebSocket, schema admission, and structured errors. Feature components do not hand-write routes or reinterpret wire payloads independently.
- The frontend remains a public-protocol consumer. It does not import backend Python objects, own scientific contracts, or cause backend runtime modules to depend on UI code.
- Scientific state is stored by its existing backend owner. Canvas positions, expansion, current selection, viewer camera, temporary filters, hover state, and local undo history remain frontend-owned UI state.
- Do not create a design-system project, plugin framework, generic workflow platform, form-builder product, or speculative frontend extension architecture.
- Reuse the eight throwaway prototypes as interaction evidence only. Production code is written under current protocol and repository constraints and does not copy prototype state models blindly.

### Catalog-driven authoring

- Load the active Catalog and Authoring Capability Projection at startup.
- Render ordinary Palette entries, Port Types, parameter schemas, Binding choices, Method information, units, Availability, and user-visible meaning from those projections rather than duplicating a frontend Node catalog.
- Preserve the exact distinction between Node Type, Node Instance, Execution Binding, Method, Port, and Port Type Definition.
- A persisted Node Instance pins one Execution Binding. Switching the visible model selector changes the selected Binding deliberately; the frontend never chooses a hidden fallback.
- The UI groups different structure-prediction Bindings under the one scientific operation “预测蛋白质结构”. ESMFold2, SimpleFold, and future available models appear as choices within that Node Instance.
- Cross-Binding scientific parameters and Binding-specific parameters remain distinguishable according to their public definitions. Credentials, endpoints, devices, and provider filesystem paths are not presented as Workflow parameters.
- Only ordinary Nodes and Specialized Compositions are addable. Managed Members remain visible for read-only inspection of the materialized Workflow but are not independently editable, copyable, or deletable.
- Port compatibility comes from exact public Port Type contracts. The frontend may provide early visual feedback but the backend remains the authority at Draft/Commit admission.

### Canvas interaction

- Use the adopted spatial-card prototype direction: Palette at left, freely positioned Node Instance cards, input Ports at left, and output Ports at right.
- Node parameter groups are collapsed on open. The entire card can collapse to its title; a running card adds only its status beside the title.
- Parameter editing occurs inside the Node Instance card. Generic right-side parameter editing is not the primary path.
- Support Palette drag, canvas search, purpose classification, package/provider classification, and switching between the two classifications.
- Support output-to-input dragging, compatible Port highlighting, invalid drop rejection, edge deletion, drag-to-empty disconnection, and automatic replacement for occupied single-input Ports.
- Support multi-select deletion, copy/paste of selected subgraphs, and multi-step undo for all confirmed canvas edits.
- A copied subgraph retains selected Node Instances, parameters, and internal edges only. A copied Specialized Composition receives a new composition identity through its owning backend authoring operation.
- Do not infer or rewrite Managed Member graphs in the frontend.

### ProteinPrompt Studio

- Use the public Prompt Authoring interface as the sole authoring seam: open, preview, then apply.
- The Specialized Composition is one visible canvas entry that opens Prompt Studio; the backend materializes the explicit scientific Node Instances and edges.
- Support blank, FASTA, PDB, and existing ProteinPrompt sources without making a PDB mandatory.
- Present sequence, structure coordinates, secondary structure, absolute per-residue SASA, and function annotation intervals as one ProteinPrompt.
- Do not expose ResidueLayout, ResidueMap, canonical residue identities, provider positions, raw graph patches, or managed Node parameters as user-editable fields.
- Use opaque authoring residue handles from the public protocol for edits while showing human-readable chain and residue locators.
- Use the adopted matrix-first layout: residue matrix is primary, structure viewer is synchronized and secondary, and the current selection/action panel stays adjacent.
- Collapse the structure viewer when no coordinates exist; never create a fake structure for display.
- Preserve the six public change states: source, current, changed, cleared, inserted, and pending-delete.
- Support preserve, specify, Mask, insert, and delete as the complete residue-operation vocabulary. Function annotation changes operate on complete intervals.
- Sequence and coordinates are independently nullable per residue. Viewer visibility never changes ProteinPrompt coordinates.
- Secondary structure and SASA remain optional tracks; present SASA values are absolute Å² values.
- One local pending edit corresponds to one backend Preview. Enter applies a valid preview, Escape cancels it, and Ctrl/Cmd+Z undoes an applied UI edit. Equivalent visible controls remain available.
- Saving requests a normalized backend Preview, shows all diagnostics and the complete Prompt summary, and applies only after explicit confirmation.
- Prompt Studio edits do not autosave into the Workflow Draft. Leaving with changes offers save, discard, or continue editing.
- The initial implementation must fully support the default example's sequence/coordinate preserve, Mask, insert, and delete operations. More advanced multi-source merge, manual correspondence editing, random authoring controls, and rigid coordinate editing remain later slices.

### Default 3GB1 example

- Use 3GB1 chain A with its 56-residue source layout.
- Pin the initial example to the current `esm3.generate_paired.biohub_medium`,
  `folding.fold.esmfold2_remote`, and `proteinmpnn.design.local` Execution Bindings. A user may
  deliberately select another available Binding; the application never switches automatically.
- Use `1603` as the example's adjustable `effective_seed` wherever the selected Node contract requires
  a configured seed and supplies no default. Use the backend-declared defaults for all remaining parameters
  except the explicitly confirmed generation counts, Top-N values, and weights.
- Specify the original sequence and coordinates for A1–A36 and A42–A56.
- Mask sequence values at A37, A38, A40, and A41; delete A39 VAL; insert two sequence-Mask residues between the original A38 and A40.
- The resulting redesign region contains six generated residues.
- Mask original coordinates for A37–A41. The deleted residue has no target value; inserted residues begin without coordinates.
- Leave secondary structure, SASA, and function annotations absent/empty.
- Use ESM-3 paired generation so every generated Candidate has a sequence and structure for downstream folding and comparison.
- Generate 7 ESM-3 Candidates and select Top 4 by canonical mean-residue pLDDT.
- Fold those four sequences with the “预测蛋白质结构” operation using ESMFold2 and select Top 2 with the declared composite objective.
- Run ProteinMPNN once for each selected parent and generate 3 child sequences per parent, preserving exact parent identity and producing 6 child Candidates.
- Fold all six child sequences with ESMFold2 and select final Top 3 with the declared composite objective.
- For the second selection, TM-score compares each ESMFold2 structure only with its corresponding ESM-3 parent structure.
- For the final selection, TM-score compares each refolded ProteinMPNN child only with the structure that was the direct ProteinMPNN input parent.
- Do not add a fixed-reference 3GB1 similarity objective to the second or final selection.
- Use canonical `structure.plddt.mean_residue` on 0–100 and an explicit linear Utility Transform `x / 100`.
- Use parent-normalized TM-score on 0–1 with an explicit identity Utility Transform.
- Register the minimum exact pLDDT Utility Transforms required by the pinned ESM-3 and ESMFold2 Methods.
  Each transform declares its exact Metric, Method, intrinsic Context, and `x / 100` behavior; do not add
  range guessing or a frontend-only normalization.
- Declare both Selection Objective weights as 0.5 by default. The backend normalizes declared non-negative weights by their sum; the UI displays the effective percentages and allows both declared weights to be changed.
- A missing required Score Observation follows the explicit Selection Objective missing-value policy and is not silently imputed by the frontend.
- Candidate relations, Score subject identity, and Structure Alignment Evidence join by exact Candidate Data Reference and role-labelled lineage, never by list position.
- Build parent, fixed-reference, counterpart, sibling, and ancestor associations by composing generic Candidate
  relation Nodes. A relation has exactly one reference per subject and permits several subjects to share one
  reference. Do not add effect-specific pairing or direct-ancestor Node Types.
- Structure comparison consumes an explicit Candidate relation: a generic alignment Node produces normal
  Structure Alignment Evidence, and generic TM-score or RMSD Nodes consume that evidence. The resulting
  pairwise Score Observations use the `explicit_relation` Observation Context and matching exact Utility
  Transforms.
- All other ESM-3, ESMFold2, and ProteinMPNN parameters use the selected backend Binding/Method defaults and remain editable when their public parameter contract permits editing.
- Bundle one completed result produced through the real current Workflow and public/backend owners. Do not fabricate Candidate, Score, lineage, Artifact, or evidence payloads in frontend fixtures.
- The bundled result records the exact resolved Prompt, parameters, Method identities, randomness, lineage, Metric Definitions, Selection Objectives, and Run provenance used to produce it.
- If a backend default changes, the example Workflow and bundled result must be regenerated together; an old result is never relabelled as if it used new defaults.

### Project and persistence behavior

- The immutable default example is a distinct backend-owned example Project, not mutable frontend seed JSON.
- The public protocol must let the frontend discover the default example, its current Workflow Draft/Commit, and its attached completed Run projection without hard-coding scientific payloads in components.
- On the first scientific or canvas edit, create a personal Project copy without a blocking confirmation dialog and continue the edit there.
- The personal copy keeps a provenance link sufficient to display the bundled result as “来自修改前的流程” until a new Run result replaces it.
- Personal Workflow Draft edits autosave through the existing Workflow authoring owner; Runs execute only immutable Workflow Commits.
- Add only the smallest public Project operations needed to list/search personal Projects, reopen a Project, and create the first personal copy. Keep them in the current public protocol and Project owner; do not create frontend-specific aggregation endpoints.
- Named versions, general Project rename/copy/delete/recovery, folders, tags, favorites, and full version-branch navigation are later implementation slices.

### Run behavior

- Commit the current admitted Workflow Draft before starting a new full Run.
- Use the existing start, derived-run, projection, cancellation, typed-value, Artifact, and Run event-stream contracts directly.
- “运行完整流程” starts from the active Workflow Commit.
- “运行到所选节点” and “从所选节点继续” use existing derived-Run semantics and show the selected execution range before confirmation.
- A Run summary must show scope, selected Bindings/Methods, major parameters, generation counts, effective randomness, and all current blockers.
- Keep Node Instance status overlaid on the canvas. Do not replace the canvas with a scheduler table.
- Independent branches continue after an unrelated failure. Dependent Node Instances show an explicit not-executed disposition.
- Cancellation applies to the entire Run. Already-published Typed Outputs, Candidates, Scores, and Artifacts remain visible.
- Closing a page or WebSocket subscription never cancels the Run.
- The first slice displays only the most recent Run for the active Project.

### Results Workbench

- Use the adopted lineage-workbench direction. Candidate lineage is the primary scientific axis; a neighboring Candidate table supports focus, sorting, filtering, comparison, and export selection.
- Synchronize the focused Candidate across lineage, table, sequence, structure, Score Observations, Method information, and provenance summary.
- Display Metric Definition name, Method, unit, canonical range, direction, aggregation, and Observation Context with each Score Observation.
- Side-by-side comparison and export share one explicit Candidate selection.
- Overlay structures only from existing Structure Alignment Evidence. A viewer-only overlay is labelled as visual and never published as a scientific alignment.
- Temporary sorting/filtering remains frontend UI state and does not mutate the Workflow.
- Continue showing the most recent result after Workflow changes, with a persistent “来自修改前的流程” label.
- Direct export creates one ZIP containing one PDB per selected structure Candidate, combined FASTA, score CSV, and a manifest describing Candidate identities, lineage, Methods, and Run provenance.
- Use existing Typed Output and Artifact retrieval operations. Do not duplicate structure bytes or scientific values into a second frontend result store.

### Explicit non-architecture decisions

- The application is trusted, single-user, and loopback-only. Do not add authentication, authorization, accounts, multi-tenancy, permission roles, CSRF systems, or hosted-service hardening.
- Do not add compatibility aliases, legacy protocol support, fallback routes, dual frontend implementations, or migration layers for the retired frontend.
- Do not guess provider payloads, repair backend responses, infer missing units, normalize unknown Metrics, or choose substitute models.
- Do not add broad catches, silent coercion, automatic scientific fixes, or undocumented retry behavior.
- Fail closed on unsupported public capability and show the backend's structured diagnostic in user language.

## Testing Decisions

- Use one highest-level primary seam: a browser journey against a real local FastAPI public v2 server seeded with the immutable WebUI example and its completed Run.
- The primary journey covers startup, Catalog/Authoring Capability loading, default canvas rendering, bundled result inspection, one parameter edit causing a personal copy, one edge rewire and undo, Prompt open/preview/apply, Workflow Draft save/Commit, Run-range confirmation, event/projection handling, Candidate lineage inspection, and ZIP export.
- Browser tests assert user-visible behavior and public outcomes, not React component structure, hook calls, CSS class names, or internal state containers.
- Use Playwright for the small number of browser journeys needed to cover the end-to-end slice. Do not build a broad page-object framework before repeated behavior justifies it.
- Run browser tests against the real public protocol bundle and real backend route handlers. Do not replace Catalog, Workflow Draft, Prompt Preview, Run Projection, Candidate, Score, or Artifact payloads with component-local mocks.
- The bundled completed result is a startup fixture for WebUI usability, not a substitute for scientific acceptance of ESM-3, ESMFold2, ProteinMPNN, confidence materialization, alignment, TM-score, or Selection.
- Test the default example Workflow separately through the public v2/backend seam: exact Candidate counts 7 → 4 → 4 → 2 → 6 → 6 → 3, exact parent-child closure, exact comparison roles, exact Metric/Method/Context selection, exact Utility Transforms, and declared/effective 50%/50% weights.
- Test the direct-ancestor comparison with two parent structures and three descendants per parent. Every subject
  must resolve exactly one two-hop ancestor, repeated references must be accepted, an unrelated or ambiguous
  ancestor must fail, and each TM-score Observation must retain its exact subject/reference evidence.
- Test the 3GB1 Prompt through public Prompt Authoring open → preview → apply. Assert the A37–A41 sequence/coordinate masks, A39 deletion, two insertions, target length, empty optional tracks, and materialized explicit Workflow graph.
- Use existing public Prompt Authoring interface tests as prior art for source handling, opaque residue handles, six-state changes, diagnostics, and atomic Draft replacement.
- Use current public-journey and installed-backend tests as prior art for Catalog discovery, Workflow Draft/Commit, Run events, Typed Output retrieval, Artifact retrieval, cancellation, and structured errors.
- Use the canonical 3GB1 deterministic and real-provider campaigns as prior art for scientific and provenance assertions, but keep the canonical Workflow unchanged.
- Provider acceptance continues to use real Providers where required. Frontend mocks, readiness checks, historical manifests, and Cache replay cannot replace those acceptance tiers.
- Add focused backend tests only for genuinely new public Project operations and the separate WebUI example seed. Test their public behavior and Project ownership, not storage implementation details.
- Frontend verification includes lint, TypeScript type checking, browser tests, and production build.
- Backend changes run focused pytest coverage plus:

  ```bash
  .venv/bin/python -m verification.backend routine
  .venv/bin/python -m verification.backend deterministic-acceptance
  ```

- The existing backend verification gate remains independently runnable without frontend source or build output.
- The frontend production build remains independently runnable without importing Python source.
- Do not commit client build output, environments, `.local/`, keys, or Provider credentials.

## Out of Scope

- Replacing, weakening, or redesigning the current backend scientific runtime.
- Modifying the immutable canonical 3GB1 Workflow used by backend verification.
- A BFF, GraphQL server, server-side rendering layer, desktop wrapper, hosted deployment platform, or cloud account system.
- Authentication, authorization, multi-user collaboration, permissions, audit roles, or adversarial-service hardening.
- Reusing or maintaining the retired frontend implementation.
- Building a generic plugin system, frontend module marketplace, design-system product, or schema/form framework beyond current Catalog needs.
- Implementing the FASTA batch-scoring scenario as a second complete default journey in this first slice.
- Implementing additional example Workflows beyond the confirmed 3GB1 journey.
- Prompt multi-source merge, temporary automatic correspondence, manual gap/alignment editing, and per-track conflict resolution in the first slice.
- Random Prompt Mask/insertion controls in the first slice, although deterministic random authoring remains a confirmed later product capability.
- Residue-level 3D rigid translation/rotation controls in the first slice, although their Blender-style interaction contract remains confirmed for later work.
- Atom-level structure editing, atom selection, coordinate sculpting, scaling, automatic minimization, or automatic movement of neighboring residues.
- Named Project versions, general version branching/navigation, general Project copy, rename, recently-deleted recovery, folders, tags, and favorites in the first slice.
- Run history beyond the most recent Run.
- Cancelling one Node Instance independently from its Run.
- Inventing a new scientific alignment for temporary viewer overlays.
- Adding original-3GB1 fixed-reference similarity to the second or final default selections.
- Natural-language-to-ProteinPrompt generation.
- A ProteinMPNN constraint editor independent of the confirmed Workflow operations.
- Final visual polish for colors, icons, classification names, density, Port Type label persistence, and exact 3D panel dimensions.
- Final decisions about recommended-model ranking, deep evidence browsing, default Project ordering, and the full expression language for “保存为流程筛选”.

## Further Notes

- The authoritative user-visible product decisions remain in [Protein Workbench WebUI 功能规格](2026-08-29-webui-functional-spec.md).
- The authoritative domain vocabulary remains in [CONTEXT.md](../CONTEXT.md).
- Prompt authoring hierarchy and parameter ownership are already fixed by [ProteinPrompt Authoring 层级与参数所有权规格](2026-08-31-prompt-authoring-layer-and-parameter-ownership-spec.md).
- The public-protocol/client boundary follows accepted ADRs for full-stack scope, pinned Execution Bindings, parameter ownership, immutable Workflow Commits, Candidate-associated scientific values, explicit Utility Transforms, and ProteinPrompt conditioning ownership.
- The eight prototypes under `.scratch/webui-product-definition` are disposable interaction evidence. They are not production source and do not override this specification or the public protocol.
- No issue tracker item or triage label was created because the requested publication target is this local Markdown file. The local `ready-for-agent` status is the equivalent handoff marker for this task.
