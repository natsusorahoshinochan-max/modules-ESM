---
status: accepted
---

# One active Catalog generation and one canonical scientific operation

Protein Workbench is scientific software under active development and has not
been deployed. Scientific meaning, interpretability, and exact provenance take
precedence over runtime compatibility with development artifacts. The current
checkout therefore publishes exactly one active `FrozenCatalog` generation.
For each logical Node Type, Port Type Definition, Method, Execution Binding,
Metric Definition, and Utility Transform, that Catalog contains exactly one
active exact version.

An incompatible contract change receives a new exact version. Repository-owned
producers, consumers, examples, fixtures, and documentation change atomically.
The Catalog registers only the active identity and never assigns different
descriptor bytes to one exact identity. Exact descriptor bytes and digests,
environment locks, and Run Evidence preserve provenance without creating a
second executable runtime generation. Unsupported contract identities fail
closed.

The `FrozenCatalog` is a deep module for exact public contract publication and
resolution. Workflow admission and compilation use it to resolve an immutable
`Execution Plan`. Before execution crosses the scientific-operation seam, the
plan has already selected the exact Node Type, Execution Binding, Method, Port
contracts and codecs, normalized parameters, input sources, operation factory,
Readiness declaration, effective-randomness resolver, produced Observation and
Selection facts, and evidence identity. Admitted input values, environment,
resources, Availability, and effective randomness remain Run-scoped facts.
The canonical scientific operation receives admitted typed scientific values
and operation context. It does not receive the `FrozenCatalog`, search public
contracts, inspect public contract versions, or reconstruct its own Binding.

Execution consumes that exact retained plan and does not resolve contracts,
factories, codecs, or Utility Transforms again. A Derived Run reuses the exact
in-memory plan retained by its source Run. If only durable source evidence
remains after a process restart, derivation fails closed; `V2RunService` does
not reinterpret the persisted Workflow or mint a replacement executable plan
under the source compile identity.

Each scientific operation has one canonical implementation for one scientific
meaning. Distinct algorithms, model variants, or scientifically meaningful
checkpoints remain distinct Methods and may require distinct implementations.
Public contract publication is a projection of an operation's meaning, not a
second implementation of that operation. A contract-version change must not
create parallel positional and identity-based implementations of the same
science.

A Provider Adapter owns the true external seam. It alone translates admitted
provider-independent values into the provider's documented representation,
invokes the declared provider route, translates the documented result back,
and records invocation-specific provenance. Exact provider, model, checkpoint,
and source identity are static facts owned once by the exact Method and
Execution Binding descriptors; they are not copied into Candidate metadata or
repeated as per-call provenance. Every Engine Invocation uses the exact Method
contract digest as its engine identity; the Execution Plan owns that field and
an Operation or Adapter cannot supply or override it. Provider-native positions,
tensors, payloads, paths, and response objects do not cross that seam. Scientific
transformations, Candidate lineage, Metric meaning, unit conversion, masking,
residue mapping, and call-seed derivation do not belong in the Adapter.

Call seeds are derived from the configured base seed, canonical scientific
input content, and stable parent, sample, and track slots. Candidate IDs,
Result IDs, Run IDs, scheduling order, and temporary paths never enter that
derivation. The configured base seed is first normalized as an ordinary Node
parameter. A Binding without an explicit effective-randomness declaration
keeps it in the Result Identity's normalized Node parameters and contributes
an empty `effective_randomness` object; the runtime never infers randomness
from parameter names such as `seed`, `random_seed`, or `effective_seed`. A
Binding with exact seed control explicitly declares and resolves that parameter
into Result Identity randomness. An Adapter that actually applies the derived
seed records closed
invocation provenance under `effective_randomness` with `control=exact_seed`
and the applied `effective_seed`. An official provider route without seed
control records `control=provider_uncontrolled`, does not send a seed, and does
not publish an effective-seed claim. Those two randomness variants are mutually
exclusive. The closed provenance object can also contain the orthogonal
`provider_residue_projection` fact; ProteinMPNN design records both facts in
the same Invocation, while deterministic scoring records only the projection.

Canonical scientific values are immutable after admission. Their
contract-owning seam validates scientific invariants once; trusted in-process
callers then pass those values directly without repeated wire encoding,
decoding, or defensive validation. Validation remains at Project Input,
provider translation, explicit scientific transformations, persisted-value
admission, and durable-write seams. Local invariant violations fail fast.
Authentication, authorization, multi-tenancy, sandboxing, adversarial provider
handling, speculative fallbacks, and compatibility shims are outside the
trusted single-user deployment model.

`ProteinStructure` owns canonical PDB scientific content and nothing else. The
active `protein.structure@4.0.0` wire contains exactly one field,
`pdb_string`; provider, project-input, file, and source labels are provenance,
not scientific content, and therefore cannot change its content digest. That
provenance is owned by Method, Execution Binding, Candidate lineage, or Run
Evidence at the seam where the fact is known. The active
`structure_transform.backbone_structure@4.0.0` wire likewise contains only
canonical PDB content. Its nominal distinction is established by its closed
backbone atom, ordering, chain-break, and serialization invariants, never by a
producer string. Both Port Types have one decoder for their current closed
wire shape and accept no source-bearing fields.

Every Node Type and Execution Binding that directly declares either active Port
Type uses its current exact generation. A Method keeps its exact identity only
while its complete scientific definition is unchanged. Secondary-structure and
SASA projection Methods use version `3.0.0` with exact Candidate Data Reference
association contracts. The semantically distinct prompt-conversion Methods use
version `2.2.0`. ProteinMPNN design uses the current identity-based constraints
value and design Method. Candidate collections resolve their declared item type
through the one active Catalog and carry no compatibility registry or alternate
structure decoder.

ProteinMPNN has one identity-based constraints value, one canonical design
operation, and one Adapter per real provider route. Only the Adapter converts
stable `ResidueIdentity` values to provider positions. No positional
compatibility contract or alternate decoder is executable.
