---
status: accepted
---

# One SimpleFold module owns Provider Asset Closure admission and staging

The `folding` Module Package has one package-private deep module that owns the
Provider Asset Closure grammar, exact file and source admission, and isolated
staging shared by the two distinct SimpleFold Adapters. Each Execution Binding
continues to own one immutable closure declaration; the module supplies one
implementation of that declaration rather than merging the Bindings or their
scientific Methods.

A Provider Asset Closure is the exact minimal set of result-affecting Provider
source and artifact identities required by one Execution Binding. File entries
fix their scientific or runtime role, runtime filename, and SHA-256. Source
entries fix an exact revision and, where required, the reviewed runtime
source-tree digest. Environment Configuration supplies locations only; private
paths, unrelated files in those locations, and temporary staged copies are not
closure identity. Expected byte counts and CDN ETags remain installation and
acquisition metadata. Neither is Method or Execution Binding identity or a
local Readiness content proof.

The SimpleFold folding closure contains `simplefold_100M.ckpt`,
`simplefold_1.6B.ckpt`, `plddt.ckpt`, and `ccd.pkl`; both the primary ESM2 weight
and its contact-regression weight; the exact SimpleFold source revision; and the
exact ESM2 revision and reviewed runtime source tree. The existing-structure
confidence closure contains `simplefold_1.6B.ckpt`, `plddt.ckpt`, `ccd.pkl`, only
the primary representation ESM2 weight, and the same exact source identities. It
explicitly excludes the 100M and 360M folding checkpoints, ESM2 contact
regression, and `boltz1_conf.ckpt`. Extra files may coexist in configured roots,
but they are neither rejected nor admitted, hashed, staged, or promoted into a
product capability.

The Binding-owned closure declaration is the one source for Method and Binding
descriptor projections, Readiness prerequisites, staging selection, and closure
tests. Parallel handwritten file lists or digest maps in the two Adapters are not
independent authorities. A result-affecting membership, role, content digest,
source revision, or reviewed source-tree change creates a new Method and
Execution Binding. A staging-only refactor that preserves all scientific inputs
and Provider behavior does not change the Method.

On the first Cache miss or bypass for one exact Binding, Readiness asks the deep
module to admit that Binding's closure once. File admission checks the declared
SHA-256 once. ESM2 source admission resolves the configured checkout, verifies
its exact HEAD, and hashes the declaration-owned reviewed runtime file set into
the declared aggregate digest once. The configured root is a location, not an
identity. Admission does not require a clean checkout, hash an unrelated package
tree, inspect extra files, or interpret an installed directory as the closure.
Subsequent Node Execution Attempts using the same Binding reuse the Run-scoped
Readiness conclusion fixed by ADR-0041.

Folding and confidence retain separate Readiness conclusions even when their
closures overlap. The implementation does not add cross-Binding memoization,
shared proof caches, expiry, invalidation, or an opaque admitted-resource payload
to the core Readiness interface. Under the trusted expected-use model, staging
uses the same Environment Configuration and declared files after admission and
trusts them without rehashing, querying Git, or rediscovering the source tree.

Before each Adapter call enters its Engine Invocation, the module copies only the
declared closure into a fresh private staging root and preserves the reviewed ESM2
source layout. It does not search another workspace or cache, invoke a downloader,
use the network, select another checkpoint, or fall back to an alternate source.
RunResources and the Node Execution Attempt lifecycle continue to own temporary
directory lifetime and cleanup.

Closure admission failure is a Readiness failure and therefore a Binding Failure
without an Operation Attempt or Engine Invocation. Failure to stage already
admitted assets occurs during Operation preparation before Provider entry, so it
fails the Operation without inventing an Engine Invocation. Provider import,
model loading, and scientific execution occur after the Invocation starts. A
successful Invocation followed by translation, normalization, or output admission
failure remains a successful Invocation inside a failed Operation Attempt.

The two Adapters remain the external seams and retain their different model
loading, namespace isolation, deserialization, provider-native representations,
and canonical translation. Folding retains the contact-regression loader,
sampling, high-level pLDDT, and PDB-tail translation. Existing-structure
confidence retains representation-only ESM2 loading, coordinate featurization,
direct-head masking, and native-to-canonical pLDDT normalization. The closure
module does not construct Candidates, Prediction Keys, Prediction Residue Axes,
Confidence Facts, Metrics, or published outputs.

Exact Provider, source, model, and checkpoint identities remain static Method and
Execution Binding facts. Invocation provenance does not repeat them or expose
private paths. A passing Readiness Attestation proves that the exact declared
closure matched, so durable evidence does not need a second observed-digest map.

Tests cross the shared module interface using temporary filesystems and real
temporary Git checkouts. They prove the two exact memberships, exclusions,
SHA and source-tree admission, the exclusion of byte count and ETag from
Readiness identity, staged layout without a second proof, trust-after-admission
behavior, and causal failure placement. Separate Adapter and real-Provider
acceptance tests continue to prove the two scientific Methods. The implementation
replaces duplicate hash, file-set, source-validation, and staging helpers plus
private cross-module calls; it retains no compatibility helper or alternate path.

The rejected alternatives are taking the union of the two closures, letting each
Adapter maintain a parallel closure grammar, admitting entire configured
directories, rejecting irrelevant extra files, rehashing during staging,
promoting byte count or ETag into scientific identity, querying Git or
rediscovering the source tree during staging, memoizing proofs across Bindings,
recording paths or static asset identities per Invocation, staging after an
Engine Invocation has started, and introducing a generic all-Provider asset
framework before another Module Package demonstrates the same seam.

This decision refines ADR-0025, ADR-0029, ADR-0032, ADR-0034, and ADR-0041. It
preserves the distinct folding and existing-structure confidence Methods and the
Adapter ownership established by ADR-0044.
