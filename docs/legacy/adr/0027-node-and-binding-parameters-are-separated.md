---
status: accepted
---

# Node and Binding parameters are separated by scientific meaning

A Node Definition declares only parameters whose scientific meaning is stable
across every Execution Binding of that Node Type. Parameters specific to one
Method or Adapter are declared by that Execution Binding and may be fixed by a
Workflow without being presented as universal Node parameters.

Credentials, deployment endpoints, and runtime filesystem locations are
Environment Configuration rather than Workflow parameters. The composition root
validates these external fields once. Device and performance policy are
Adapter-owned operational facts and do not round-trip through Environment
Configuration. An actual device may be recorded as non-gating provenance but
does not split scientific or Cache identity.

Model identity belongs to the Method and Execution Binding. A mutable
`model_name` parameter cannot switch models within one Binding: a scientifically
distinct model variant receives a distinct Method and Binding identity.
