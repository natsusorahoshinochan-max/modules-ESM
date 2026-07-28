---
status: accepted
---

# Node and Binding parameters are separated by scientific meaning

A Node Definition declares only parameters whose scientific meaning is stable
across every Execution Binding of that Node Type. Parameters specific to one
Method or Adapter are declared by that Execution Binding and may be fixed by a
Workflow without being presented as universal Node parameters.

Credentials, device selection, deployment endpoints, and runtime filesystem
locations are Environment Configuration rather than Workflow parameters. They
control whether and where a Binding can execute; identities that affect
scientific results remain subject to the established provenance requirements.

Model identity belongs to the Method and Execution Binding. A mutable
`model_name` parameter cannot switch models within one Binding: a scientifically
distinct model variant receives a distinct Method and Binding identity.
