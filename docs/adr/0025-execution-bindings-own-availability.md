---
status: accepted
---

# Execution Bindings own availability

A Node Definition always describes and discovers the scientific Node Type,
while each executable variant is an Execution Binding associating that Node
Type with one Method and either a direct implementation or the required
Adapter. Module Package registration supplies the corresponding lazy
implementation or Adapter factory. Availability is resolved and reported per
Execution Binding, so a missing model, runtime, accelerator, binary, or
credential makes only that Binding `unavailable`; it does not hide the Node
Type or invalidate another Binding.

Module Package registration contributes these bindings explicitly. Malformed or
conflicting binding contracts fail startup atomically, whereas valid but
unavailable bindings remain registered with structured reasons. This refines
ADR-0018. ADR-0026 defines explicit Workflow binding selection, and ADR-0027
assigns parameters according to their scientific meaning and execution scope.

Availability is only the startup snapshot of a Binding's basic prerequisites.
It is neither a per-Run Readiness Attestation nor evidence that an Engine
Invocation occurred. ADR-0029 defines Readiness and its admission order, while
ADR-0030 defines actual invocation evidence.
