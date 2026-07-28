---
status: accepted
---

# Workflows pin Execution Bindings explicitly

Every persisted Node Instance identifies both its scientific `node_type_id` and
one exact `binding_id`. Workflow validation confirms that the binding exists,
belongs to that Node Type, and is available before execution; an unavailable
selection produces a structured validation error rather than environment-based
automatic selection or silent fallback to another binding.

The selected binding identity participates in cache keys, run manifests, and
provenance so the same Workflow cannot silently change Method, Adapter, or
deployment path on another machine. Binding-specific parameter ownership
remains a separate decision.
