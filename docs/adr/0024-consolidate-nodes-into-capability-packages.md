---
status: accepted
---

# Legacy node directories consolidate into capability packages

The v2 migration consolidates the current one-node directories into eleven
repository-owned Module Packages: `prompt_authoring`, `esm3`, `folding`,
`proteinmpnn`, `structure_annotation`, `structure_comparison`,
`structure_transform`, `protein_io`, `selection`, `collection_ops`, and
`solubility`.
Grouping follows shared scientific capability, dependencies, Adapters, and
contract-test assets rather than legacy ID prefixes or UI categories.

The migration does not preserve accidental contracts merely to keep the
current Node count: ESMFold2 and SimpleFold folding become bindings of one
scientific folding Node Type; the duplicate mkdssp Nodes and SASA invocation
become one structure-annotation Node with shared outputs; ambiguous
cross-Metric confidence aggregation is not migrated unchanged; and
`stub.echo` becomes test support rather than a production Node. Local ESM-3
extends `esm3`, local ESMFold2 extends `folding`, and SoluProt plus Protein-Sol
form the `solubility` Module Package.
