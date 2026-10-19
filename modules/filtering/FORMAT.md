# Filtering and sorting

Install `modules.filtering:module` from the `protein-workbench` distribution.
The module explicitly depends on the public
[`modules.metric_analysis.read_metric_choices`](../metric_analysis/FORMAT.md#public-existing-metric-reader)
and [`modules.structure_io.parse` / `atoms`](../structure_io/FORMAT.md#public-structure-processing)
APIs in that distribution. React 19 is supplied by the host. Producer modules
need not be registered or enabled to read their delivered public formats.

## Inputs and entry points

`workbench.filter` is both a canvas node and a temporary interaction. Both take
ordered `candidates` and `evaluations` package lists and identical parameters.
They share input resolution, evaluation disambiguation, conditions, stable
sorting and quantity limits. Missing selected inputs or required values stop
the operation before output is produced, including values of candidates that
would fail another condition. All conditions are combined with AND.

Candidates accept `workbench.sequence`, `workbench.structure_set`,
`workbench.proteinmpnn_design`, the concrete source formats listed in the
[metric reader](../metric_analysis/FORMAT.md), and `workbench.filtered_collection`.
Evaluation inputs accept those metric formats, saved `workbench.metric_analysis`
statistics and filtered collections. Analysis results supply evaluations; bind
the original object packages separately as candidates.
An empty candidate list or an empty candidate package yields an empty collection.
A comparison package supplies its actual subject. A sequence/backbone package
supplies each complete explicitly evaluated joint sequence context as one item;
its score cannot be assigned to a single member sequence. A native ESM3 generation
is likewise one complete object, including all chains and its original native file.

In the canvas, bind delivered packages explicitly using the port's multiple
selection control. **Inspect selected inputs** lists each candidate and its actual
metric, method, reference, original region, sample, unit and meaning. Unavailable
values remain listed with their reason. Select the exact evaluation for each
candidate and operation. Parameter changes update only the current node; **Copy
node** copies its complete settings and direct inputs. Save manually before running.

On the result page, **Temporary filter and sort** provides separate explicit
candidate-package and evaluation-package checkboxes from the current project's
available packages. Set conditions, direction and quantity limit, then **Apply
temporary filter**. Its ordered input/item positions describe only those selected
packages in that invocation. This display creates no run or saved result and does
not change the canvas. Input changes and cancelled requests invalidate pending displays.

`workbench.filter.inspect` accepts the same inputs without computation parameters.
It returns `candidates: [{input, item, label, choices}]`. Each choice contains an
opaque `evaluation` selection, plus descriptive `metric`, `method`, `reference`,
`region`, `sample`, `unit`, `meaning` and optional `unavailable`. Interfaces maintain
these selections internally; users select descriptive options.

## Parameters

- `conditions`: ordered array of `{evaluation, operator, value}`. Operators are
  `lt`, `le`, `eq`, `ge`, `gt`; the threshold is finite and uses the original unit.
  Omitted conditions means no conditional selection.
- `sort`: optional `{evaluation, direction: "ascending" | "descending"}`.
  Sorting uses the existing original scalar. Ties retain package and item order.
- `limit`: optional nonnegative integer. Zero returns no items; otherwise at most
  that many items are returned, with no enlargement for ties.

Each `evaluation` may use exact inspection bindings:
`{bindings: [{candidate: {input, item}, evaluation: <choice.evaluation>}]}`.
There must be exactly one binding and one applicable value for every candidate.
The inspection value identifies the explicit evaluation input and complete
source selector; a collection evaluation also identifies its archived source.
For programmatic callers, `{metric, method, reference, region}` selects that exact
semantic context across candidates, with optional `origin` and `sample`. Multiple
matching records fail and must be resolved by exact bindings. Scalar selection
uses its original scope. Positional metrics require an explicit existing-metric
analysis first; filtering computes no mean and invokes no scientific tool.

## Persistent result: workbench.filtered_collection

The JSON entry has `items`, `sources`, `selected` and the actual `parameters`.
`items` contains the selected objects in result order, each as
`{object: <unchanged original description>, source: <sources index>}`. Joint items
retain their complete original `members`. No scientific object identity changes.

Each `sources` entry records original `format`, original `entry`, a `files` map
from every original file key to the actual file key in this collection, and its
explicit input `roles` (`candidate` and/or `evaluation`). The collection includes all
candidate and evaluation source files, complete original structure files, native
results, manifests and research files. Resolve every file reference in an
original object or manifest through that source map. Repeated filtering flattens
source maps while retaining the original file contents. `selected` records the
invocation's input/item ordering for explanation; independent use reads `items`
and the actual files.

`modules.filtering.formats.read_collection(package)` is a standalone standard-library
reader. `SourcePackage(package, source)` exposes an original source through its
file map using the public read-only Package contract. Saved and adopted collections
remain readable after source deletion and producer uninstall. A subsequent filter
explicitly accepts the collection on its candidate and evaluation ports; all archived sources with declared metric formats provide their existing
values for explicit evaluation selection. Repeated or ambiguous records require
exact source bindings. No project history is consulted.

## Explicit structure conversion

`workbench.filter.extract_structures` accepts one `collection` and no parameters.
It converts every selected complete PDB/mmCIF object into `workbench.structure_set`
on `structures`. It requires one actual conformation per selected object and
includes the unchanged coordinate bytes and a real atom-view JSON file produced
by the public structure reader, retaining protein, water, ligand and other atoms.
The object retains its original identity, label and supplied sequence/position
correspondence. `collection_source` retains the complete original object and its
format/entry/file map with all original files. Other scientific fields remain
inside that original description and are interpreted through its map.

The collection viewer offers **Extract selected structures** to add this explicit
conversion node. Sequence-only and joint-context candidates lacking a complete
coordinate file fail conversion. Downstream structure modules receive the declared
structure-set format; the carrier performs no automatic unpacking or conversion.
