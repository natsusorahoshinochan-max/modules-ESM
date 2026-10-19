# ESM3 sequence completion and conditioned generation

Install `modules.esm3:module`. **Complete or generate a conditioned sequence** reads either canonical `workbench.sequence` objects or the current [sequence editing document](../sequence_edit/FORMAT.md). Use the editor to create masks, fix residues and adopt coordinate conditions. The task submits the current ordered Prompt: fixed positions contain their residues and variable positions contain `_`. Coordinates use the same current position order, including inserted positions. Extra supported conditions are configured in the node's `conditions` object: aligned `secondary_structure`, aligned `sasa`, inclusive one-based `function_annotations`, and the Biohub `potential_sequence_of_concern` disclosure flag. No earlier editing operation is replayed.

Invalid conditions JSON remains an unsaved local draft and blocks saving and running until corrected. Polling and unrelated parameter edits preserve that text; leaving the project follows the ordinary discard confirmation.

`samples` is the positive number of independent requests per source, in source order then sample order. Tool computation controls and local seed belong to the selected tool; see [TOOL.md](TOOL.md). A failed exhausted request stops requests that have not started. Successful prefixes remain viewable and exportable. Continue uses the original input, tool and parameters, skips accepted successful requests and returns cumulative results. A failed file reception leaves the previous accepted progress intact.

## workbench.esm3_generation

The JSON entry contains `objects`, `batch` and `tool`. `batch` records `completed`, `total` and `status`; `tool` records the selected implementation ID and supplied computation parameters, excluding deployment settings and credentials. Each generated object has:

- An independently allocated `id` and actual native `sequence` string. Native `X`, `B`, `Z`, `U`, `O`, `.`, `-` and chain separator `|` are retained when returned; incomplete masks fail. No `invalid_ids` are inserted to force canonical output.
- Ordered `positions`, one entry for every output string position, including a `|` separator. `sequence_index` is one-based in that complete string. `edit_position` identifies the corresponding current editor position when applicable. Optional `source` retains the selected input object's identity, sequence index and complete original position record, including chain, residue number and insertion code. Optional `structure_position` retains the current editing record’s separate structure ID and complete actual component position (`model`, `chain`, `author_number`, `insertion_code`, `residue_name`). These are input correspondences; no new structure numbering is invented. Current coordinate values are contained directly in `generation.tracks`; interpreting them does not require retained editing files.
- `generation: {input, sample, tracks}` describes this actual call's source editing/sequence object, one-based sample ordinal and full supplied Prompt/condition tracks.
- `native: {file}` names the complete native output JSON in this package.
- `tool: {parameters, actual_seed}` records effective controls returned by the adapter. `actual_seed` is the literal local torch seed or `null` for Biohub. The SDK may reduce `num_steps` internally; the post-call config value is recorded where the SDK changes it.

Native files contain `tracks` and `metrics`. Available sequence, secondary structure, SASA and function annotation tracks retain their native values. Coordinates retain the SDK's atom37 array order in Å; missing coordinate elements are JSON `null`. The second coordinate axis is the following atom order, also exported as `modules.esm3.adapters.ATOM37`:

```text
N CA C CB O CG CG1 CG2 OG OG1 SG CD CD1 CD2 ND1 ND2 OD1 OD2 SD CE CE1 CE2 CE3 NE NE1 NE2 OE1 OE2 CH2 NH1 NH2 OH CZ CZ2 CZ3 NZ OXT
```

 Scores are retained exactly without additional inference or rescaling: native pLDDT is 0–1, pTM is its native scalar/batch-shaped value, PAE is in Å. Metrics are optional, only present when naturally returned. Arrays retain the selected SDK/backend's actual axes: local structure decoding returns residue-only pLDDT, batch-shaped pTM, and batch/BOS/EOS axes for PAE; consumers must interpret these native axes explicitly. These scores belong to this generation/reconstruction, with no independent evaluation relation.

Every referenced native file is included. An independent consumer can read the manifest and files through `Package.open`, after adoption, source project deletion or producer uninstall. Private continuation state is unnecessary for reading results.

## Explicit canonical sequence conversion

**Use a generated chain as sequence** accepts `workbench.esm3_generation`. For multi-chain output, select a zero-based `chain_index` split at actual `|` separators. A single chain may omit the index. The selected chain must contain only the 20 canonical amino acids; extended symbols fail with a specific reason. Conversion creates ordinary independent sequence identities and preserves available source chain/residue/insertion correspondence for the selected positions. It never rewrites extended symbols, joins chains or limits native generation sampling.
