# Public types are independent of provider SDKs

The workbench defines its own public data types (ProteinSequence, ProteinStructure,
ProteinPrompt, ScoreCollection, etc.) rather than adopting ESM SDK types (ESMProtein)
directly as the system-wide contract.

Module adapters translate between the workbench's public types and provider-native
formats. When the ESM SDK changes its internal representation, only the ESM module
adapters are affected; the type system, execution engine, and other modules are not.

This is the non-obvious path: the straightforward alternative would be to make
ESMProtein the universal data carrier, since it already encodes most of the information
the workbench needs. Rejected because it would couple every module (including
ProteinMPNN, SimpleFold, and scoring modules) to the ESM SDK's release cycle.
