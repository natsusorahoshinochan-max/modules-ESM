---
status: accepted
---

# Scientific capability package boundaries

Protein Workbench has twelve repository-owned Module Packages:
`prompt_authoring`, `esm3`, `folding`, `proteinmpnn`, `structure_annotation`,
`structure_comparison`, `structure_transform`, `protein_io`, `selection`,
`collection_ops`, `solubility`, and `structure_prediction`.

Grouping follows shared scientific capability, dependencies, Adapters, and
Contract Test Kit assets rather than Node ID prefixes or UI categories.
ESMFold2 and SimpleFold folding are distinct Execution Bindings of one scientific
folding Node Type. Secondary-structure and SASA observations are owned by the
`structure_annotation` package. Provider-independent confidence materialization
is owned by `structure_prediction`. Local ESM-3 belongs to `esm3`, local
ESMFold2 belongs to `folding`, and SoluProt and Protein-Sol belong to
`solubility`.

Test-only operations are not production Node Types. Every production Node Type
has unambiguous scientific meaning, Method identity, outputs, and package
ownership.
