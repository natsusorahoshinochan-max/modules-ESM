---
status: accepted
---

# Public types are independent of provider SDKs

The workbench defines its own public data types (ProteinSequence, ProteinStructure,
ProteinPrompt, ScoreCollection, etc.) rather than adopting ESM SDK types (ESMProtein)
directly as the system-wide contract.

Module adapters translate between the workbench's public types and provider-native
formats. When the ESM SDK changes its internal representation, only the ESM module
adapters are affected; the type system, execution engine, and other modules are not.

Provider-independent public types keep the type system, execution engine, and
Module Packages independent of any provider SDK's representation and release
cycle.
