---
status: accepted
---

# SimpleFold confidence evaluation fixes its actual Method

SimpleFold evaluation is a separate confidence Node Type from folding and does
not expose mutable `model_name`. Its Method is the actual confidence
pipeline: the configured `simplefold_1.6B.ckpt` latent checkpoint,
`plddt_module_1.6B.ckpt` output head, `esm2_t36_3B_UR50D.pt` encoder
checkpoint, structure featurization contract, upstream scientific source
identity, and native-to-canonical pLDDT scale contract. The Execution Binding
and Result Identity additionally record the stable Workbench Adapter and
implementation identity. Checkpoint bytes, source-tree bytes, installation
origin, and device are not Method or Result Identity.

The evaluation Binding checks operability and loads only components used by that
pipeline. A folding-model checkpoint that does not contribute to the confidence
result is not loaded and is not a Readiness prerequisite. Readiness does not
hash the loaded assets or record their content digests as provenance.

A scientifically different model variant, featurization, or scale contract uses
a distinct stable Method and Binding ID. Reinstallation, packaging, device, or
byte-level replacement within the declared operational model route does not
create internal contract semver or a content-proof identity.
