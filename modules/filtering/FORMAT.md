# Filtering and sorting

Install `modules.filtering:module` from the `protein-workbench` distribution.
The module explicitly depends on the public
[`modules.metric_analysis.read_metric_choices`](../metric_analysis/FORMAT.md#public-existing-metric-reader)
and the [collection module](../collection/FORMAT.md)
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
[metric reader](../metric_analysis/FORMAT.md), and `workbench.collection`.
Evaluation inputs accept those metric formats, saved `workbench.metric_analysis`
statistics and filtered collections. Analysis results supply evaluations; bind
the original object packages separately as candidates.
An empty candidate list or an empty candidate package yields an empty collection.
A comparison package supplies its actual subject. A sequence/backbone package
supplies each complete explicitly evaluated joint sequence context as one item;
its score cannot be assigned to a single member sequence. A native ESM3 generation
is likewise one complete object, including all chains and its original native file.
Native ProteinMPNN candidates retain their complete backbone PDB/mmCIF file.
The shared candidate reader checks these concrete required file declarations and
readability through each actual source map before predicates or quantity limits,
including zero. Missing resources stop filtering; generic package saving remains
format-agnostic.

In the canvas, bind delivered packages explicitly using the port's multiple
selection control. **Inspect selected inputs** lists each candidate and its actual
metric, method, reference, original region, sample, unit and meaning. Unavailable
values remain listed with their reason. Each condition and sort can use exact
records for individual candidates, or **Match evaluation meaning for current
objects**. The latter accepts an explicit JSON rule before upstream results exist;
use **Apply rule** to store its metric, method, reference selection and region for every
incoming object, including new objects in later rounds. **Exact reference in rule**
keeps a fixed reference. **Reference from connected evaluations** explicitly uses
the reference in the currently connected evaluation packages, allowing it to
change between rounds. Changing this choice updates the rule draft; **Apply rule**
accepts it. Parameter changes update only the current node; **Copy
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
these selections internally; users select descriptive options. Inspection also supplies
`context` (evaluation input, optional collection source, source format/entry and
optional analysis source ordinal), `reference_display` (provided name/label and
structure file/format), and `reference_access` (`input` and exact package `key`, or
an `unavailable` reason). Access resolves original keys through the recorded
collection and saved-analysis source maps; matching filenames are never used to
infer an association. Repeated saved analyses follow each selected analysis record
and its explicit source map within the current self-contained package. A cyclic
source declaration reports unavailable access with its reason.

Both node and temporary controls show that explicit input/source context, actual
reference file, region, method details and parameters. For saved statistics,
analysis method/region and original source method/region are shown separately.
**View reference file** reads the selected reference's declared PDB/mmCIF bytes
through the existing package file access, including while the node is read-only.
Anonymous references can share filenames; their explicit input/source context and
actual content allow selection without exposing object or package identities.
Viewing changes no filtering parameter, flow or result. A changed choice/input or
unmount discards pending file responses; unavailable access reports its reason.

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
The meaning mode uses `{metric, method, reference, region}` to select that exact
semantic context across candidates, with optional `origin` and `sample`.
Alternatively, replace `reference` with `reference_mode: "provided_evaluations"`.
These fields are mutually exclusive. This explicit mode searches only the
evaluation packages supplied to the current invocation, matching each candidate's
identity, metric, actual method, original region and any optional selectors.
It accepts a changed reference when exactly one evaluation matches. Several
matching evaluations, including evaluations against different references, fail;
select the intended evaluation inputs or use exact bindings. Missing matches also
fail. No history, latest record or highest score is used to choose a reference.
Scalar selection
uses its original scope. Positional metrics require an explicit existing-metric
analysis first; filtering computes no mean and invokes no scientific tool.

## Persistent result

The canvas node delivers [`workbench.collection`](../collection/FORMAT.md), with
selected objects in result order, their complete source files, explicit evaluation
sources and the actual filtering parameters. The collection module owns splitting,
merging, object selection and conversion to complete structure or sequence packages.
A subsequent filter accepts the collection on candidate and evaluation ports;
archived sources with declared metric formats provide the existing values. Repeated
or ambiguous evaluation records require exact bindings. No project history is read.
