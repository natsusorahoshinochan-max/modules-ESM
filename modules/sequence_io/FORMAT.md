# Sequence input and output

`modules.sequence_io:module` supplies sequence import and viewing independently of prediction. Its optional public Python reader is an explicit code dependency for consumers choosing to reuse it. Other consumers can read the public format without the producer.

## workbench.sequence

The JSON entry contains `objects`, one or more ordered objects, each with a nonempty string `id`, a protein `sequence`, and optional text `label`. IDs are unique within the batch. The alphabet is `ACDEFGHIKLMNPQRSTVWYBXZJUO` plus `_`. `X` is an unknown residue, `B/Z/J` are ambiguous residue codes, `U/O` are retained single-letter identities, and `_` is an unfilled position. Blanks are never silently rewritten as X, removed or completed. Each consumer checks its own operation and tool restrictions.

Optional `source` contains explicitly supplied text fields `name`, `record` and/or `text`. Sequence/FASTA import records the selected filename when present, the FASTA header as `record`, and the original input text unchanged. Headers remain descriptive text; chain IDs and author numbering come from explicit correspondence.

Optional `positions` contains exactly one entry per sequence residue, in sequence order. Every entry has a one-based `sequence_index`. Optional stable `id` values must be nonempty, unique and supplied for every position when used. Author correspondence, when known, supplies all three fields `chain` (text), `author_number` (integer) and `insertion_code` (text, empty when absent). Independent optional `label_position: {chain, position}` supplies the source mmCIF label chain and positive one-based polymer position. Either correspondence or both can be present; a known label is retained even when author numbering is unknown. Repeated identities within either coordinate system or incomplete supplied fields fail. New positions without source correspondence and plain sequence/FASTA imports supply only sequence indices. This example retains an insertion and a numbering gap:

```json
{"objects":[{"id":"source-fragment","sequence":"ACD","source":{"name":"selection.json"},"positions":[{"sequence_index":1,"chain":"Z","author_number":12,"insertion_code":""},{"sequence_index":2,"chain":"Z","author_number":12,"insertion_code":"A"},{"sequence_index":3,"chain":"Z","author_number":19,"insertion_code":""}]}]}
```

The sequence action accepts single sequence/FASTA, explicit batch FASTA, or sequence JSON. Single mode directs multi-record FASTA to batch import. JSON preserves supplied object identities, source and correspondence. `modules.sequence_io.formats.read_sequences(package)` is the optional public Python reader; independent consumers may read the format directly. Missing content required by a selected operation produces an error.

## Export

`workbench.export_sequences` accepts one `workbench.sequence` package on `sequences`. The optional `objects` parameter is an ordered list of explicit object IDs; omission exports all input objects in input order. Its `files` output has format `workbench.sequence_export`, with `manifest.json` containing the selected unchanged sequence objects and export parameters, and `sequences.fasta` containing those sequences. FASTA export requires filled positions and rejects `_` with an object/position error. All supported letters, including X, are exported unchanged. Save the input package as ZIP to preserve unfilled positions. FASTA headers use labels or object IDs on one line; the manifest preserves the original text and correspondence. Download the delivered package as ZIP.
