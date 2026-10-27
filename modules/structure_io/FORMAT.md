# Complete structure files

`workbench.structure_file` has a JSON entry with exactly `name` (original filename),
`file` (one package file key), and `format` (`pdb` or `mmcif`). One package imports
one coordinate file. `workbench.import_structure` takes `models`: an actual integer
model number, or `all` to deliver independent candidates for every model. Missing
or unavailable selection fails with the available numbers. Alternate atom locations
remain in each candidate.

`workbench.structure_set` has a JSON entry containing `objects`. Each object has an
independently assigned `id`, optional `label`, `structure: {file, format}`, and an
`atoms` JSON file key. Import also supplies `source: {name, file, format, model}`,
where `file` contains the unchanged original research file. All referenced keys
are included in the package. The object contains one model; its actual model,
author chain, residue number, insertion code, atom names and alternate locations
are retained. Every protein, ligand, metal, water and nucleic component atom is
included. Import requires actual author correspondence, finite coordinates,
occupancy and B factor; missing information fails rather than being inferred
from label numbering. mmCIF must contain one coordinate data block.

The atom file is an ordered array of `{index, model, chain, author_number,
insertion_code, residue_name, atom_name, element, altloc, position}`. `index` is a
zero-based index into that candidate's delivered structure-file atom hierarchy;
`position` is Cartesian x/y/z in Å. This file supports the module's viewer and
selection. Consumers performing calculations read the actual coordinate file.
Comparison accepts candidate batches and checks each object's tool conditions.
Its reference input requires one explicitly selected object. Collection selection
and extraction can prepare that reference from a multi-object package.

`workbench.export_structure` accepts structure sets or existing
`workbench.prediction` and `workbench.structure_confidence` packages. Parameters select `object` by its existing ID,
`format` (`pdb` or `mmcif`), and optionally `atoms` (unique nonempty zero-based
indices in the selected file's hierarchy). Omitting `atoms` exports the complete
candidate. Outputs retain source files and existing parameter records, add the
selected coordinate file and atom view file, and record `selection:
{source_object, atoms}` (`atoms: "all"` for full export) plus `source_object`
containing the selected source description. `source_manifest: {file, format}` points
to the preserved source entry under its own package file key, retaining existing
evaluation methods, regions, values and calculation parameters. `export-notes.txt` explains that
existing calculation parameters describe the source calculation and that export
does not recalculate the selected component. Original input and calculated
results acquire no invented prediction relationship.

PDB export rejects chain names longer than one ASCII character, model/serial,
residue, component-name, atom-name, coordinate, formal-charge, occupancy or B-factor fields that
exceed PDB widths. Choose mmCIF for those structures. PDB coordinates use its
specified three-decimal representation. Export preserves all selected atoms and
never renumbers residue identities to fit a format. The current PDB writer cannot
preserve lowercase alternate-location identifiers exactly; PDB export and PDB
import candidate creation reject those selected atoms with a specific error.
Use mmCIF to retain those identifiers.

Use the public `workbench.structure_io` React action to select one file and its
model policy, then run the import node. The viewer selects candidates, rotates
actual coordinates and selects atoms or complete residues/components. Add an
export node with the chosen format, run it and download its package ZIP. Existing
prediction result viewers also provide the format export action. Generic ZIP
packaging retains the module's declared files and existing parameter records.

## Public structure processing

Install this module with `modules.structure_io:module`; it has no dependency on
sequence/condition editing. The installable Python code is supplied by the
`protein-workbench` distribution, with `gemmi==0.7.3`. A consumer voluntarily
importing these public functions declares `protein-workbench` in its Python
installation dependencies. A consumer reading this format independently needs
only its own coordinate reader. Module installation and shared React dependencies
follow [module authoring](../../docs/module-authoring.md).

The public Python entry `modules.structure_io` exports:

- `parse(bytes, encoding)` and `encode(structure, encoding)` read/write Gemmi
  structures as PDB or mmCIF with the preservation limits above.
- `read_structure(package, object_id)` reads exactly one selected object through
  the public `Package` file interface. It requires the declared coordinate file,
  a single conformation and an unambiguous object ID.
- `atoms(structure)` returns the atom mapping described above.
- `positions(structure)` returns actual component positions, each with `model`,
  `chain`, `author_number`, `insertion_code`, `residue_name` and `atoms`. Each
  atom has `index`, `name`, `altloc` and Cartesian `position`.
- `resolve_selection(structure, selection=None)` returns atom indices in source
  file order. A selection has exactly one key: `atoms`, `chains`, or `positions`,
  whose value is a nonempty list. Atom indices and chain names are unique and
  must exist. Every position specifies `chain`, integer `author_number` and
  `insertion_code` (including the empty string); optional `model` and
  `residue_name` disambiguate components. Every requested position must match
  exactly one actual component. All its atoms and alternate locations are
  selected. Missing or ambiguous selections fail in full.
- `extract(structure, selection)` returns a clone containing only selected atoms.
  Its current polymer entities describe the retained residue groups, with local
  sequence labels; separate subchains can retain different fragments of a shared
  source entity. Alternate components at one residue position share one label.
  Ambiguous polymer membership or different retained groups for the same
  subchain across models fail with a specific explanation.
- `transform(structure, rotation, translation, selection=None)` returns a clone
  retaining every atom. Selected atoms receive `rotation @ xyz + translation`;
  their anisotropic displacement tensors receive `rotation @ U @ rotation.T`.
  Translation leaves these tensors unchanged; unselected atoms retain both
  coordinates and tensors. The finite 3×3 matrix is a proper
  orthonormal rotation (tolerance 1e-6), applied about the coordinate origin;
  translation is three finite values in Å. Reflections, scale and shear fail.
  Omitting the selection selects all atoms.

The input to these operations remains unchanged. Selection retains original
model, author numbering, insertion codes, component names and alternate locations.
Extraction does not fill missing atoms, complete residues or expand the selection.

`workbench.extract_structure` and `workbench.transform_structure` accept
`workbench.structure_set` and `workbench.prediction` and deliver `workbench.structure_set`. Both take `object`, `format` and `selection` in
the public form above; extraction requires selection, transformation permits it
to be omitted and additionally requires `rotation` and `translation`. The output
object records `operation: {kind, selection}` (plus rotation and translation for
transformation), and `source_object` contains the previous object description.
All source package files and existing calculation records are retained. New
object IDs are independently assigned. Existing calculation parameters continue
to describe the source calculation. `workbench.export_structure` is the explicit
format conversion node; it retains its optional atom selection contract above.

In the complete structure viewer, select chains, residues/components or individual
atoms; the coordinate table shows their actual positions. Add an extraction node,
choose an export format, or enter a rotation matrix and translation to add a
coordinate transform node. Run the node on the canvas, open its output package to
inspect the result and download the ZIP to save its files. Rotation/tilt view
controls only change the viewing angle. Coordinate transformations execute only
through the explicit transform node.

## Complete design target mmCIF

`modules.structure_io.target.write_target(positions, chain="A")` returns mmCIF
bytes for one complete ordered protein target. Each input row has `residue`,
optional `author_number`, `insertion_code`, `author_chain`, and `atoms` mapping
actual atom names to finite XYZ coordinates. Source author numbers may be absent;
the writer leaves those unknown. Unknown or masked residues use `UNK`/`X`.

The file's `_entity_poly_seq` declares every position; `_pdbx_poly_seq_scheme`
records target order and actual author correspondence; `_atom_site` contains
only supplied atoms. Missing coordinates do not remove polymer positions.
Current target labels and preserved author numbers have separate meanings.

`read_target(bytes_or_text, chain=None)` returns `{chain, sequence, positions}`.
Each position contains one-based `position`, `residue`, `author_number` (integer
or `None`), `insertion_code`, `author_chain`, and `atoms`. Without an explicit
chain, the file must declare one chain. The reader requires the complete ordered
polymer and residue scheme, one coordinate conformation, finite coordinates and
unambiguous atom names. It reads coordinate-free targets without constructing
fictional atoms. This public reader depends only on Gemmi, with no editor or
model adapter dependency. Independent consumers can read the documented standard
mmCIF categories directly.

`polymer_positions(package, object_id, author_chain)` reads a complete source
protein chain. It returns the public component-position rows above plus optional
`label_position: {chain, position}` from the source mmCIF. Declared unobserved
positions have empty `atoms`, their known author numbering or `None`, and the
actual sequence label. mmCIF correspondence must be explicit and unique. A PDB
whose SEQRES length exceeds its actual residues cannot supply that missing
correspondence: choose explicit observed residues or provide mmCIF with sequence
labels. Non-amino-acid components on the same author chain are excluded from
protein-position rows without changing the source structure. Protein residues
remain paired with their actual atoms and sequence labels, including when water
or metal records are interspersed in the coordinate file.

Whole-structure mmCIF import, conversion, export and rigid transformation preserve
the original `_pdbx_poly_seq_scheme`, including known author numbers at positions
without atoms. Fragment extraction rebuilds current polymer labels from the
selected actual residues; the unchanged full source file is retained separately.

## Current coordinate tracks and existing annotations

Processing and export also accept [`workbench.coordinates`](../sequence_edit/FORMAT.md#independent-track-outputs).
Its structure file contains current atoms, with current positions numbered 1…N
on chain A. Readers validate this file against `values` and `residues` before
processing; missing atoms are never refilled from retained originals. Omit the
object selector only for a single-object package.

`existing_tracks(source, object_id, selected_positions)` reads existing
secondary-structure records and explicitly supplied `tracks.secondary_structure`,
`tracks.sasa` and `tracks.function_annotations`. Supplied tracks require an ordered
`positions` list with chain, author number and insertion code; arrays must cover
that list and annotation intervals use its one-based positions. The function
maps these values to the requested polymer positions. Supplied values take
precedence over file records, including nulls. It performs no secondary-structure,
SASA or annotation calculation.
