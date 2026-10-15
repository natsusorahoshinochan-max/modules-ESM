# Protein Workbench v2 examples

`canonical-3gb1.workflow.json` is the canonical executable verification Workflow.
`webui-3gb1.example.json` is the separate protected WebUI example;
`webui-3gb1.results.zip` carries its completed real Run and is included in the
backend wheel. Its results are available offline on first open; new Runs require
the configured real Providers. See the [WebUI guide](../../webui/README.md) and
[workspace requirements](../../docs/workspace.md#教学实例与默认入口).

These files describe current executable fixtures; they do not establish product
scope or prove that all current requirements are implemented. In particular,
ProteinMPNN must be rebuilt under the [module requirements](../../docs/module-capabilities.md),
and the teaching example's first-edit persistence does not meet the required
first-manual-save behavior. Requirements are owned by the [current decisions](../../docs/documentation-governance-decisions.md).

`repository-capabilities.workflow.json` is a provider-free Catalog compilation
fixture. It fixes its Execution Bindings by stable ID and separates Node and
Binding parameters. Its ordinary `prompt_authoring.author` Nodes declare Prompt
content through the `document` parameter, as in the public authoring surface.
Verification parses and compiles the Workflow against the current Catalog without
invoking a Provider or selecting a sibling Binding.

`prompt-downstream-interfaces.workflow.json` closes both required Prompt Studio
downstream interfaces without a converter: `author → decompose.sequence →
materialize_sequence.sequence_candidates → folding.fold`, and the same
materialized sequence as the optional reference for `proteinmpnn.design` while
its authoritative structure target remains the independently resolved structure
Candidate axis. It is a compile-only interface example for a complete
single-chain Project Input.

The repository examples are representative scientific Workflows, not a
mechanical inventory of every Catalog registration. Prediction and folding
Nodes publish subjectless confidence facts; the Workflows join those facts to
admitted structure Candidates only through
`structure_prediction.materialize_confidence`. Run on the remote verification
host's fixed snapshot, following the [verification policy](../../docs/backend-verification.md#execution-policy):

```bash
uv run --no-sync python -m examples.v2_suite
```

Focused owner tests cover scientific Node and Binding behavior, Adapter
translation, valid and invalid values at each scientific Port's admission
boundary, and separate canonical encoding and codec round-trip contracts.
Real Provider routes remain covered by their acceptance tiers; neither
the examples nor a Catalog identity inventory substitutes for those tests.

`source-bound-1pga.workflow.json` is the exact 75-residue acceptance Workflow
for `examples/v2/structures/1PGA-75-gen1_0690.pdb` (SHA-256
`d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30`).
It admits the structure through Project Input, derives the shared sequence
parent inside the Workbench, runs one explicitly seeded ESMFold2 sample and one
explicitly seeded 50-step SimpleFold sample, and closes the three pairwise
comparisons with exact evidence references. Only the two prediction Methods
provide pLDDT confidence; the input coordinate B-factor field remains
uninterpreted. Provider-free public REST/WebSocket acceptance uses lawful
controlled Binding clients and never invokes a remote Provider or local model.

`source-bound-2emo.workflow.json` is the exact 224-residue acceptance Workflow
for `examples/v2/structures/2EMO.pdb` (SHA-256
`6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700`).
It materializes the CSH A:66 parent-span normalization as A:65–A:67 `SHG`,
retains the explicit A:64–A:68 residue correspondence, and generates eight
ProteinMPNN sequence Candidates before one ESMFold2 sample per Candidate. Four
independent filters apply reference-normalized TM-score, Cα RMSD, mean pLDDT,
and Protein-Sol scaled observations; their exact Candidate intersection may be
empty without turning the scientific result into a failed Run. Provider-free
public REST/WebSocket acceptance uses lawful controlled Binding clients and
does not invoke a remote Provider or load ProteinMPNN or Protein-Sol.

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
acceptance Workflow for `examples/v2/structures/5G53.pdb` (SHA-256
`a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537`).
It imports the four-chain source bytes with HETATM records and provenance,
selects chain A explicitly, and retains the 283-residue reference axis with
the A:146-to-A:159 and A:211-to-A:224 discontinuities. Three paired ESM3
branches insert 8, 12, or 16 residues only at the second discontinuity, with
two samples per branch and exact seeds and generation parameters. ESMFold2
folds all six designed counterparts. The Workflow publishes reference-core
and counterpart alignment scores, resolved-core and inserted-loop confidence,
junction geometry, and clash evidence before applying the declared scientific
gates. A scientifically valid zero-pass result remains a successful Run.
Provider-free public REST/WebSocket acceptance uses lawful controlled Binding
clients with reconstruction and both full-PAE confidence paths; it invokes no
remote Provider or local model.

## Protected WebUI result resource

`webui-3gb1.results.zip` belongs to the protected `webui-3gb1-example` Project.
It carries the completed real Run of `webui-3gb1.example.json` with the Workflow's
declared Bindings, Methods and seeds; a canonical verification Run is not a
substitute. The resource includes its manifest, original immutable Project
Inputs, Draft/workspace/Commit records, ordered Ledger transactions, and all
published manifests, values and artifacts needed by that Run. Original identities
and contents remain unchanged. Runtime caches, temporary Provider workspaces,
weights, process environment, execution profiles, credentials and private
configuration are excluded.

`verification.webui_example_evidence` generates and exports this resource. Generation
uses a fresh explicit remote data root and execution profile, runs the full real
Workflow and requires successful completion, no derived source and no cache replay.
Export reads the original durable owner records rather than reconstructing Ledger
transactions from public events. A failed or interrupted generation remains
diagnosable in its data root and is not exported as the teaching result. An already
completed generation can be exported without invoking Providers again. Changed
calculation definitions require a new real generation, not relabeling old results.

Current startup installs the packaged trusted records before runtime registration,
publishes dependencies first and the Run directory last, and leaves no partly
visible Run on interrupted staging. An already installed identical Run is reused;
conflicting protected content is rejected without overwriting it. User Projects
and the canonical verification Project are outside the installer. The resource
ships in the backend wheel, so first-open browsing works with Providers unavailable.

Current composition installs the example resource by default; the
`load_example_results=False` option supports isolated composition and resource
generation. This is implementation behavior, not a requirement that the carrier
depend on a science module or teaching resource to start. The original tutorial
remains protected. Editing/personal-save and copied Run scope must follow
[workspace requirements](../../docs/workspace.md#教学实例与默认入口), not the currently
implemented copy-on-first-edit path.

Changes to the resource require remote verification of real generation, clean
installed-package startup without Providers, original Commit/Run readability,
candidate/score/parent/structure browsing, and protection of the teaching original.
The real browser journeys and backend Provider gates remain separate; use the
[WebUI verification entry point](../../webui/README.md#verification).
