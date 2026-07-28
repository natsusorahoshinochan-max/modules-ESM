---
status: accepted
---

# Execution Bindings own availability

A Node Definition always describes and discovers the scientific Node Type,
while each executable variant is an Execution Binding associating that Node
Type with one Method and one Adapter or factory. Availability is resolved and
reported per Execution Binding, so a missing model, runtime, accelerator,
binary, or credential makes only that binding `unavailable`; it does not hide
the Node Type or invalidate another binding.

Module Package registration contributes these bindings explicitly. Malformed or
conflicting binding contracts fail startup atomically, whereas valid but
unavailable bindings remain registered with structured reasons. This refines
ADR-0018. ADR-0026 defines explicit Workflow binding selection; the placement
of binding-specific parameters remains a separate decision.
