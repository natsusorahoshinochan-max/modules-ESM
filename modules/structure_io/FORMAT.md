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
Comparison independently accepts exactly one candidate and checks its own tool
conditions. Multi-candidate packages require an explicit one-candidate export
before comparison.

`workbench.export_structure` accepts structure sets or existing
`workbench.prediction` packages. Parameters select `object` by its existing ID,
`format` (`pdb` or `mmcif`), and optionally `atoms` (unique nonempty zero-based
indices in the selected file's hierarchy). Omitting `atoms` exports the complete
candidate. Outputs retain source files and existing parameter records, add the
selected coordinate file and atom view file, and record `selection:
{source_object, atoms}` (`atoms: "all"` for full export) plus `source_object`
containing the selected source description. `export-notes.txt` explains that
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
