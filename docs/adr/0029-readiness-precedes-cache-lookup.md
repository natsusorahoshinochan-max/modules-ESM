---
status: accepted
---

# Readiness is attested before any Cache lookup

Availability is a startup snapshot of an Execution Binding's baseline
prerequisites. A Readiness Attestation is a run-scoped, point-in-time conclusion
for one exact Binding, while an Engine Invocation is actual entry into a
scientific engine. These facts are recorded separately and none substitutes for
another.

Before the first Cache lookup in a Run, every distinct Execution Binding
selected by the resolved Execution Plan must have a passing Readiness
Attestation. A failed or missing attestation rejects execution before Cache
access, so a Cache hit cannot provide offline replay around an unavailable
provider, model, runtime, binary, accelerator, or credential.

The immutable Readiness declaration has its own canonical contract digest,
which is included in the owning Binding's contract digest. An attestation
records its Binding, Readiness contract digest, safe
environment fingerprint, time, conclusion, and proof source without persisting
secret values, secret-derived hashes, or unsafe diagnostic output. Proof reuse
must be explicitly permitted by the Binding's readiness declaration and must
match its stated scope, maximum age, and configuration fingerprint; the Run
still records its own attestation and reference to the reused proof. Node
Instances selecting the same Binding may share that explicit run attestation.

Volatile prerequisites such as credentials, endpoints, binaries, paths, and
devices are re-observed for every Run. An expensive immutable proof may be
reused only under an explicit content or metadata identity and invalidation
contract. Zero-argument process-global readiness caches are forbidden.
Observed Availability and Readiness conclusions never enter a stable contract
digest.

This decision refines ADR-0025 and ADR-0026.
