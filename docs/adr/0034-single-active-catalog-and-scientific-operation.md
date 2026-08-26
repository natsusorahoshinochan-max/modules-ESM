---
status: accepted
---

# One current Catalog and one canonical scientific operation

Protein Workbench is scientific software under active development and has no
historical compatibility obligation. The current checkout publishes one
immutable `FrozenCatalog`. Every Node Type, Port Type Definition, Method,
Execution Binding, Metric Definition, Utility Transform, and Behavior resolves
uniquely by stable ID. Internal semantic versions, inactive generations,
version ranges, descriptor digests, and compatibility aliases are not part of
the Catalog identity model.

Repository-owned producers, consumers, examples, fixtures, tests, and
documentation change together when a current definition changes. Development
Workflow, Commit, Ledger, and fixture artifacts may be invalidated and
regenerated. When a current definition that can affect a scientific result
changes without receiving a new stable ID, cutover to that definition must
atomically clear or isolate every Cache entry created under the superseded
definition. The current runtime must never replay such an entry. The application
does not preserve an old reader, migration, parallel generation, or alternate
decoder for superseded internal contracts.

The Catalog builder validates stable-ID uniqueness, required references,
implementation or Adapter resolvability, Node/Binding ownership, Port
compatibility, Candidate and Observation subjects, Metric schemas, residue-axis
requirements, dependency closure, and the other relations that protect
scientific module inputs and outputs. The same direct builder is used for startup
and build/test verification; there is no generated registration layer or second
validation architecture.

Workflow admission resolves stable IDs into an immutable in-process Execution
Plan. Before execution crosses the scientific-operation seam, the plan has
selected the Node Type, Binding, Method, Port codecs, normalized parameters,
input sources, operation factory, Readiness declaration, effective-randomness
resolver, produced Observation and Selection facts, and scientific evidence
definitions. Execution consumes that plan and does not ask the Catalog to
reinterpret the Workflow.

A Workflow Commit is the durable root for execution. It stores the admitted
Workflow, the information required to rebuild its current plan, and minimum
Node/Method/Metric scientific definition snapshots needed to interpret its
results. A Run names that Commit only by `workflow_commit_id`; it does not bind
parallel Workflow, Catalog, Contract Lock, or Plan digests.

Each scientific operation has one canonical implementation for one scientific
meaning. Distinct algorithms or model variants remain distinct stable Methods.
A Provider Adapter alone translates admitted provider-independent values into
the provider's documented representation, invokes the selected route, and
translates its output back. Provider-native tensors, positions, payloads, paths,
and response objects do not cross that seam.

Provider source bytes, checkpoint bytes, Git state, installation form, and
device are not scientific Method identity. Readiness checks operability rather
than proving those bytes. CPU/GPU execution and its accepted tiny numerical
variation do not split Method, Result Identity, or Cache identity and do not
create a cross-device equivalence gate. An actual device observation may be
recorded as non-gating invocation provenance when already known.

Call seeds derive from the configured base seed, canonical scientific input
content, and stable parent, sample, and track slots. Candidate IDs, Result IDs,
Run IDs, scheduling order, and temporary paths never enter that derivation.
Effective randomness is included in Result Identity and invocation provenance
according to the owning Binding's scientific contract.

Canonical scientific values are immutable after admission. Their
contract-owning seam validates scientific invariants once; trusted in-process
callers then pass those values without repeated wire encoding or defensive
validation. Public input is validated at its wire boundary. Public output is
constructed by typed projections that guarantee the complete wire shape before
serialization. Internal metadata is read for required fields and causal state,
not revalidated as an adversarial or canonical-text protocol.
