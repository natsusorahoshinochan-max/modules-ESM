# Protein Workbench v2 examples

`repository-capabilities.workflow.json` is a provider-free-to-verify authoring
example. It fixes its production Execution Bindings by stable ID, separates Node
and Binding parameters, and uses production scientific values. Verification
parses and compiles the Workflow against the current Catalog without invoking a
Provider or selecting a sibling Binding.

The repository examples are representative scientific Workflows, not a
mechanical inventory of every Catalog registration. Prediction and folding
Nodes publish subjectless confidence facts; the Workflows join those facts to
admitted structure Candidates only through
`structure_prediction.materialize_confidence`. Run:

```bash
uv run --no-sync python -m examples.v2_suite
```

Focused owner tests cover scientific Node and Binding behavior, Adapter
translation, and every scientific Port codec's valid, invalid, and round-trip
contract. Real Provider routes remain covered by their acceptance tiers; neither
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
