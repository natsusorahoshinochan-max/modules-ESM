# Project workspace persistence

This is the P0/P6 implementation contract for the [full WebUI integration plan](2026-09-17-webui-full-integration-plan.md). Workflow Drafts remain immutable, may be incomplete, and do not become runnable until normal Workflow Commit admission.

## Project lifecycle and Inputs

Project identity survives rename, trash, restore, and server restart. `deleted_at` is the authoritative recently-deleted state. Trash changes this metadata atomically; payloads stay in their existing storage scopes until explicit permanent deletion. This avoids a partially moved Project when projects, outputs, cache, and runs use separate filesystem roots. Normal listings and authoring exclude trashed Projects; the trash list is a separate endpoint. Restore clears `deleted_at`.

Trash and permanent deletion hold the Run Runtime's Project idle lease. A reserved or nonterminal Run rejects the action with `project_has_active_runs`; it never cancels a Run. The UI can wait for closure or invoke the existing explicit cancellation endpoint and retry after closure. Permanent deletion only accepts a trashed, unprotected Project and removes its Project, output, cache, and Run scopes. All scientific references are Project-local. General copies own their Inputs; their `copied_from_project_id` is attribution only, so deleting a source does not delete or invalidate copied content. Protected examples cannot be renamed, trashed, or permanently deleted and remain available for first-edit result attribution.

Already-published immutable Inputs survive cancelling an import or merge, whether referenced or not. They remain listed for later reuse; no implicit garbage collection occurs. They are removed by Project permanent deletion. Workflow changes from import/merge are still one Draft publication, independently of Input publication.

Run Runtime owns the complete `trash_project(project_id)` and
`permanently_delete_project(project_id)` operations. The HTTP adapter calls these
operations without managing the idle lease or cache eviction. Runtime holds its
private idle lease across the whole operation, checking reserved and nonterminal
Runs from one active-Run snapshot. ProjectManager alone checks protected Project
policy, Project existence, and the trashed-only condition before storage writes;
Runtime and cache eviction do not repeat those checks.

Trash returns the updated Project metadata without deleting content. Permanent
deletion removes storage first, then evicts Run registry records and authoring
Commit caches before releasing the lease. ProjectManager's storage methods do
not constitute the complete lifecycle operation. Authoring retains its cache
eviction operation because example-record installation also uses it.

Permanent deletion is not a transaction across filesystem roots. A filesystem
failure propagates immediately, stops subsequent deletion and cache eviction,
and releases the idle lease. Already-deleted content is not rolled back; there
is no automatic retry or recovery state, and failure never returns success.

## UI snapshots and current work

UI state is an opaque JSON object interpreted only by the WebUI. The backend writes immutable UI revisions and acknowledges the exact Draft/UI pair through one workspace publication. An initial UI revision `0` denotes the empty object. An append-only workspace record binds a Draft revision, UI revision, optional source named version, and optional return workspace revision. The latest workspace record is the current work; records and their content are never overwritten. Publishing the workspace record is the point at which a Draft/UI save becomes current. Unreferenced content left by an interrupted publication does not become current.

`PUT /workspace` accepts Workflow content, UI state, or both and appends one workspace record. The Workflow and layout from the same edit become current together; omitted content retains its previous revision. `GET /workspace` returns the current Draft, exact UI state, and workspace revision. An ordinary UI-only save does not create a scientific Draft. A named version captures the current exact Draft and UI revisions without compiling. Names need not be unique; the version ID is its identity.

Workflow Authoring reads one private workspace head containing these exact
references for each operation. Public authoring operations own Project existence,
protected-write policy, submitted Workflow scope, and requested-resource checks;
internal publication trusts those admitted facts. Workspace saves compare an explicitly supplied expected Draft
revision with the current head once, before writing content. Named versions
also use the head's references without loading their content. Copy reads one source
workspace for both its Draft and UI.

Content is appended before the final workspace record. Publication returns the
exact new head; responses reuse newly written in-memory Draft/UI values and load
only missing content, without rediscovering the latest workspace or reading back
new records. UI values retain their immutable representation. Each collection's
next revision follows its highest occupied record, including content left by an
interrupted publication; returning to older work does not reuse occupied numbers.
Ordinary writes touch Project metadata once after workspace publication, reading
the latest metadata to preserve other updates. Copy staging and seed installation
retain their own metadata lifecycle. There is no automatic retry or rollback, and
a failure after workspace publication does not undo that publication.

Reading a named version has no write effect. Its response includes the current workspace revision as the return point at the time it is opened. On first edit, the client submits the edited Workflow, displayed UI state, source version ID, and that return workspace revision in one `:fork` request. The backend publishes fresh Draft/UI revisions and one workspace record retaining the return point. Both the immutable version and the pre-open work remain available. `workspace:return` appends a new current workspace record referencing the chosen saved workspace, so returning does not destroy the work being left behind. No general branching system is introduced.

### Complete edits and failure ownership

The [04 / 05 / 06 architecture design](2026-09-22-architecture-04-05-06-design.md)
retains independent immutable Draft/UI revisions while replacing the two ordinary
write paths with `save_workspace`. Both it and the distinct version `fork_version`
share private content append and workspace publication. No compatibility aliases,
dual writes, cross-store rollback, or recovery framework are part of this contract.

`WorkspaceEditor` owns desired edits, acknowledged workspace, the ordered save
queue, tutorial copy, version origin/return, history, failure, and explicit retry.
A failed save retains the desired edit and pauses the queue. Dependent navigation,
version naming and Commit/Run actions wait for a successful flush. A failure before
publication leaves the previous head current; a metadata or response failure after
publication does not undo the published head. Retry belongs to the same owner and
may read the current receipt once to resolve that ambiguity; it never silently
merges a changed scientific baseline or automatically retries.

The ReactFlow adapter retains raw input, measurements, drag and selection state.
It finishes or blocks active input before dependent operations; invalid raw text
is preserved and never turned into a guessed scientific value. Long Prompt,
Selection and Input sessions capture a scientific baseline and submit a complete
prospective Workflow. Any layout operation acts on the latest desired UI through
`updateUi(currentUi)`, rather than overwriting it with the UI from session opening.
Session retirement, including A→B→A, prevents late work from installing into a new
session. Actual later science edits conflict; ordinary later layout changes do not.

Named-version first edits still create fresh Draft/UI content and retain the
source version and pre-open return point, even if the first edit changes only
layout. Returning appends a workspace record and preserves the work being left.
Read-only tutorial inspection does not copy it. Copy for a real edit or Input
publication remaps Workflow/Project scope and uses the copied Draft's baseline;
copy itself is not a second scientific edit.

## Copy behavior

The existing protected-example first-edit operation remains distinct (`:copy`): it records the protected source for reference-result presentation. General `:duplicate` works for any active Project, carries the current Workflow including parameters and Prompt documents, exact current UI state, and only Inputs referenced by the Catalog-declared Project Input parameters. Input references are relative to the new Project and keep their immutable content and filenames; the Workflow ID becomes the new Project ID. It does not copy Run evidence, output objects, cache, named versions, or source history. Copy publication is staged before the new Project appears in the active list.

## Public operations

Draft reads and Commit operations remain current. Ordinary writes use `save_project_workspace` (`PUT /projects/{project_id}/workspace`) with optional `workflow`, `ui_state`, and `expected_draft_revision`; at least Workflow or UI must be supplied. Separate Draft/UI writes and Prompt apply are removed. Project lifecycle, Input list, current workspace read, named-version list/create/read/fork, and workspace return retain their explicit operations. Public schemas are declared in the protocol bundle; validation remains at the existing protocol/Workflow boundary rather than repeated in storage helpers.

## Original Commit science and result currency

Every newly published Workflow Commit stores canonical compiled scientific identity together with its existing minimal scientific definition snapshots. Identity records admitted parameter values including defaults, compiler-owned result identity facts (exact Node Types, Bindings, Methods, selectors/objectives and their scientific definitions), and each Node's ordered input Port sources. Node presentation order and opaque UI state are excluded; input order is retained because many-valued Ports can be scientifically ordered. Project identity is the enclosing scope. This is captured at original publication, never reconstructed later from a changed Catalog.

`GET /workflow/commits/{workflow_commit_id}` reads those saved Workflow and scientific snapshots without current-Catalog admission. Results and exports use these snapshots to interpret their original Metrics and Methods. `POST /workflow/commits/{workflow_commit_id}:compare` accepts the current Workflow Draft document without saving it. A compile failure returns `unknown` plus the current issues; successful admission compares canonical scientific identity to the persisted original and returns `current` or `stale`. Reverting scientific edits clears staleness; layout changes cannot cause it. Comparison does not admit an old Commit for execution or rewrite any evidence. Execution continues to use normal Commit admission.

Comparison resolves Catalog-declared Project Input parameters to immutable input content digest and size using the same facts as Result Identity. Different upload identities with identical content do not make science stale; filenames and upload references remain provenance. This resolution is a read for comparison, not an added Commit admission requirement. An unavailable referenced Input makes the comparison `unknown`. Permanent deletion evicts both Runtime registry records and retained Commit caches after removing storage, so evidence cannot still appear available until process restart.

The comparison request explicitly names `workflow_project_id`, which may differ from the path's original Commit Project. This supports personal work that displays reference results from a protected example. Current Draft Inputs resolve in `workflow_project_id`; the original immutable Commit's references resolve in its original Project. The Workflow identity must equal `workflow_project_id`; the comparison never guesses or rebases input locations.

Compiler-declared parameter indirections (Observation Selector and Selection Objective locator IDs) are excluded from the normalized Node parameters. Their resolved scientific facts remain in Result Identity plan facts, so renaming a locator while preserving its content does not make results stale.

The current WebUI's opaque payload uses `canvas` for node positions, collapsed cards and viewport, and `binding_parameter_memory` for inactive model settings. Opening or inspecting a named version does not save either payload. The first graph, parameter, Prompt, or layout modification publishes a new current workspace retaining the pre-open return point. Prompt preview includes its exact version context. Confirmation submits the normalized document inside the complete Workflow through WorkspaceEditor; version fork and content saving are one publication. Project navigation waits for the shared save lifecycle; explicit retry preserves and resubmits pending edits after a persistence failure.

Parameter resource choices read the current Project Input list. Chain and residue choices belong to each parameter Node's exact incoming source edge: direct PDB chain selection uses backend Input inspection; current authorable Prompt/residue-axis sources use a read-only prospective Prompt owner projection. Temporary preview Nodes are never saved. Other resolved axes use only the matching source Node/Port's published value after the backend confirms scientific consistency with the current Workflow. The UI neither parses PDB residue identities nor combines unrelated layouts. Missing evidence is visible and existing unavailable parameter values remain editable/removable. First-edit example copies transfer inactive Binding parameter memory to the new Project scope before UI persistence.

## Verification

Focused remote tests cover restart persistence, incomplete Draft versions, first-edit/return round trips, independent copy Inputs/UI and excluded history, exact trash restoration, all configured storage roots on purge, protected examples, and active Run rejection. Tests and the repository backend gates run on the remote server only, per the user instruction.

## Canvas connection editing

Canvas connection operations identify an edge by its source Node/Port and target
Node/Port, not its array position. Creation and reconnection replace an occupied
one-valued input consistently. Ordered many-valued inputs retain the original
slot when an existing edge is reconnected within that input; a connection moved
to another input is appended there. An unchanged or already-existing connection
is a no-op, with no publication or undo entry. Invalid or abandoned reconnection
retains the old edge. Explicit deletion is separate. Reconnection anchors are
interactive only on selected edges, so overlapping endpoints of other incoming
edges cannot intercept the intended reconnection.

The ReactFlow adapter finishes raw inputs and pending writes before submitting a
connection or deletion intent against the current WorkspaceEditor contents.
Pre-admission refusal leaves the canvas unchanged. Once accepted, the desired
Workspace remains visible on write failure and uses the existing explicit retry.
Batch node/edge deletion is atomic and keeps existing Selection-reference cleanup.

Collapsed nodes retain separate visible connection anchors, but connections to
those nodes cannot be created or reconnected until expanded. Port rows colocate
labels and anchors and expose exact type, meaning, requiredness, multiplicity,
and ordered input sources. Matching feedback describes Port compatibility only;
the backend remains responsible for scientific Workflow admission.
