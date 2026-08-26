---
status: accepted
---

# One SimpleFold module owns Provider asset selection and staging

The `folding` Module Package has one package-private deep module that owns the
minimal operational Provider Asset Closure and isolated staging shared by the
two SimpleFold Adapters. Folding and existing-structure confidence remain
distinct scientific Methods and Bindings; sharing staging logic does not merge
their science.

The closure lists only the runtime roles and configured files or source
locations needed for a Provider call. It is an operational selection, not a
content or installation identity. It does not assign SHA-256 values, reviewed
source-tree digests, Git revisions, PEP 610 forms, byte-count proofs, or CDN
ETags to Method, Binding, Readiness, Result Identity, or provenance.

The folding route requires the checkpoints, ESM2 resources, and source locations
that its actual implementation loads. The existing-structure confidence route
requires only the resources that its actual implementation loads. Unrelated
installed assets are ignored. The shared module prevents the Adapters from
maintaining divergent file-role and staging lists, while preserving separate
route requirements.

On the first Cache miss or bypass for a Binding in a Run, Readiness checks the
configured locations, readability, required imports and loads, and other minimum
operational prerequisites. It does not hash files, verify checkout HEAD, inspect
dirty-tree state, prove an installation origin, or build a replacement manifest
or stat fingerprint. Nodes using the same Binding share that Run-scoped
conclusion; overlapping Bindings do not need a shared proof cache.

Before Provider entry, the module stages only the resources required by the
selected Adapter into a private temporary root and preserves the layout needed
by the Provider. It does not search another workspace, download assets, select
an alternate checkpoint, or fall back to another source. RunResources and the
Node Execution Attempt lifecycle own temporary-directory lifetime and cleanup.

Staging failure before Provider entry fails the Operation without inventing an
Engine Invocation. Provider import, model loading, and scientific execution
occur at their actual invocation seam. A successful Invocation followed by
translation, normalization, or output admission failure remains a successful
Invocation inside a failed Operation Attempt.

The Adapters retain their different model loading, namespace isolation,
provider-native representations, and canonical scientific translation. The
shared staging module does not construct Candidates, Prediction Keys,
Prediction Residue Axes, Confidence Facts, Metrics, or published outputs.

Focused tests cover route-specific required roles, exclusions, staged layout,
and causal failure placement without asserting hashes or Git installation form.
Real-Provider acceptance proves each scientific Method's input translation and
output semantics. No compatibility helper, alternate asset path, content-proof
cache, or defensive installation identity is added.
