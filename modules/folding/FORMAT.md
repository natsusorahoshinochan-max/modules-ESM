# Prediction data packages

These formats are owned by the prediction module. Consumers read only package files and need no producer installation.

## workbench.sequence

The JSON entry contains `objects`, one or more ordered objects, each with a nonempty string `id`, a canonical protein `sequence`, and optional text `label`. Example: `sample/sequence.json`. Prediction rejects additional components, conditions, modified residues and multi-chain inputs. A single-sequence FASTA UI rejects multiple records and directs users to batch import.

## workbench.prediction

The JSON entry contains `objects` and `tool`. Each object has its own independently allocated `id`, the complete input `sequence`, optional `label`, and `structure: {"file": "structure.pdb", "format": "pdb"}` or mmCIF equivalent. `file` is a package file key. Each object names its own file keys; examples use `structure.pdb` for the first object and `objects/1/structure.pdb` for the second. The structure file preserves chain identifiers, residue numbers and insertion codes; sequence order corresponds to the protein chain in the predicted file. The batch produces one object per completed request in input order. A failed or cancelled node can deliver a completed prefix for explicit viewing, export or input selection; its node status records that the batch is incomplete.

Confidence is optional for tools that do not produce it. When present, `confidence.plddt` is `{"file":"confidence.json","scale":"0-1"}`; that JSON contains `{"plddt":[0.8,0.9,0.7]}` with exactly one value per input residue in order. `confidence.ptm` is the native whole-prediction pTM on a 0–1 scale. ESMFold2 requires both outputs. These are prediction confidence, with no independent evaluation relation.

Optional `supplementary: {"file":"supplementary.json"}` names a JSON file of native output fields, such as `pae` (sequence-order square matrix in Å), `distogram`, `pair_chains_iptm`, `output_embedding_sequence` and `output_embedding_pair_pooled`. Values retain the provider's axes and numeric values; omitted native outputs are absent. No synthetic scores are generated.

`tool` contains the selected implementation `id` and user `parameters`; omitted controls use the adapter's documented defaults. Deployment settings and credentials are excluded. All referenced files are included in the package. Consumers needing a different format must use an explicit conversion node.
