---
status: accepted
---

# Workflows pin Execution Bindings explicitly

Every persisted Node Instance identifies its scientific `node_type_id` and one
`binding_id`. Stable IDs resolve uniquely in the current Catalog. The Binding
fixes the Method, so the Workflow does not store a second mutable Method choice.
Contract semver, version ranges, `latest`, environment-based automatic
selection, and silent fallback are absent.

The Workflow Compiler confirms stable identity, Binding ownership, parameters,
Ports, graph validity, and objectives, then emits an immutable Execution Plan.
Availability does not reject compilation. Execution trusts an admitted Cache
hit. On an Adapter-route Cache miss or bypass, it obtains Readiness for the
selected Binding immediately before entering its Provider seam. Only a failing
fresh Readiness conclusion can stop entry with the structured Binding error;
startup Availability cannot. Direct routes enter their Operation without
Provider Readiness.

The selected stable Binding and Method IDs participate in Result Identity and
scientific evidence so the same Workflow cannot silently change scientific
route. ADR-0027 assigns cross-Binding scientific
parameters to the Node Definition, Method- or Adapter-specific parameters to
the Execution Binding, and runtime environment configuration outside the
Workflow parameter contract. Workflow Commit stores the minimum scientific
definition snapshots needed to interpret results; it does not preserve semantic
versions, descriptor digests, or a Contract Lock. ADR-0029 defines Readiness on
Cache miss before Provider entry, and ADR-0031 defines Result Identity and Cache
reuse.
