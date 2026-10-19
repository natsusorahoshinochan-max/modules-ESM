# Prediction data packages

These formats are owned by the prediction module. Consumers read only package files and need no producer installation.

## workbench.sequence

The JSON entry contains `objects`, one or more ordered objects, each with a nonempty string `id`, a canonical protein `sequence`, and optional text `label`. IDs are unique within the batch. Example: `sample/sequence.json`. Prediction rejects additional components, conditions, modified residues and multi-chain computational inputs.

Optional `source` contains explicitly supplied text fields `name`, `record` and/or `text`. Sequence/FASTA import records the selected filename when present, the FASTA header as `record`, and the original input text unchanged. Headers remain descriptive text; chain IDs and author numbering come from explicit correspondence.

Optional `positions` contains exactly one entry per sequence residue, in sequence order. Every entry has a one-based `sequence_index`. An explicit source-residue correspondence additionally supplies all three fields `chain` (text), `author_number` (integer) and `insertion_code` (text, empty when absent). Repeated residue identities or incomplete supplied correspondence fail. Plain sequence/FASTA imports supply only sequence indices. This example retains an insertion and a numbering gap:

```json
{"objects":[{"id":"source-fragment","sequence":"ACD","source":{"name":"selection.json"},"positions":[{"sequence_index":1,"chain":"Z","author_number":12,"insertion_code":""},{"sequence_index":2,"chain":"Z","author_number":12,"insertion_code":"A"},{"sequence_index":3,"chain":"Z","author_number":19,"insertion_code":""}]}]}
```

The sequence action accepts single sequence/FASTA, explicit batch FASTA, or sequence JSON. Single mode directs multi-record FASTA to batch import. JSON preserves supplied object identities, source and correspondence. `modules.folding.formats.read_sequences(package)` is the optional public Python reader; independent consumers may read the format directly. Missing content required by a selected operation produces an error.

## workbench.prediction

The JSON entry contains `objects` and `tool`. Each object has its own independently allocated `id`, the complete input `sequence`, optional `label`, and `structure: {"file": "structure.pdb", "format": "pdb"}` or mmCIF equivalent. `file` is a package file key. Each object names its own file keys; examples use `structure.pdb` for the first object and `objects/1/structure.pdb` for the second. `input`, when present, is the complete original sequence object, including its identity, source and supplied positions. Prediction execution includes it without rewriting. Its positions describe the input sequence and its explicit source correspondence; positions in the generated structure are read from the generated structure file. A supplied input sequence must match the prediction sequence. Imported results may omit `input` when that relationship was not supplied. The structure file preserves chain identifiers, residue numbers and insertion codes; sequence order corresponds to the protein chain in the predicted file. The batch produces one object per completed request in input order. A failed or cancelled node can deliver a completed prefix for explicit viewing, export or input selection; its node status records that the batch is incomplete.

Confidence is optional for tools that do not produce it. When present, `confidence.plddt` is `{"file":"confidence.json","scale":"0-1"}`; that JSON contains `{"plddt":[0.8,0.9,0.7]}` with exactly one value per input residue in order. `confidence.ptm` is the native whole-prediction pTM on a 0–1 scale. ESMFold2 requires both outputs. These are prediction confidence, with no independent evaluation relation.

Optional `supplementary: {"file":"supplementary.json"}` names a JSON file of native output fields, such as `pae` (sequence-order square matrix in Å), `distogram`, `pair_chains_iptm`, `output_embedding_sequence` and `output_embedding_pair_pooled`. Values retain the provider's axes and numeric values; omitted native outputs are absent. No synthetic scores are generated.

`tool` contains the selected implementation `id` and user `parameters`; omitted controls use the adapter's documented defaults. Deployment settings and credentials are excluded. All referenced files are included in the package. Consumers needing a different format must use an explicit conversion node.

## Importing existing prediction results

Use **Import existing prediction results** with a `workbench.prediction` JSON manifest. Bind every structure, confidence and supplementary file explicitly to the displayed package key; filenames are not matched automatically. The entry is saved as `manifest.json`, so referenced files use different keys. The module checks required object, sequence, tool and parameter content, declared confidence scale and values, and all required file bindings before uploading. It preserves the original manifest bytes and selected file bytes, including existing object IDs, numeric results, tool parameters and any supplied input relationship. Consumers check their own structural requirements when running.

The imported package appears in Data packages and in compatible canvas input selectors. Save the canvas manually to retain its bindings. **Download ZIP** includes the complete selected package and its existing parameter description in `tool`; referenced numeric and supplementary files remain unchanged. The generic archive index maps original package keys to safe ZIP members, as described in [module authoring](../../docs/module-authoring.md#交付文件).
