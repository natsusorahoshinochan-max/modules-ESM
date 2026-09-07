---
status: accepted
---

# Port Types are explicit nominal scientific contracts

Every Port identifies one `PortTypeDefinition` by stable `type_id`. Core types
are registered as built-ins; Module Packages may contribute additional
definitions through their production registration object. Each definition owns
the scientific admission and canonical scientific codec needed to interpret its
values. Scientific values that use content identity also define the canonical
bytes and content-digest procedure for that value.

The Catalog builder resolves the Port Type view before Node Definitions are
admitted. It rejects unknown references, duplicate stable IDs, and incompatible
producer/consumer Ports. Focused owner tests separately exercise every scientific
codec with valid, invalid, and round-trip cases. Startup and tests use the same
Catalog builder; there is no separate generated registration artifact.

Port compatibility is nominal `type_id` equality. Structural similarity,
implicit coercion, and version-range matching do not create compatibility. A
scientifically different value contract receives a different stable `type_id`,
and conversion is represented by an explicit Node Type. Repository-owned
producers, consumers, tests, examples, and documentation change together when a
current definition changes; no inactive version registry or compatibility
decoder is retained.
