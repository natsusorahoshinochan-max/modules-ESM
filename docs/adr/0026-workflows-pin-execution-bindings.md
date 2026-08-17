---
status: accepted
---

# Workflows pin Execution Bindings explicitly

Every persisted Node Instance identifies its exact scientific
`node_type_id` and `node_type_version` and one exact `binding_id` and
`binding_version`. The Binding fixes the Method, so the Workflow does not store
a second mutable Method choice. Version ranges, `latest`, environment-based
automatic selection, and silent fallback are forbidden.

The Workflow Compiler confirms identity, version, Binding ownership, parameters,
Ports, graph validity, and objectives, then emits an immutable Execution Plan.
Availability does not reject compilation. Execution trusts an admitted Cache
hit. On an Adapter-route Cache miss or bypass, it obtains Readiness for the
selected Binding immediately before entering its Provider seam. An unavailable
or unready Binding fails the Node Attempt with the exact structured Binding
error before an Operation Attempt starts. Direct routes enter their Operation
without Provider Readiness.

The selected Binding identity participates in Result Identity, run manifests,
and provenance so the same Workflow cannot silently change Method, Adapter, or
deployment path on another machine. ADR-0027 assigns cross-Binding scientific
parameters to the Node Definition, Method- or Adapter-specific parameters to
the Execution Binding, and runtime environment configuration outside the
Workflow parameter contract. The FrozenCatalog calculates canonical contract
digests for Node Types, Bindings, Methods, Metrics, Port Types, and Utility
Transforms; the Execution Plan and Manifest retain those resolved digests, and
one ID/version with a conflicting digest fails closed. A Binding digest covers
its immutable Availability and Readiness declarations, but not their observed
conclusions. ADR-0029 defines Readiness on Cache miss before Provider entry,
and ADR-0031 defines Result Identity and Cache reuse.
