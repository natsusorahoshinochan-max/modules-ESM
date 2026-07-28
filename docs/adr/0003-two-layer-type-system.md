# Two-layer type system: versioned nominal Port Types and runtime values

Port compatibility is checked against exact nominal `type_id + version`
identity, resolved through a Port Type Definition. The core does not hard-code
the scientific structure of values; it delegates validation, canonical
encoding, and content-digest calculation to that Definition.

Runtime data may be carried by concrete Python classes or other values accepted
by the registered validator and codec. Node implementations read and write them
through the exact Port contract declared by their Node Definition.

Module Packages can register new Port Type Definitions without modifying
`core/`. Producer and consumer Ports connect only when both exact identities
match; scientific conversion uses an explicit Node Type.

ADR-0028 supplies the complete versioned contract, atomic registration, and
fail-closed unknown-type rules for this decision.
