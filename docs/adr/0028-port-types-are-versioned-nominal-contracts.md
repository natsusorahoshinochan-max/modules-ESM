---
status: accepted
---

# Port types are explicit versioned nominal contracts

Every Port identifies one exact `PortTypeDefinition` by `type_id` and version.
Core types are registered as built-ins; Module Packages may contribute
additional definitions through their production registration object. Each
definition owns a contract digest, validator, canonical codec, and
content-digest procedure for values of that type.

The temporary Registry builder resolves its Port Type view atomically at
startup before Node Definitions are accepted, then publishes it only as part of
the single FrozenCatalog. An unknown type reference or two conflicting
definitions for the same `type_id` and version fails startup rather than
leaving a partially usable Catalog.

Port compatibility is exact nominal identity: both `type_id` and version must
match. Structural similarity, implicit coercion, and version-range matching do
not create compatibility; a changed contract receives a new version and any
conversion is represented by an explicit Node Type.

This decision refines ADR-0003, ADR-0018, and ADR-0023.
