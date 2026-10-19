# Existing metric analysis

Install `modules.metric_analysis:module`. Add **Existing metric analysis**, bind
explicit delivered packages on `metrics`, and choose **Inspect existing metrics**
in the node editor. The input may contain several packages. Choose the displayed
object/context, reference, existing evaluation or generation method, metric and
stochastic sample. For a positional metric, select individual actual chain,
author-number and insertion-code checkboxes; chain controls narrow the displayed
positions. Apply selections, then save and run through the canvas. Each node owns
its input list and selections; canvas composition determines batch/group scope.

`workbench.analyze_metrics` reads these concrete public formats directly, without
installing or calling their producers:

| Input | Existing values used |
| --- | --- |
| [`workbench.structure_confidence`](../structure_confidence/FORMAT.md) | Explicit evaluation `values` scalars; `per_position` JSON `positions` / `plddt` |
| [`workbench.prediction`](../folding/FORMAT.md#workbenchprediction) | Source-generation pLDDT fractions and whole-prediction pTM |
| [`workbench.comparison`](../structure_comparison/FORMAT.md) | Saved native TM-scores and aligned-pair RMSD, with their original normalization/scope |
| [`workbench.solubility`](../solubility/FORMAT.md) | Named scalar values of the selected actual sequence evaluation |
| [`workbench.sequence_backbone_evaluation`](../sequence_backbone_evaluation/FORMAT.md) | Explicit sample's native `score`, `global_score`, `region_nll`, or mapped `residue_nll`, retaining the complete joint sequence context |

Natural prediction pLDDT uses the complete coordinate file's observed canonical
protein sequence order only when it exactly matches the supplied prediction
sequence on one chain. Parsing establishes position correspondence; numbers
come from the existing confidence file. This path voluntarily uses the public
`modules.structure_io.parse` API, so installation requires the
`protein-workbench` distribution containing structure processing and its pinned
Gemmi dependency. Other producer formats are parsed independently in this module.
React 19 is supplied through the public host contract.

A scalar retains its original evaluation scope. A requested new positional region
requires complete existing per-position values. Missing files, nonfinite values,
ambiguous metric/sample selection, repeated or unavailable positions, and
incomplete sequence/value correspondence stop the operation. Backbone residue
analysis also requires valid coordinate-mask positions; fixed residues retain
their recorded NLL and original design mask. Samples are selected separately.
Backbone `region_nll` requires its sample's region mask to match the declared
actual region exactly in each chain's tool-position order, including zeros
outside the region. A null source region requires the complete actual axis.
Analysis performs arithmetic mean, minimum, maximum and count; it does not invoke
scientific tools or generate missing metric values.

## Parameters and inspection

`selections` is a nonempty ordered array. Each entry has `input` (zero-based index
in the explicit `metrics` port package list), the complete selector returned by
`workbench.inspect_metrics`, and optional `region` (nonempty unique actual
`{chain, author_number, insertion_code}` positions). The interaction's selectors
use these concrete source-specific fields:

- Evaluation scalars and independent confidence: `object`, `origin: "evaluation"`,
  `evaluation` (array index), `metric`.
- Natural prediction confidence: `object`, `origin: "generation"`, `metric`.
- Comparison: `object` (subject), `origin: "comparison"`, `metric`; the reference
  comes from the explicitly chosen comparison package.
- Sequence/backbone: `objects` (the complete original `object_ids` list),
  `origin: "sequence_backbone"`, `evaluation`, `sample`, `metric`.

The editor manages these selectors internally. It displays descriptive labels,
actual methods, regions and sample numbers. `workbench.inspect_metrics` accepts
only the explicitly supplied packages and returns choices with actual positions,
unit and meaning. A candidate whose necessary values or correspondence cannot be
read remains listed with `unavailable` containing the specific reason; unrelated
valid candidates remain selectable. Existing unavailable selections can be removed
explicitly, and Apply requires every retained selection to be available. Analysis
independently resolves only each selected metric's necessary dependencies.
Unidentifiable objects or ownership fail inspection. Inspection creates no run or
saved analysis. Node/project/draft
changes invalidate pending displays, and temporary interaction handles are
released after display data is read.

## Result: workbench.metric_analysis

The JSON entry contains `sources` and ordered `analyses`. All original input
files are copied unchanged. Each `sources` entry records the original `format`,
original entry key `entry`, and `files` mapping every original package file key
to its actual key in this analysis package. Resolve source-manifest references
and copied object/reference descriptions through that source's file map.

Each analysis contains:

- `source`: index into `sources`; `selection`: the exact source selector.
- `object`: original object description, or `{members, label}` for the complete
  explicitly evaluated sequence/backbone context. `members` retains the actual
  original sequence objects. `reference` retains the evaluation reference or null.
- `source_region`, `source_method`, `metric`, `unit`, `meaning`: original scope,
  actual source method and numeric interpretation, separate from this analysis.
- `positions`: ordered actual positions for positional data, otherwise null.
  `region` gives those analyzed positions or the scalar's original scope.
- `input_values`: existing values in that same order, or one existing scalar.
- `method: "arithmetic mean, minimum, maximum of existing values"` and
  `statistics: {count, mean, minimum, maximum}`. Mean/minimum/maximum retain the
  source metric's unit; count is the number of selected existing values.
- Backbone analyses additionally retain explicit `sample` and original sequence,
  coordinate/design/region masks in `context`.

`modules.metric_analysis.formats.read_analysis(package)` is a standard-library
standalone consumer. It reads declared result/source files through the public
Package interface. Saved and adopted packages retain every source structure,
evaluation, generation record and research file. They remain independently
readable after the source project and producer modules are removed. The module
viewer shows actual methods, reference, scope, statistics and input values;
ordinary host save, ZIP export and adoption operations handle all files.
