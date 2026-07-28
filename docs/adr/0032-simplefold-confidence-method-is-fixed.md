---
status: accepted
---

# SimpleFold confidence evaluation fixes its actual Method

SimpleFold evaluation remains a separate confidence Node Type from folding, but
it no longer exposes mutable `model_name`. Its Method is the actual confidence
pipeline: the exact `simplefold_1.6B.ckpt` latent checkpoint,
`plddt_module_1.6B.ckpt` output head, `esm2_t36_3B_UR50D.pt` encoder
checkpoint, structure featurization contract, upstream scientific source
identity, and native-to-canonical pLDDT scale contract. The Execution Binding
and Result Identity additionally record the Workbench Adapter and implementation
identity. All three assets retain their resolved immutable content digests as
specified by
[`provider-install-contract.md`](../provider-install-contract.md).

The evaluation Binding loads, attests readiness for, and records provenance
only for components used by that pipeline. A folding-model checkpoint that does
not contribute to the confidence result is not loaded, is not a readiness
prerequisite, and does not appear in Method or invocation provenance.

Changing any checkpoint, head, encoder, featurization, relevant source
implementation, or scale contract creates a new Method and Execution Binding;
it is not a parameter change within the existing Binding. This decision
supersedes ADR-0013 and refines ADR-0020 and ADR-0027.
