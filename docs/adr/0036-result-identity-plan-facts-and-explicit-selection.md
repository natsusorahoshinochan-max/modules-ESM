---
status: accepted
---

# Result Identity uses compiler-owned plan facts and Selection is explicit

Result Identity identifies one reproducible scientific Node result. It is
independent of Workflow layout and authoring locators. A Node Instance ID,
upstream Node Instance ID, Workflow edge locator, Selection Objective label,
Run ID, Project ID, and unrelated downstream contract cannot change the
identity of an otherwise identical result. The immutable Execution Plan remains
topology-sensitive and therefore does change when those Workflow facts change.

The compiler is the single owner of the static facts used by Result Identity.
For every compiled Node it creates one immutable `ResultIdentityPlanFacts`
value containing the exact result-affecting Node Type, Execution Binding,
Method, input and output Port declarations, produced Observation contracts,
and only the Selection Objectives or Observation Selectors consumed by that
Node. Presentation fields and locator-like parameter indirections are excluded.
Scientific objective facts such as Metric, Method, Observation Context,
Utility Transform, weight, and missing-value policy remain included.

At execution time the runtime extends that compiler-owned projection with the
admitted typed input content identities, normalized Node and Binding
parameters, resolved resource identities, and effective randomness. It does
not reconstruct static facts from the Workflow, scan the Catalog, or add every
Utility Transform in the Workflow. The exact same canonical plan-facts
projection supplies Result Identity hashing, Cache contract metadata, and the
plan-facts digest recorded in the Run Evidence Ledger. Those consumers cannot
silently develop different identity rules.

An opaque Project input locator, including a `project_input_ref` parameter
value, is authoring and storage location rather than scientific identity. The
runtime resolves it before identity construction, excludes the locator value,
and records only the resource's semantic parameter role, exact content digest,
and byte size. The durable Project Input `filename` is likewise a provenance
label rather than scientific identity. Import operations project it through
Engine Invocation provenance, while the resolved-resource identity excludes
it. Renaming either the locator or filename for identical bytes therefore
preserves Result Identity; changing those bytes changes Result Identity.

The scientific Result Identity namespace remains
`protein-workbench-cache/v3`. ADR-0039 owns the current physical schemas:
Cache entry `v4` and Run Evidence Ledger `4.0.0`.
Development artifacts in prior namespaces are unsupported and are not
migrated, aliased, or replayed. Cache storage remains Project-scoped even
though the scientific Result Identity excludes Project identity. Cache entries
are best-effort replay indexes; an existing entry is not a public or cross-Run
consistency authority.

Selection executes only through an explicit Selection Node and its canonical
scientific operation. Every Workflow Selection Objective and Observation
Selector must be consumed by one declared exact consumer; unconsumed facts are
a compile error, and multiple consumers of the same declaration are also a
compile error. There is no end-of-Run weighted-selection fallback and no
synthetic `__workflow__` operation. Consequently Selection receives the same
Method, Result Identity, Cache, Operation Attempt, output admission, lineage,
and evidence treatment as every other scientific operation.

The rejected alternatives are hashing Node IDs or Workflow-wide Utility
contracts into every result, maintaining separate projections for Cache and
evidence, treating objective labels as scientific identity, and executing an
implicit Selection path outside the Plan. This decision refines ADR-0031's
identity inputs. ADR-0039 supersedes the former physical schemas and conflict
rules; ADR-0031's scientific identity, Project-scoped storage, and replay
semantics remain in force.
