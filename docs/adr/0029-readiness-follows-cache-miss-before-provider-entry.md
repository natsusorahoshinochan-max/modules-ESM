---
status: accepted
---

# Readiness is checked only when a Cache miss enters a Provider

Availability is a startup snapshot of an Execution Binding's baseline
prerequisites. Readiness is one direct check immediately before a Cache miss
enters that Binding's Provider seam. An Engine Invocation records actual entry
into the scientific engine. These facts have separate meanings.

A Cache hit trusts the previously admitted Result and replays it without
checking whether the Provider, model, runtime, or credential is currently
available. A Cache miss checks the selected Binding once before its first
Provider entry in that Run. Nodes using the same Binding share that conclusion.
This keeps replay independent of infrastructure that it does not use.

The immutable Readiness declaration remains part of the owning Binding's
contract digest. The Run records the Binding, Readiness contract digest, time,
conclusion, and proof source without persisting credentials or private paths.
There is no reusable-proof cache, maximum age, configuration fingerprint, or
invalidation state machine.

The Provider owner checks the result-affecting commit, model, checkpoint, and
required assets once at this boundary. After admission, internal components
trust those values. Observed Availability and Readiness conclusions do not
enter a stable scientific contract digest.
