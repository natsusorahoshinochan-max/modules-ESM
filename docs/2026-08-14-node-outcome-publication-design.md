# Node Outcome Publication design

- Status: accepted implementation specification
- Decision: [ADR-0039](adr/0039-node-outcomes-publish-atomically-through-immutable-value-objects.md)
- Scope: `core`, current Run persistence, Result Cache, and
  `protein_workbench_public`

## 1. Purpose

This specification replaces the current sequence of independent Artifact,
output, Operation, Node, disposition, and Run writes with explicit durable
boundaries. It must allow lawful large scientific outputs without weakening
Port contracts, and it must make every crash-recoverable state mean exactly
what its committed evidence says.

The change is storage and lifecycle work. It must not change Candidate,
Prediction Key, Prediction Confidence Fact, PAE, lineage, Method, Metric,
Observation Context, Port digest, multiplicity, masking, units, residue axes,
or randomness semantics.

### 1.1 Confirmed trigger and historical boundary

The provider-free `WFRET-5G53-001` reproduction used the registered ESM-3 Port
codecs and lawful domain values for 291 residues and two samples:

| Output set | Canonical `outputs_published` bytes | Current behavior |
| --- | ---: | --- |
| required outputs, no reconstruction | 3,365,804 | persists |
| reconstruction, no PAE | 3,582,657 | persists |
| reconstruction and PAE in both confidence collections | 6,721,503 | `evidence_unavailable` at the 4 MiB fact bound |

This proves that a lawful scientific output can trigger the publication gap.
The original 5G53 Provider exception was not durably recorded, so the final row
is the strongest supported explanation of that historical Run, not proof that
its exact Provider response contained both PAE collections. Implementation and
acceptance wording must retain that distinction.

## 2. Non-goals

This work does not:

- change an ESM-3 Node Type, Binding, Adapter, or Provider request;
- delete PAE, reconstruction, confidence outputs, or legal samples;
- make ordinary Typed Outputs artifact-capable;
- make Result Cache a source of evidence;
- add legacy readers, migration, aliases, or an embedded-value fallback;
- add authentication, multi-tenancy, hostile-input hardening, distributed
  locking, or multi-process execution support.

### 2.1 Trust model

This is a trusted, single-user, loopback-only system. Each contract owner
validates once; downstream components trust admitted values and resolved
contracts. Adapters translate documented Provider responses directly and do
not guess schemas, repair responses, cross-check Providers, or add fallback
behavior for hypothetical malformed responses.

Only scientific contracts, public protocol admission, durable writes, content
integrity, causal evidence, accidental data loss, and credential hygiene retain
checks. A current-generation local invariant violation fails fast. The design
does not add repeated validation, broad catches, catch-and-continue behavior,
silent coercion, guessed defaults, or undocumented retries.

## 3. Required invariants

1. Canonical Port value bytes and the existing per-value and aggregate Port
   digests remain authoritative. Storage never decodes and re-encodes a value
   to derive identity.
2. Object bytes are durable before a Ledger transaction can reference them.
3. Object presence alone grants no visibility. Only a committed current-schema
   Ledger fact can publish a Typed Output or Artifact for a Run.
4. A successful Node publication becomes visible as one group. A failed
   transaction publishes none of its logical facts.
5. Operation outcome describes implementation work through output admission
   and artifact contract processing. Node outcome additionally describes
   publication.
6. Projection and Cache failures after Ledger commit cannot change Operation,
   Node, disposition, Selection, or Run outcomes.
7. Result Identity conflict detection is derived from committed Run evidence,
   not from whether an optional Cache entry happens to exist.
8. Ledger metadata size is independent of canonical scientific value size and
   sample count.
9. Restart applies the same causal rules as normal completion. Restart itself
   is not a scientific outcome.
10. A public descriptor can retrieve every exact admitted canonical value, in
    original multiplicity order, and verify both its per-value digest and the
    Port aggregate digest.

## 4. Outcome model

### 4.1 Operation boundary

An executed Operation Attempt includes:

```text
implementation call
-> Engine Invocation closure
-> provider decoding and normalization
-> Candidate identity normalization
-> output Port admission
-> artifact intent and media-contract processing
```

Failure anywhere in that sequence closes the Operation Attempt and Node
Execution Attempt with the same non-success status. A successful Engine
Invocation remains successful when a later step fails.

The Operation Attempt becomes `succeeded` only after all output Ports have an
immutable `AdmittedPortValues` snapshot. Content-addressed object writes,
Result Identity conflict comparison, Ledger commit, projection refresh, and
Cache indexing are outside the Operation Attempt.

### 4.2 Node failure origins

`node_attempt_terminal` gains a closed `failure_origin` field, required exactly
when `status` is `failed`:

| `failure_origin` | Required causal state | Public outputs |
| --- | --- | --- |
| `operation` | Executed child Operation is `failed` | none |
| `publication` | Executed child Operation is `succeeded`; an object or publication preparation failed | none |
| `result_identity` | Executed child Operation is `succeeded`, or a replay was inspected; committed identity evidence conflicts | none |

Cancellation, interruption, and unknown remote outcome keep their existing
terminal statuses and do not use `failure_origin`. A Ledger write failure
cannot truthfully persist any terminal status; it is exposed as
`evidence_unavailable` until restart can resume from the durable prefix.

### 4.3 Failure classification

| Failure point | Operation terminal | Node terminal | Durable outputs |
| --- | --- | --- | --- |
| engine, decode, normalize, admission, artifact contract | non-success | same non-success | none |
| typed-value object write | `succeeded` | `failed/publication` | none |
| artifact object write | `succeeded` | `failed/publication` | none |
| Result Identity mismatch | `succeeded` when executed | `failed/result_identity` | none |
| Node Ledger transaction | no newly acknowledged terminal | no newly acknowledged terminal | hidden in-process until the durable prefix is resolved |
| projection refresh after commit | `succeeded` | `succeeded` | all, from Ledger |
| Cache index publication after commit | `succeeded` | `succeeded` | all, from Ledger |
| Run Closure transaction | Node facts unchanged | Node facts unchanged | already committed Node outputs remain visible |

## 5. Deep module boundary

`run_execution_v2` remains the scheduler and scientific-operation
orchestrator. It must no longer coordinate object, Artifact, Cache, terminal,
and disposition writes itself. Its only Node completion interface is:

```python
class NodeAttemptFinalizer:
    def finalize(
        self,
        intent: NodeFinalizationIntent,
    ) -> FinalizedNode: ...
```

`NodeFinalizationIntent` is a closed union:

- executed success with the exact Operation Attempt identity, Result Identity,
  admitted output snapshots, output declarations, and producer provenance;
- executed non-success with the Operation terminal and redacted public error;
- Cache replay success with admitted output snapshots and original producer
  provenance;
- cancellation or interruption conclusion with the exact causal identities.

`FinalizedNode` reports only the committed disposition and, for success, the
admitted runtime values needed by downstream Nodes. It does not expose staging
paths, transaction assembly, rollback callbacks, or Cache write order.

The deep module internally composes two focused persistence interfaces:

```python
class ProjectObjectStore:
    def put_exact(self, canonical_bytes: bytes) -> ObjectReference: ...
    def read_verified(self, reference: ObjectReference) -> bytes: ...

class RunEvidenceLedger:
    def commit(
        self,
        logical_facts: tuple[ProposedFact, ...],
    ) -> CommittedFactRange: ...
```

The object store owns only immutable bytes, digests, sizes, durable publication,
and garbage collection. It has no knowledge of Port Types, Candidates,
Artifacts, Results, or Runs. The finalizer owns those domain meanings. The
Ledger owns schemas, causal reduction, sequence allocation, durability,
projection notification, and public event ordering.

Tests replace the object and Ledger persistence interfaces with explicit
fault-injecting implementations. Production and fault-injection are the two
justified adapters; neither interface is added to scientific operations or
Module Packages.

## 6. Immutable Project object store

### 6.1 Physical ownership

`PROTEIN_WORKBENCH_OUTPUT_ROOT` remains the configurable physical owner of Run
output bytes. For each Project, it contains one shared object namespace rather
than random Run-scoped artifact files:

```text
<project-output-base>/objects/v1/sha256/<first-two-hex>/<remaining-hex>
<project-output-base>/staging/<writer-id>/...
```

When no output root is configured, `<project>/outputs` is the
`project-output-base`. The object path is derived only from canonical SHA-256;
Project identity remains physical scope and is not hashed into content
identity.

`put_exact` computes digest and byte size, creates a private staging file,
writes and fsyncs all bytes, atomically renames without replacement, and fsyncs
the destination directory. An existing object is accepted only after its size
and digest are verified. It returns:

```json
{
  "content_digest": "sha256:<64 lowercase hex>",
  "size": 123
}
```

There is no cross-filesystem rename between the object root and Run root.
Object durability intentionally precedes the independently atomic Ledger
transaction.

### 6.2 Port value manifests

Every admitted output Port, including an artifact-capable Port, receives one
canonical immutable manifest:

```json
{
  "schema_namespace": "protein-workbench-port-value-manifest/v1",
  "port_type": {"id": "...", "version": "..."},
  "multiplicity": {"minimum": 1, "maximum": 100},
  "content_digest": "sha256:<aggregate Port digest>",
  "value_count": 2,
  "values": [
    {
      "index": 0,
      "content_digest": "sha256:<canonical value digest>",
      "size": 1580000,
      "object": {
        "content_digest": "sha256:<canonical value digest>",
        "size": 1580000
      }
    }
  ]
}
```

Manifest order is the admitted multiplicity order. The finalizer verifies that
the manifest's Port Type, count, per-value bytes, and aggregate digest equal the
existing `AdmittedPortValues`; it does not recompute scientific identity by a
different codec. The manifest itself is stored as a content-addressed object.

One internal canonical `NodeResultManifest` contains the Result Identity, exact
compiler-owned result contract metadata, and the output-port-to-manifest
mapping for every declared output actually produced, including
artifact-capable outputs. It is itself stored as an immutable object and is the
complete comparison surface for Result Identity. Public Typed Output
descriptors are created only for ordinary outputs; public Artifact descriptors
are created only according to declared artifact intent and media contract.

```json
{
  "schema_namespace": "protein-workbench-node-result-manifest/v1",
  "result_identity": "sha256:<result digest>",
  "result_contract_metadata": {},
  "outputs": [
    {
      "output_port": "confidence_facts",
      "port_type": {"id": "...", "version": "..."},
      "value_manifest": {
        "content_digest": "sha256:<manifest digest>",
        "size": 1234
      }
    }
  ]
}
```

Output entries use Execution Plan declaration order. Optional outputs that were
not produced are absent; required-output closure was already proven by output
admission.

### 6.3 Artifact materialization

Artifact bytes use the same `ProjectObjectStore.put_exact` operation, but they
retain an Artifact descriptor, artifact-capable Port declaration, exact media
type, filename provenance, Candidate association when declared, and Run-scoped
artifact reference. Sharing a physical byte store does not make a Typed Output
an Artifact or an Artifact a Typed Output.

Artifact retrieval resolves the Run-scoped reference through a committed
`artifact_published` fact and then streams the verified object. A file without
that committed fact is unreachable through the public protocol.

## 7. Result Identity authority and Cache order

The finalizer builds the exact `NodeResultManifest` before committing success.
Under one Project-scoped publication lock it compares that manifest and the
compiler-owned contract metadata with a Result Identity index rebuilt from
committed current-schema Ledger publications:

- no existing committed claim: success may commit;
- exact same contract metadata and output manifests: success may commit;
- any different contract or output manifest: commit a failed Node conclusion
  with `failure_origin=result_identity` and `result_identity_conflict`.

The lock covers comparison, Run Ledger commit, and in-memory index update, so
concurrent Runs in the supported single backend process cannot publish
conflicting claims. The index is a rebuildable projection, not a new evidence
file. On startup it is reconstructed only from causally valid committed Run
transactions.

The Result Identity hashing namespace stays
`protein-workbench-cache/v3`. Storage representation is not a
result-affecting scientific fact.

After a successful Node Ledger commit and after releasing the Project
publication lock, the Result Cache may publish a `v4` replay index containing:

- Result Identity and exact contract metadata;
- producer Run and Node identities;
- the `NodeResultManifest` reference and output Port manifest references;
- no embedded canonical values and no base64 copies.

Cache publication has no rollback callback. Failure to create or refresh the
index loses only an optimization. Cache lookup verifies references and object
digests, reconstructs `AdmittedPortValues` through the registered Port codec,
and records current-Run materialization plus original producer provenance.
An absent Cache entry is a miss. A current-generation Cache entry that violates
its exact storage contract fails fast rather than being silently converted to a
miss. A conflict with committed Result Identity evidence is
`result_identity_conflict`, not `cache_identity_conflict`.

## 8. Ledger transaction schema

Run Evidence Ledger schema `4.0.0` stores one immutable canonical transaction
file per commit. The closed envelope is:

```json
{
  "schema_namespace": "protein-workbench-run-ledger-transaction/v4",
  "schema_version": "4.0.0",
  "project_id": "...",
  "run_id": "...",
  "transaction_sequence": 12,
  "first_fact_sequence": 38,
  "last_fact_sequence": 42,
  "committed_at": "...",
  "facts": [
    {
      "sequence": 38,
      "recorded_at": "...",
      "fact_type": "operation_attempt_terminal",
      "payload": {}
    }
  ]
}
```

Transaction files are named by zero-padded `transaction_sequence`. Logical fact
sequences are contiguous across transactions and remain the cursor and
WebSocket event ordering. A one-fact append is represented by a one-fact
transaction; there is no second persistence path.

`RunEvidenceLedger.commit` performs this order while holding its ordering lock:

1. validate every proposed payload against its closed fact schema;
2. allocate transaction and contiguous logical sequences;
3. apply the complete proposed transaction to a temporary causal reducer;
4. canonicalize and enforce bounds on transaction metadata;
5. write, fsync, atomically publish without replacement, and fsync the Ledger
   directory;
6. swap the validated reducer state and append logical facts in memory;
7. notify projection and event consumers.

Failure before the final-name rename means no logical fact in the transaction
exists. An exception after the rename begins, including directory-fsync
failure, is an unacknowledged commit outcome: the process must not expose the
transaction, append a contradictory failure, or delete the final-name file. It
marks the Run `evidence_unavailable`; restart resolves the outcome solely by
whether one complete canonical transaction occupies the next contiguous
position.

If the durable file succeeds but the in-memory reducer swap fails, the Ledger
reloads and validates its own durable prefix before returning. It may then
acknowledge the committed range; if reload fails, it uses the same
`evidence_unavailable` behavior and never attempts compensation. Projection
refresh happens only after an acknowledged durable commit and may be retried or
rebuilt without changing the committed state. The transaction size bound
constrains fact and descriptor metadata only; canonical value and Artifact
bytes are never placed inside it.

Unknown, truncated, non-canonical, discontinuous, duplicate, or causally
invalid transaction files fail the current Ledger read. A trailing private
staging file is not a transaction and can be removed. Prior Ledger schemas are
unsupported development state and are neither replayed nor prefix-repaired as
v4.

## 9. Node finalization transactions

### 9.1 Executed success

One transaction contains, in order:

1. `operation_attempt_terminal(status=succeeded)`;
2. one `typed_outputs_published` fact containing the Result Identity,
   `NodeResultManifest` reference, and bounded descriptors for all ordinary
   output Ports, including an empty descriptor list when the Node has only
   artifact outputs;
3. one `artifact_published` fact per published Artifact;
4. `node_attempt_terminal(status=succeeded, resolution=executed)`;
5. `node_disposition(outcome=succeeded, resolution=executed)`.

All referenced value manifests and Artifact objects are already durable. The
causal reducer requires these publication facts, terminal, and disposition to
belong to the same transaction.

### 9.2 Cache replay success

The same publication, Node terminal, and disposition facts commit together
with `resolution=cache_replayed`. There is no Operation Attempt terminal or
Engine Invocation. Artifact-capable cached Port values are materialized into
current-Run Artifact descriptors before the transaction.

### 9.3 Operation non-success

One transaction contains the Operation terminal when the Operation started,
the matching Node terminal, and the disposition. It contains no Typed Output
or Artifact publication fact. A Node failed with `failure_origin=operation`
must have one child Operation terminal with the same failed status. Existing
cancelled, interrupted, and `outcome_unknown` causal rules remain explicit.

### 9.4 Publication or Result Identity failure

When output admission succeeded but object preparation or Result Identity
comparison fails, one transaction contains:

1. `operation_attempt_terminal(status=succeeded)` when execution occurred;
2. `node_attempt_terminal(status=failed, resolution=executed,
   failure_origin=publication|result_identity, error=...)`;
3. `node_disposition(outcome=failed)`.

It contains no publication fact. Successfully written but unreferenced objects
remain invisible and become garbage-collection candidates.

### 9.5 Cancellation ordering

Cancellation request and Node finalization use the same Run Ledger ordering
lock. If `cancellation_requested` commits first, finalization publishes no
outputs and closes the active attempt as cancelled unless required cleanup
itself fails. If the success transaction commits first, cancellation observes
the durable disposition and cannot rewrite it. Cleanup never deletes a shared
content-addressed object merely because one Run was cancelled.

## 10. Public protocol

The current bundle remains `protein-workbench-public/v2` and advances to
`schema_version=2.2.0`. All backend, frontend, fixtures, examples, generated
protocol artifacts, and tests change together.

### 10.1 Typed Output descriptor

`TypedOutput.values` is deleted. `RunProjection.outputs` contains the following
closed descriptor:

```json
{
  "node_id": "generate",
  "output_port": "confidence_facts",
  "port_type": {"id": "...", "version": "..."},
  "content_digest": "sha256:<aggregate Port digest>",
  "value_count": 1,
  "value_manifest_reference": "sha256:<manifest digest>",
  "result_identity": "sha256:<result digest>",
  "materialization": {
    "run_id": "...",
    "resolution": "executed"
  },
  "producer_provenance": {
    "producer_run_id": "...",
    "producer_result_identity": "sha256:<result digest>",
    "output_port": "confidence_facts"
  }
}
```

The descriptor is bounded independently of `value_count` and value byte size.
`content_digest`, Result Identity, materialization, and provenance keep their
current scientific meanings.

### 10.2 Canonical value retrieval

Add one operation:

```text
GET /api/v2/projects/{project_id}/runs/{run_id}/outputs/
    {node_id}/{output_port}/values/{value_index}
```

The route resolves only a Typed Output descriptor made visible by a committed
successful Node disposition. `value_index` is zero-based and must be less than
`value_count`. The response streams the exact full canonical bytes admitted by
the Port codec and supplies:

- `Content-Type: application/json`;
- exact `Content-Length`;
- `Digest` for the individual canonical value;
- a strong `ETag` derived from that digest;
- response metadata containing Port Type, aggregate Port digest,
  value-manifest reference, value index, and value count.

The server verifies object size and digest on read. It never re-encodes the
value for transport. A missing Node/Port/index is `typed_output_not_found`; a
referenced object whose bytes fail verification is
`typed_value_integrity_mismatch`. Cross-Project or cross-Run references remain
unresolvable through this route.

There is no endpoint that returns all values embedded in a Run Projection and
no query flag that restores `values`.

### 10.3 Artifacts and events

`artifact_index` and the existing Artifact retrieval route remain distinct.
Their backing bytes change to object references, but public Artifact semantics
do not.

WebSocket events remain lifecycle facts. Logical facts inside a committed
transaction are emitted in sequence order after the whole transaction is
durable. Typed value and Artifact bytes are never WebSocket messages.

### 10.4 Structured errors

The public vocabulary:

| Code | HTTP | Retryable | Closed safe details |
| --- | ---: | --- | --- |
| `node_publication_failed` | 500 | false | Node ID and `typed_value_object`, `artifact_object`, or `manifest` stage |
| `result_identity_conflict` | 409 | false | Result Identity |
| `typed_output_not_found` | 404 | false | Run, Node, output Port, and optional value index |
| `typed_value_integrity_mismatch` | 409 | false | Run, Node, output Port, value index, expected digest, and expected size |
| `evidence_unavailable` | 503 | true | last acknowledged durable cursor |

`cache_identity_conflict` is removed. A durably recorded Node with
`failure_origin=publication` uses `node_publication_failed`; a Node with
`failure_origin=result_identity` uses `result_identity_conflict`.

Every new error has a closed bounded details schema. Public errors never
contain canonical values, object paths, temporary paths, or raw exceptions.

## 11. Projection and same-process failure behavior

Run Projection is rebuilt only from committed transactions. It joins
`typed_outputs_published` and `artifact_published` facts with successful Node
dispositions; object-store enumeration never contributes.

Projection refresh failure after commit records an in-memory operational error
without retrying automatically. A subsequent explicit public read or startup
rebuild derives the view from validated Ledger state. Projection failure does
not append a compensating fact, hide committed outputs, or change their
outcome.

When a background worker finishes but cannot persist a required Ledger
transaction, the active Run record keeps a sticky `evidence_unavailable`
condition in addition to its finished signal. Until process restart or an
explicit recovery successfully advances the durable prefix:

- Run Projection and Cancel Run return `evidence_unavailable` rather than
  `running`;
- the WebSocket sends no invented terminal event and closes as an unavailable
  evidence stream;
- a second cancellation request cannot report that an already-finished worker
  is still running;
- no Cache entry is published for the unacknowledged result.

There is no undocumented retry loop against a failing evidence medium.

## 12. Run Closure and restart

### 12.1 Normal Run Closure

After all Node dispositions are durable, the runtime derives the expected
Selection conclusion set fixed in `run_scope_bound`. If every Node succeeded,
all required `selection_terminal` facts and `run_terminal` commit in one Run
Closure transaction. A Selection derivation failure commits one failed
Selection terminal with a failed Run terminal in that same transaction.

If Node outcomes already determine non-success, no successful Selection result
is invented. The terminal precedence remains:

```text
failed or Selection failed -> failed
else interrupted           -> interrupted
else cancelled             -> cancelled
else all succeeded and required Selection is complete -> succeeded
```

Blocked dispositions retain their exact `blocked_by` causes; the underlying
failed, interrupted, or cancelled disposition determines the terminal class.

### 12.2 Restart reconciliation

Restart loads and validates complete transaction files, ignores private
staging files, and starts from the last committed logical fact. It then:

1. records `restart_reconciliation_started` only as audit evidence;
2. closes each genuinely open Engine Invocation as `outcome_unknown`;
3. closes each genuinely open Operation and Node causal chain in an idempotent
   recovery transaction;
4. derives dispositions for Nodes that never started from their durable
   dependency outcomes;
5. if all Node dispositions were already successful, reads committed value
   manifests to reconstruct any missing required Selection conclusions;
6. applies the normal Run Closure rule.

A complete successful Node publication can never be missing only its Node
terminal or disposition because those facts share one transaction. A Run with
all successful dispositions and complete or reconstructable Selection becomes
`succeeded` even if its original Run Closure write failed. A Run with no
required Selection also becomes `succeeded` once all dispositions are
successful. Restart never forces `interrupted` merely because restart occurred.

If a committed descriptor references a missing or corrupt object, evidence is
unavailable; reconciliation does not downgrade or rewrite the successful Node
fact to disguise corruption.

Each recovery transaction is safe to replay after another crash because its
preconditions are derived from the new durable prefix. Run Closure remains a
separate final transaction.

## 13. Object ownership and garbage collection

Live object roots are:

- Port value manifests and value objects referenced by committed Run Ledger
  publication facts;
- Artifact objects referenced by committed Run Ledger Artifact facts;
- objects referenced by valid current-schema Cache replay indexes;
- files in an active writer staging directory.

The Project-scoped Result Identity index is derived from Ledger facts and is
not an additional root file. Projection files are also not roots.

At startup, after current-schema Ledgers and Cache indexes have been validated,
the object store performs mark-and-sweep per Project under the Project
publication lock. It removes stale private staging files and unreferenced
content-addressed objects. Sweep is best-effort operational cleanup: failure is
reported but never changes scientific outcomes or deletes a referenced object.

An object cannot be swept while an active finalizer may reference it. Tests use
an explicit active-writer root rather than a time-only race heuristic. Because
objects are immutable and shared, cancellation and Run failure remove only
staging ownership; they do not eagerly unlink a digest path.

## 14. Current-generation cutover

Implementation changes all current producers and consumers together:

- extract Ledger transaction/reducer ownership from
  `core/run_execution_v2.py`;
- introduce the Project object store and Node finalizer;
- replace Run-scoped Artifact file publication with object references;
- replace Cache `encoded_values` with manifest references and remove rollback;
- update public schemas, server routes, generated models, frontend data access,
  examples, Contract Test Kit, acceptance fixtures, and documentation;
- delete sequential `commit_node_publication`, embedded `TypedOutput.values`,
  `cache_identity_conflict`, and superseded cleanup paths.

The cutover supports only Run Ledger `4.0.0`, Cache entry `v4`, object manifest
`v1`, and public bundle `2.2.0`. Old development Projects, Runs, projections,
and Cache entries may be cleared. No migration or dual reader is implemented.

## 15. Verification contract

### 15.1 Exact large-output regressions

- Publish the lawful 291-residue, two-sample ESM-3 output with reconstruction
  and PAE in both confidence collections through the real registered Port
  codecs, without a Provider call.
- Assert exact digest, value count, Candidate lineage, Prediction Keys,
  confidence facts, PAE shapes, and byte-for-byte retrieval for every output.
- Exercise declared `num_samples=100` with lawful canonical fixtures and prove
  Ledger transaction byte size changes only with descriptor count, not with
  scientific value byte size.

### 15.2 Failure injection

Inject failure before and after each of:

1. typed-value object staging write, fsync, and rename;
2. Artifact object staging write, fsync, and rename;
3. Result Identity comparison;
4. Ledger transaction staging write, fsync, rename, and directory fsync;
5. in-memory reducer swap;
6. projection refresh;
7. Cache replay-index publication;
8. Run Closure transaction.

For every point, assert Operation terminal semantics, Node terminal and
`failure_origin`, public visibility, Result Identity index state, Cache state,
object reachability, same-process API behavior, and restart result. No failed
transaction may expose a strict subset of its logical facts.

### 15.3 Lifecycle and recovery

- A 202 response followed by worker failure must either close durably or expose
  `evidence_unavailable`; it must not remain publicly `running`.
- Cancel Run must distinguish an active worker from a finished worker whose
  evidence did not close.
- Restart must recover all-success dispositions to `succeeded` when Selection
  is complete, reconstructable, or not required.
- Restart must preserve true `failed`, `cancelled`, `interrupted`, and
  `outcome_unknown` causal chains.
- A transaction is visible all-at-once to Projection, Artifact retrieval,
  typed-value retrieval, event replay, and live WebSocket consumers.
- Missing or corrupt referenced objects fail visibly and are never converted
  into empty values or `interrupted` outcomes.

### 15.4 Public and Cache contracts

- Projection size remains bounded when canonical outputs exceed 4 MiB and when
  sample count reaches 100.
- Every descriptor/index route validates Project, Run, Node, Port, and value
  index scope.
- Retrieved bytes exactly match registered Port-codec canonical bytes and
  headers match size and digest.
- Cache replay reads the same immutable objects, preserves Result Identity,
  Candidate identity, lineage, Method, materialization, and producer
  provenance, and creates no Operation Attempt or Engine Invocation.
- Cache storage failure after Node commit does not change the Run.
- Conflicting committed outputs under one Result Identity fail even when the
  Cache directory is absent.

### 15.5 Repository gates

Run focused transaction, object-store, public-route, Cache, Artifact,
cancellation, restart, ESM-3, and Contract Test Kit tests, then:

```bash
.venv/bin/python scripts/verify_backend.py routine
.venv/bin/python scripts/verify_backend.py deterministic-acceptance
cd frontend && npm run lint && npm run build
```

After all provider-free gates pass, run one fresh real 5G53 acceptance. The
Provider is not repeatedly consumed to test transaction mechanics.
