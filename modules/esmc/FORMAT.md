# ESMC representations

`modules.esmc:module` provides `workbench.represent`, accepting the documented
[`workbench.sequence`](../folding/FORMAT.md) format. Its independent reader accepts
complete canonical protein sequences and preserves each input object, source and
explicit sequence-to-structure position mapping. No producer module installation
is required to read these files.

The output format is `workbench.esmc`. Its JSON entry contains `objects`, `tool`
(actual selected tool ID and resolved computation parameters) and `parameters` (requested
outputs and saved dtype). Every object has:

- `input`: the complete supplied sequence object.
- `model`: the actual remote wire model ID or local native HF configuration, with
  its backend.
- `tokens`: actual encoded order, zero-based `index`, integer `id`, and a `name`
  when the fixed tokenizer names that ID. A residue token also has one-based
  `sequence_index`, indexing `input.positions` when supplied. Added tokens and
  padding have no residue index.
- Optional `mean_embedding`: a numeric descriptor with its pooling `semantics`.
- Optional `logits`: a numeric descriptor, `semantics` and `columns`. Each column
  has its actual zero-based `index`; only named tokenizer IDs have `name`.

Logits include every actual token position, including special tokens and padding,
and every returned column. They are raw logits. Column widths and embedding
lengths come from actual results. Local mean embedding averages only tokens
mapped to actual input residues. Remote mean embedding preserves the service's
returned vector; the service has not specified its special-token exclusion rule.

Each numeric descriptor contains `shape`, `dtype` (`float32` or `float16`),
`byte_order: "little"`, and ordered `pages` with `file`, `start` and `rows`.
The page file holds contiguous, row-major IEEE floating point bytes with no
header. Vector pages contain up to 64 components; matrix pages contain up to 64
rows of all columns. `start` is the first vector component or matrix token row.
Only requested arrays are present. All declared files are closed before handoff.

For example, a descriptor for a two-component mean may be
`{"shape":[2],"dtype":"float32","byte_order":"little","pages":[{"file":"0-mean-0.bin","start":0,"rows":2}],"semantics":"…"}`.
The bytes `00 00 80 40 00 00 c0 40` encode `[4, 6]`.

Python consumers may use `read_manifest(package)` and
`read_page(package, descriptor, page_index)` from `modules.esmc.formats`.
`read_array` explicitly materializes all pages for consumers that need a full
array. Independent consumers can use the format above without importing the
module. The React viewer fetches one numeric page at a time, offers eight-column
windows, and shows actual values with token and source positions. Generic file
access and ZIP export retain every page plus the computation parameters.
