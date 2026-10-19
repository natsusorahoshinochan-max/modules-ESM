# Independent structure comparison

Factory: `modules.structure_comparison:module`. The `workbench.compare` node reads one `workbench.prediction` subject and one independently selected `workbench.reference`. It reads the [prediction file format](../folding/FORMAT.md) directly; the prediction producer need not be installed or registered. A reference has no required generation relationship to the subject.

## Reference input: workbench.reference

The JSON entry contains exactly one object:

```json
{"objects":[{"id":"reference-object","label":"Optional display name","structure":{"file":"reference.cif","format":"mmcif"}}]}
```

`id` is a nonempty independently allocated object identity. `structure.file` is a declared package file key containing the complete unchanged structure. `format` is `pdb` or `mmcif`; `label` is optional. The UI imports one file per action and creates a comparison node with its reference port populated. Connect a prediction output or select an existing prediction package for the subject port. Unsupported multiple conformations must be selected as a single structure before comparison.

## Method and supported inputs

The current complete-structure operation uses `tmtools==0.3.0`, underlying TM-align 20210224, with native optimized alignment and its default algorithm settings. It accepts exactly one model and one canonical protein chain on each side, with at least three residues. Each observed protein residue must have one Cα without alternate locations. All observed protein residues enter the calculation in file order. Prediction sequence must exactly match this complete residue stream. Where SEQRES or mmCIF entity sequence is declared, it must match the resolved chain; unresolved residues cause failure. Numbering gaps alone do not establish missing residues.

Multiple protein chains, nucleic acids, modified or unknown protein residues, missing Cα, ambiguous residue identities and incomplete sequence correspondence produce explicit errors. Chain assignment and region extraction are separate tasks. Ligands, metals and water remain in the two original files and the all-atom overlay. The metric scope is the complete protein Cα stream; these other components do not enter TM-align.

TM-align can align unequal lengths and return gaps. Every residue remains represented in its aligned position axis, including residues opposite gaps; gaps are null positions. These method-selected gaps are recorded in full.

## Result: workbench.comparison

The JSON entry `manifest.json` contains:

- `id`: newly allocated comparison identity.
- `subject` and `reference`: original object `id`, optional `label`, and `structure: {file, format}`. Both full original structure byte streams are included. An available input `sequence` is preserved. `generation` preserves the subject's prediction `tool: {id, parameters}` separately from this subject/reference evaluation relationship. The selected reference acquires no generation-parent relationship.
- `method`: `name: "TM-align"`, pinned `tmtools` and underlying `algorithm`, explicit `scope`, and `parameters: {}` for native defaults.
- `metrics.tm_subject`: native `tm_norm_chain1`, normalized by the subject protein residue count; `metrics.tm_reference`: native `tm_norm_chain2`, normalized by the reference protein residue count. Both are dimensionless, with `value`, human-readable `normalization` and `normalization_length` fields. `metrics.rmsd` is native aligned-pair Cα RMSD in angstroms with an explicit scope and `aligned_pair_count`. A low RMSD may cover only a small aligned subset; both native TM-scores retain full-chain length normalization.
- `alignment`: `subject_sequence`, `reference_sequence`, native `markers` and equal-length `subject_positions`/`reference_positions`. Each nongap position is `{chain, author_number, insertion_code}` using the original author chain, integer numbering and insertion code. Each gap is null. Sequence letters without gaps cover the entire corresponding protein chain.
- `transform`: `direction: "subject to reference"`, `rotation` (3×3) and `translation` (3). For an original row coordinate `x`, apply `x @ rotation.T + translation`. Reference coordinates stay fixed. This transform applies to all subject atoms, including other components.
- `overlay`: package file key `overlay.json`. Its `subject` and `reference` arrays contain all atoms in the reference coordinate frame. Every atom includes `position` (three angstrom coordinates), original `chain`, `author_number`, `insertion_code`, `residue_name`, `atom_name`, `element`, `altloc`, and `component` (`protein` or `other`). The full original files retain all additional source fields.

The viewer uses only these delivered files and its supplied React runtime. Its orthographic atom display rotates and tilts, shows/hides either structure, and identifies selected atoms from every component. No producer, source project, source run or external browser library is needed to reopen the overlay. A complete package example is in `sample/`.

## Public execution reuse

`modules.structure_comparison.api` provides `StructureInput(object_id, content, format, sequence=None, label=None, generation=None)`, `read_prediction(package)`, `read_reference(package)` and `compare(subject, reference, runtime)`. `StructureInput` is frozen; `content` is the complete original bytes. Supplying `sequence` requests exact sequence/residue validation. `compare` returns a public `Outcome` on port `comparison`, writing all delivered files inside `runtime.workdir`. Cancellation is checked before parsing and after the synchronous lightweight TM-align call. Errors stop the operation with a specific exception; input bytes remain unchanged.

A converted-format consumer may independently parse its own format into `StructureInput` and call `compare`. That consumer must declare installation of this comparison module's distribution (`protein-workbench` in this repository) as a dependency. Reuse creates a dependency on comparison execution, while reading the prediction format creates no dependency on the producer. No host scientific registry participates.
