# Existing structure confidence

`workbench.evaluate_structure_confidence` accepts one explicitly selected object
from `workbench.structure_set`, `workbench.prediction`, `workbench.confidence_input`
or `workbench.structure_confidence`. Set `object` to that supplied identity.
Optional `region` is a nonempty array of unique actual positions:
`{"chain":"Z","author_number":12,"insertion_code":"A"}`. Omit it or use null
for the whole structure. The complete selected structure goes to the tool;
region selection selects reported values and their mean. Unsupported components
or incomplete correspondence stop the selected tool with a concrete error.

The `workbench.structure_confidence` JSON entry preserves the input document's
`objects`, structure files, original research files and source generation scores.
It appends an `evaluations` entry with:

- `object_id`: the existing supplied object; no new generated object or parent.
- `reference`: null, since this evaluation has no experimental reference.
- `region`: null for the complete structure, otherwise the actual ordered positions.
- `origin`: `independent_existing_geometry`.
- `method`, `tool`, `parameters`, and `context`: the actual selected evaluator,
  its calculation parameters and numerical preprocessing/model context.
- `values.mean_plddt`: `{value, unit, meaning}`, where unit is `fraction (0–1)`.
- `per_position`: `{file, unit, meaning}`. Its declared JSON file contains
  `positions` (actual chain, author number, insertion code) and `plddt` (one
  finite 0–1 fraction per position in the same order).

Input source-generation confidence stays in the original object's `confidence`
field. Independent evaluations stay in `evaluations`; repeated evaluations append
rather than replace earlier values. `confidence_tool` describes the latest
selected tool; each evaluation also retains its own tool and parameters.

Consumers can parse this documented format without installing the producer, or
voluntarily use `modules.structure_confidence.formats.read_evaluations(package)`.
That reader checks actual file declarations, object attribution, score scales and
position/value correspondence through the public Package interface. It returns
the manifest; consumers open the per-position file for analysis. Analysis and
filtering can select the scalar `values.mean_plddt` or use the reported positions
and values, without running prediction or confidence models.

## Preparing and selecting regions

Open an existing package with the **Independent structure confidence** viewer.
Choose the structure and add an evaluation for the complete structure. To choose
residues, use the displayed actual chain/number/insertion-code checkboxes.
Imported structures already provide atom-position files. For packages without
those files, choose **Prepare region selection**, run that node, then open its
output and select residues before adding the evaluation node. Unchecked regions
mean the complete structure. The node editor shows the selected residues and
can reset to the complete structure.

`workbench.prepare_structure_confidence` reads the selected object and writes
`workbench.confidence_input`. It preserves the original objects and their files,
and adds `confidence_positions: {object_id: file}`; that file contains an ordered
actual-position array. This lightweight preparation performs no model evaluation
and creates no new structure. Its output is accepted by the evaluation node.
Results can be saved, reopened, adopted across projects and exported with the
host's ordinary package operations. All required coordinate and score files are
part of the delivered package.

## Tool replacement and installation

The public slot `workbench.evaluate.structure_confidence` is declared by this task.
Its Python contract is `modules.structure_confidence.contract`:
`evaluate(ConfidenceRequest, parameters, runtime) -> ConfidenceResult`.
The request carries an absolute existing coordinate file, its `pdb`/`mmcif`
encoding and complete actual residue positions in file order. The tool checks
its own applicability and must return every position in the same order with
0–1 pLDDT values, its actual method and optional numerical context. It must not
predict a replacement structure, drop components or reinterpret the requested
region. The node copies the original files before calling the tool and owns output
encoding. Failure raises a concrete error. Cancellation uses `runtime.cancelled`;
there is no batch continuation for this single selected-object operation.

The bundled modules are supplied by the `protein-workbench` Python distribution.
This task voluntarily imports `modules.structure_io.parse`; it therefore requires
the structure processing code and its declared Gemmi dependency. SimpleFold
voluntarily imports this public slot contract and requires this task's Python
code. External adapters importing that contract declare `protein-workbench` in
their installation dependencies. Format-only consumers need neither producer nor
its model dependencies. React 19 is supplied by the public host UI contract.
