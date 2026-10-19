# Independent structure comparison

Factory: `modules.structure_comparison:module`. The `workbench.compare` node reads one `workbench.prediction` or `workbench.structure_set` subject and one independently selected `workbench.reference` or `workbench.structure_set`. Imported structure sets follow the [complete structure format](../structure_io/FORMAT.md); each input must contain exactly one selected candidate. It reads the [prediction file format](../folding/FORMAT.md) directly; the prediction producer need not be installed or registered. A reference has no required generation relationship to the subject.

## Reference input: workbench.reference

The JSON entry contains exactly one object:

```json
{"objects":[{"id":"reference-object","label":"Optional display name","structure":{"file":"reference.cif","format":"mmcif"}}]}
```

`id` is a nonempty independently allocated object identity. `structure.file` is a declared package file key containing the complete unchanged structure. `format` is `pdb` or `mmcif`; `label` is optional. The UI imports one file per action and creates a comparison node with its reference port populated. Connect a prediction output or select an existing prediction package for the subject port. Unsupported multiple conformations must be selected as a single structure before comparison.

## Method and supported inputs

The operation uses `tmtools==0.3.0`, underlying TM-align 20210224, with native optimized alignment and default algorithm settings. The installed SDK's `tm_align` documentation and [official release notes](https://github.com/jvkersch/tmtools/blob/main/CHANGES.md) define its coordinate/sequence input and native scores. It accepts one model and one canonical protein chain in each selected scope, with at least three residues. It does not perform multichain assignment. A complete multichain input requires explicit single-chain selection before this tool can run.

Node parameters `subject_selection` and `reference_selection` independently select the evaluation scope. Omit either parameter or use null for that side's complete structure. Otherwise use the structure processing module's public selection form:

```json
{"subject_selection":{"chains":["A"]},"reference_selection":{"positions":[{"chain":"R","author_number":12,"insertion_code":"A"},{"chain":"R","author_number":16,"insertion_code":""},{"chain":"R","author_number":20,"insertion_code":""}]}}
```

A chain selection names exactly one chain. A position selection contains unique actual residue positions on exactly one chain; every selected component must be a canonical protein residue. The node editor provides complete/chain/discontinuous scope controls, a chain name and comma-separated actual residue numbers with insertion codes, such as `12, 12A, 16` (or `12:1` for numeric insertion codes). Apply each side's selection, then save and run. Users do not supply a residue index map or object IDs. Import or export one candidate when a source package contains multiple candidates.

Selection resolves against the full original coordinate file, retaining author numbering and insertion codes. Selected residues enter TM-align in coordinate-file order as one Cα/sequence stream, giving one rigid transform for all selected regions together. A selection never crops either saved original. Prediction sequence is validated against the complete observed canonical protein stream before regional evaluation. Each selected residue requires one unambiguous Cα without alternate locations. Complete/whole-chain selections also require any declared entity sequence to match resolved residues; explicit residue selection can evaluate observed positions despite unresolved positions elsewhere. Numbering gaps alone do not establish missing residues.

Missing or ambiguous real positions, repeated positions, modified or unknown selected protein residues, missing selected Cα and incomplete prediction sequence correspondence fail. Selected nucleic acids are unsupported. Ligands, metals, water, unselected chains and other unselected components remain in the original files and all-atom overlay; only the selected canonical protein stream enters the metric calculation.

TM-align can align unequal lengths and return gaps. Every selected residue remains represented in its aligned position axis, including residues opposite gaps; gaps are null positions. The computed correspondence may relate different author numbers or chain names across independently selected subject and reference regions.

## Result: workbench.comparison

The JSON entry `manifest.json` contains:

- `id`: newly allocated comparison identity.
- `subject` and `reference`: original object `id`, optional `label`, and `structure: {file, format}`. Both full original structure byte streams are included. An available input `sequence` is preserved. `generation` preserves the subject's prediction `tool: {id, parameters}` and any supplied `input` sequence object (source and input-position correspondence) separately from this subject/reference evaluation relationship. The selected reference acquires no generation-parent relationship.
- `region`: `subject` and `reference` independently contain the requested selection, or null for complete structure. The alignment axes give the actual ordered residues used.
- `method`: `name: "TM-align"`, pinned `tmtools` and underlying `algorithm`, explicit `scope`, and `parameters: {}` for native defaults.
- `metrics.tm_subject`: native `tm_norm_chain1`, normalized by the selected subject protein residue count; `metrics.tm_reference`: native `tm_norm_chain2`, normalized by the selected reference protein residue count. Both are dimensionless, with `value`, human-readable `normalization` and `normalization_length` fields. `metrics.rmsd` is native aligned-pair Cα RMSD in angstroms with an explicit scope and `aligned_pair_count`. A low RMSD may cover only a small aligned subset; both native TM-scores retain selected-stream length normalization.
- `alignment`: `subject_sequence`, `reference_sequence`, native `markers` and equal-length `subject_positions`/`reference_positions`. Each nongap position is `{chain, author_number, insertion_code}` using the original author chain, integer numbering and insertion code. Each gap is null. Sequence letters without gaps cover the entire corresponding selected protein stream.
- `transform`: `direction: "subject to reference"`, `rotation` (3×3) and `translation` (3). For an original row coordinate `x`, apply `x @ rotation.T + translation`. Reference coordinates stay fixed. This transform applies to all subject atoms, including other components.
- `overlay`: package file key `overlay.json`. Its `subject` and `reference` arrays contain all atoms in the reference coordinate frame. Every atom includes `position` (three angstrom coordinates), original `chain`, `author_number`, `insertion_code`, `residue_name`, `atom_name`, `element`, `altloc`, and `component` (`protein` or `other`). The full original files retain all additional source fields in their original coordinate frame, including anisotropic displacement tensors. Overlay JSON contains display coordinates and atom identities; its fields are defined above.

The viewer uses only these delivered files and its supplied React runtime. Its orthographic atom display rotates and tilts, shows/hides either structure, and identifies selected atoms from every component. No producer, source project, source run or external browser library is needed to reopen the overlay. A complete package example is in `sample/`.

## Public execution reuse

`modules.structure_comparison.api` provides `StructureInput(object_id, content, format, sequence=None, label=None, generation=None)`, `read_prediction(package)`, `read_reference(package)`, `read_structure_set(package)`, `read_comparison_input(package)` and `comparison_parameters(parameters)` and `compare(subject, reference, runtime, *, subject_selection=None, reference_selection=None)`. `StructureInput` is frozen; `content` is the complete original bytes. Supplying `sequence` requests exact sequence/residue validation. `compare` returns a public `Outcome` on port `comparison`, writing all delivered files inside `runtime.workdir`. Cancellation is checked before parsing and after the synchronous lightweight TM-align call. Errors stop the operation with a specific exception; input bytes remain unchanged.

Comparison voluntarily imports only `parse` and `resolve_selection` from the public `modules.structure_io` entry. Installing comparison therefore requires the `protein-workbench` distribution containing structure processing; `gemmi==0.7.3`, `numpy==2.5.1` and `tmtools==0.3.0` are pinned distribution dependencies. No private structure processing or host scientific code is imported. The structure processing module need not be enabled to read comparison output files.

The comparison UI supplies the same region editor for `workbench.compare` and the explicitly converted `workbench.compare_structure` consumer.

A converted-format consumer may independently parse its own format into `StructureInput` and call `compare`. That consumer must declare installation of this comparison module's distribution (`protein-workbench` in this repository) as a dependency. Reuse creates a dependency on comparison execution, while reading the prediction format creates no dependency on the producer. No host scientific registry participates.
