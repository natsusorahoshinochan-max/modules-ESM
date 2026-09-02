---
status: accepted
---

# Two-layer type system: nominal Port Types and runtime values

Port compatibility is checked against stable nominal `type_id` identity,
resolved through the current Port Type Definition. The core does not hard-code
the scientific structure of values; it delegates validation, canonical
encoding, and content-digest calculation to that Definition.

Runtime data may be carried by concrete Python classes or other values accepted
by the registered validator and codec. Node implementations read and write them
through the exact Port contract declared by their Node Definition.

Module Packages can register new Port Type Definitions without modifying
`core/`. Producer and consumer Ports connect only when both stable type IDs
match; scientific conversion uses an explicit Node Type.

ADR-0028 supplies the complete nominal contract and scientific admission rules
for this decision.
