# Prediction data packages

The prediction module consumes the [sequence format](../sequence_io/FORMAT.md). Consumers of prediction results read only package files and need no producer installation.

## workbench.prediction

The JSON entry contains `objects` and `tool`. Each object has its own independently allocated `id`, the complete input `sequence`, optional `label`, and `structure: {"file": "structure.pdb", "format": "pdb"}` or mmCIF equivalent. `file` is a package file key. Each object names its own file keys; examples use `structure.pdb` for the first object and `objects/1/structure.pdb` for the second. `input`, when present, is the complete original sequence object, including its identity, source and supplied positions. Prediction execution includes it without rewriting. Its positions describe the input sequence and its explicit source correspondence; positions in the generated structure are read from the generated structure file. A supplied input sequence must match the prediction sequence. Imported results may omit `input` when that relationship was not supplied. The structure file preserves chain identifiers, residue numbers and insertion codes; sequence order corresponds to the protein chain in the predicted file. The batch produces one object per completed request in input order. A failed or cancelled node can deliver a completed prefix for explicit viewing, export or input selection; its node status records that the batch is incomplete.

Confidence is optional for tools that do not produce it. When present, `confidence.plddt` is `{"file":"confidence.json","scale":"0-1"}`; that JSON contains `{"plddt":[0.8,0.9,0.7]}` with exactly one value per input residue in order. `confidence.ptm` is the native whole-prediction pTM on a 0–1 scale. ESMFold2 requires both outputs. These are prediction confidence, with no independent evaluation relation.

Optional `supplementary: {"file":"supplementary.json"}` names a JSON file of native output fields, such as `pae` (sequence-order square matrix in Å), `distogram`, `pair_chains_iptm`, `output_embedding_sequence` and `output_embedding_pair_pooled`. Values retain the provider's axes and numeric values; omitted native outputs are absent. No synthetic scores are generated.

`tool` contains the selected implementation `id` and user `parameters`; omitted controls use the adapter's documented defaults. Deployment settings and credentials are excluded. All referenced files are included in the package. Consumers needing a different format must use an explicit conversion node.

## Importing existing prediction results

Use **Import existing prediction results** with a `workbench.prediction` JSON manifest. Bind every structure, confidence and supplementary file explicitly to the displayed package key; filenames are not matched automatically. The entry is saved as `manifest.json`, so referenced files use different keys. The module checks required object, sequence, tool and parameter content, declared confidence scale and values, and all required file bindings before uploading. It preserves the original manifest bytes and selected file bytes, including existing object IDs, numeric results, tool parameters and any supplied input relationship. Consumers check their own structural requirements when running.

The imported package appears in Data packages and in compatible canvas input selectors. Save the canvas manually to retain its bindings. **Download ZIP** includes the complete selected package and its existing parameter description in `tool`; referenced numeric and supplementary files remain unchanged. The generic archive index maps original package keys to safe ZIP members, as described in [module authoring](../../docs/module-authoring.md#交付文件).
