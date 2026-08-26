# Known implementation gaps

This file records accepted current architecture that the implementation has not
yet reached. It is not a compatibility plan or an alternative contract.

## Automatic Module Package discovery

Normative decision: [ADR-0018](adr/0018-module-packages-and-startup-discovery.md)
requires startup to scan each immediate child directory under `modules/` and
consume exactly one explicit `package.py:MODULE_PACKAGE` registration object.

Current implementation gap:
[`protein_workbench_public/bootstrap.py`](../protein_workbench_public/bootstrap.py)
imports and enumerates the twelve current Module Package registrations explicitly.
Adding a conforming repository-owned Module Package therefore still requires
editing the composition root.

The gap is closed when:

- adding a conforming immediate-child Module Package requires no bootstrap edit;
- discovery scans only immediate package roots and never recursively searches for
  definitions;
- each discovered package exports exactly one `MODULE_PACKAGE` registration;
- malformed imports, duplicate stable IDs, missing required references, or
  unresolved factories fail startup atomically; and
- optional Provider dependencies remain lazy and Binding-scoped.
