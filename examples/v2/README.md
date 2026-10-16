# Protein Workbench v2 examples

`canonical-3gb1.workflow.json` is the canonical scientific Workflow.
`webui-3gb1.example.json` is the separate protected WebUI example;
`webui-3gb1.results.zip` carries its completed real Run and is included in the
backend wheel. Its results are available offline on first open; new Runs require
the configured real Providers. See the [WebUI guide](../../webui/README.md) and
[workspace requirements](../../docs/workspace.md#教学实例与默认入口).

The current authored WebUI workflow sorts generated structures by raw mean
pLDDT, and sorts both refolding stages by raw reference-normalized TM-score,
all descending with input-order ties. It does not combine confidence and
similarity into a composite score. The canonical workflow configures two
module-declared TM-score scoring choices with nonnegative relative weights.
The shipped completed Run retains its original Commit,
parameters, ranking behavior and outputs; it is a historical result, and may be
stale against the current authored workflow. Regenerating the example JSON does
not rewrite `webui-3gb1.results.zip`.

These files describe current Workflow examples; they do not establish product
scope or prove that all current requirements are implemented. In particular,
ProteinMPNN must be rebuilt under the [module requirements](../../docs/module-capabilities.md),
and the teaching example must retain first-manual-save behavior. Requirements are owned by the [current decisions](../../docs/documentation-governance-decisions.md).

`repository-capabilities.workflow.json` is a Workflow example of Catalog composition. It fixes its Execution Bindings by stable ID and separates Node and
Binding parameters. Its ordinary `prompt_authoring.author` Nodes declare Prompt
content through the `document` parameter, as in the public authoring surface.

`prompt-downstream-interfaces.workflow.json` closes both required Prompt Studio
downstream interfaces without a converter: `author → decompose.sequence →
materialize_sequence.sequence_candidates → folding.fold`, and the same
materialized sequence as the optional reference for `proteinmpnn.design` while
its authoritative structure target remains the independently resolved structure
Candidate axis. It is a interface example for a complete
single-chain Project Input.

The repository examples are representative scientific Workflows, not a
mechanical inventory of every Catalog registration. Prediction and folding
Nodes publish subjectless confidence facts; the Workflows join those facts to
admitted structure Candidates only through
`structure_prediction.materialize_confidence`.

`source-bound-1pga.workflow.json` is the exact 75-residue Workflow
for `examples/v2/structures/1PGA-75-gen1_0690.pdb` (SHA-256
`d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30`).
It admits the structure through Project Input, derives the shared sequence
parent inside the Workbench, runs one ESMFold2 sample and one
explicitly seeded 50-step SimpleFold sample, and closes the three pairwise
comparisons with exact evidence references. Only the two prediction Methods
provide pLDDT confidence; the input coordinate B-factor field remains
uninterpreted.

`source-bound-2emo.workflow.json` is the exact 224-residue Workflow
for `examples/v2/structures/2EMO.pdb` (SHA-256
`6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700`).
It materializes the CSH A:66 parent-span normalization as A:65–A:67 `SHG`,
retains the explicit A:64–A:68 residue correspondence, and generates eight
ProteinMPNN sequence Candidates before one ESMFold2 sample per Candidate. Four
independent filters apply reference-normalized TM-score, Cα RMSD, mean pLDDT,
and Protein-Sol scaled observations; their exact Candidate intersection may be
empty without turning the scientific result into a failed Run.

The `design-constraints` Node authors explicit ProteinMPNN constraints from the
resolved reference axis. It fixes A:42, A:44, A:46, A:60–A:72, A:92, A:94, A:96,
A:110, A:112, A:121, A:123, A:145, A:148, A:150, A:165, A:167, A:183, A:203,
A:205, A:220, and A:222, preserving the SHG precursor and the declared functional
neighborhood. The maintained [source-bound Workflow](source-bound-2emo.workflow.json) records
this exact set. The [module capability specification](../../docs/module-capabilities.md)
defines current functional responsibilities, while [Prompt editing](../../docs/prompt-editing.md)
describes the existing authoring boundary and its gaps.
The Adapter maps these residue identities to Provider positions. Prompt sequence
masking does not supply ProteinMPNN constraints, and the missing backbone oxygen
at normalized A:65 remains missing.

`source-bound-5g53.workflow.json` is the exact source-bound loop-insertion
Workflow for `examples/v2/structures/5G53.pdb` (SHA-256
`a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537`).
It imports the four-chain source bytes with HETATM records and provenance,
selects chain A explicitly, and retains the 283-residue reference axis with
the A:146-to-A:159 and A:211-to-A:224 discontinuities. Three paired ESM3
branches insert 8, 12, or 16 residues only at the second discontinuity, with
two samples per branch and explicit generation parameters. ESMFold2
folds all six designed counterparts. The Workflow publishes reference-core
and counterpart alignment scores, resolved-core and inserted-loop confidence,
junction geometry, and clash evidence before applying the declared scientific
filters. A scientifically valid zero-pass result remains a successful Run.

## Protected WebUI result resource

`webui-3gb1.results.zip` belongs to the protected `webui-3gb1-example` Project.
It carries the completed real Run with its original Workflow, declared Bindings,
Methods and recorded parameters.
Its current editable Draft follows `webui-3gb1.example.json`, including route-owned
ESM3 parameters. Updating that teaching Draft does not claim a fresh Run with the
new definitions. The resource includes its manifest, original immutable Project
Inputs, Draft/workspace/Commit records, ordered Ledger transactions, and all
published manifests, values and artifacts needed by that Run. Original identities
and contents remain unchanged. Additive `readings.json` and `reading.json` provide
the completed Run's current generic reading; normalized Draft readings and
nonexecutable Commit markers preserve original configurations without invoking
retired parsers or algorithms. The current authored teaching Draft is packaged
as a later revision. Original Draft, Commit and Run records remain intact.
Runtime caches, temporary Provider workspaces,
weights, process environment, execution profiles, credentials and private
configuration are excluded.

Changed calculation definitions do not change the meaning of preserved Run
records. A new Draft must not relabel historical results as a new computation.

Current startup installs the packaged trusted records before runtime registration,
publishes dependencies first and the Run directory last, and leaves no partly
visible Run on interrupted staging. An already installed identical Run is reused;
conflicting protected content is rejected without overwriting it. User Projects are outside the installer. The resource
ships in the backend wheel, so first-open browsing works with Providers unavailable.

Current composition installs the example resource by default; the
`load_example_results=False` option supports isolated composition and resource
generation. This is implementation behavior, not a requirement that the carrier
depend on a science module or teaching resource to start. The original tutorial
remains protected. Editing/personal-save and copied Run scope must follow
[workspace requirements](../../docs/workspace.md#教学实例与默认入口).


`discontinuous-regions.workflow.json` demonstrates explicit A:1/A:3/A:5 selections
on `structures/3GB1.pdb`. Upload that file into the target project and replace
`project_input_ref` and `workflow_id` with the returned input and project IDs.
The comparison branch aligns selected positions of the original against itself
without changing its structure; the separate extraction branch intentionally
creates a new fragment Candidate. Replace either comparison source with another
axis to compare distinct objects. No prediction Provider is involved.
For regional statistics of existing per-residue scores, connect a Score Collection
to `structure_comparison.region_statistics`, choose its original `metric_id`,
the same position objects, and `missing_values` (`exclude_null` or `require_all`).
See [regional behavior and downstream type boundaries](../../docs/module-capabilities.md#不连续区域比较提取与已有指标统计).
## ProteinMPNN design and independent evaluation

`proteinmpnn-design-score.workflow.json` uses `structures/3GB1.pdb` as Project Input
`3GB1.pdb`. It configures position omissions, a PSSM row and weighted tied positions,
designs one sequence, then evaluates it on the selected backbone. Configure the
ProteinMPNN source/weights location in module settings before running.

The scoring sequence input can instead come from `protein_io.import_sequence`;
it need not have been generated from the selected backbone. An unlabelled sequence
uses complete backbone order. For an existing sequence with different residue
identities, select a complete `sequence_correspondence` from original sequence
positions to backbone residues. This evaluation relationship does not change the
sequence's actual parents. Tied members must share position omissions, biases and
PSSM rows; their individual logit weights may differ.

结构导入示例使用单构象输入时可省略 `model_index`。更换为多构象文件时，先在“添加来源”检查构象列表，再为 `protein_io.import_structure` 设置从 1 开始的 `model_index`；需要多个候选时使用 `protein_io.import_structures` 和明确的 `model_indices`（例如 `[1, 2]`），将 `structure_candidates` 接至候选处理节点。一个输入引用始终指向一份未改写的原文件。

[Top-k scopes](top-k-scopes.md) shows whole-batch and per-backbone selection
using ordinary Candidate Relation operations and the same existing observations.
Its runnable public-API example uses explicitly controlled values, keeps imported
Candidate lineage unchanged, and demonstrates that missing scores stop only the
affected selection branches rather than silently removing unscored Candidates.
