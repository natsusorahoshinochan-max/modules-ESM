---
status: accepted
---

# Readiness is checked only when a Cache miss enters a Provider

Availability is a startup snapshot of an Execution Binding's baseline
prerequisites. Readiness is one direct check immediately before a Cache miss
enters that Binding's Provider seam. An Engine Invocation records actual entry
into the scientific engine. These facts have separate meanings, and Availability
never gates Readiness or execution.

A Cache hit trusts the previously admitted Result and replays it without
checking whether the Provider, model, runtime, or credential is currently
available. A Cache miss checks the selected Binding once before its first
Provider entry in that Run. Nodes using the same Binding share that conclusion.
This keeps replay independent of infrastructure that it does not use.

The Run records the stable Binding ID, time, conclusion, and diagnostic reason
without persisting credentials or private paths. It does not create a Readiness
contract digest, attestation digest, reusable-proof cache, maximum age,
configuration fingerprint, or invalidation state machine.

The Provider owner checks actual operability at this boundary: required external
configuration is present, imports and loads needed for the call succeed, and the
selected route can enter its Provider. It does not hash Provider source,
checkpoints, model assets, or installation trees and does not require PEP 610 or
Git checkout identity. Observed Availability and Readiness conclusions are
diagnostic evidence, not scientific identity.
