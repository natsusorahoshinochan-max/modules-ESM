---
status: accepted
---

# One folding module constructs paired prediction outputs

The `folding` Module Package has one package-private deep module that owns the
provider-independent construction of outputs shared by every `folding.fold`
Method. It concentrates exact parent intake, Prediction Residue Axis
construction, canonical output slots, structure digests, Prediction Keys,
Candidate lineage, Prediction Confidence Facts, and the two matching output
collections behind one small interface.

Before Provider entry, the module accepts one complete admitted parent input
record carrying the sequence Candidate Collection, its content identity, and
its exact Candidate Data References. It does not accept independent value,
digest, or reference containers that must be rejoined. It trusts nominal Port
admission and Plan-normalized Node and Binding parameters. The module owns only
the folding-specific canonical 20-amino-acid alphabet, non-empty collection,
single-chain, identity-complete layout, and exact-parent/sample closure. Those
scientific contracts are checked once; the module does not defensively
revalidate values already admitted by their contract owners.

After Provider calls complete, the module accepts one closed batch of
completed folding samples. Each sample identifies its parent and sample slots
and carries one canonical ProteinStructure, canonical per-residue pLDDT,
optional pTM and PAE, and closed actual sampling facts. The interface does not
accept arbitrary Candidate metadata, caller-created Candidates, Prediction
Keys, Confidence Facts, axes, digests, or collections.

For every parent the module requires exactly the declared number of sample
slots, with no missing, duplicate, or extra pair. It emits canonical
parent-major and sample-minor order independent of incidental caller list
order. It creates provisional Candidate identities, exact parent lineage, and
the matching collections; output admission later establishes canonical
Candidate identity under the existing Result Identity contract.

The Prediction Residue Axis is constructed only from the admitted parent
sequence, its exact Candidate Data Reference, and the actual prediction
sequence, which for folding is the exact sequence supplied to the Adapter. The
output PDB is never parsed to construct, repair, or shorten that axis. The
module derives each Prediction Key from the exact output role and slot, the
canonical structure-content digest, and the prediction-axis digest, then places
the same key in the Candidate metadata and one subjectless Prediction
Confidence Fact. The Confidence Fact Collection retains the exact resolved
folding Method.

Candidate metadata has one module-owned closed grammar: parent slot, sample
slot, Prediction Key, and actual sampling facts. A controlled route may retain
the applied call seed, and SimpleFold may retain the actual sampling-step
count. The configured base seed remains a Node parameter and Result Identity
fact. The stable Method and Binding IDs identify the scientific route and are
not copied into every Candidate. Provider source, checkpoint bytes,
installation form, and device are not scientific identity.

ESMFold2 and SimpleFold retain distinct scientific implementations. Each owns
its parameters, call-seed derivation, Provider batching, Adapter calls, and
Provider-specific confidence translation. Adapters remain the external seams:
they translate admitted provider-independent values, invoke their documented
routes, return canonical structure and confidence values plus actual
randomness, and record Engine Invocation provenance. They do not construct
Candidates, Prediction Keys, Prediction Residue Axes, or Confidence Facts.

ESM-3 generation is excluded because its ProteinPrompt source, multiple output
roles, coordinate-conditioned reconstruction, classification, and pairing
semantics would widen the folding interface until it became shallow. The
SimpleFold existing-structure confidence Method is also excluded because it
does not produce structure Candidates. The `structure_prediction` Module
Package continues to own the provider-independent axis and confidence value
contracts and the later deterministic Confidence Materialization operation.

Folding output construction remains inside the scientific Operation. It does
not write immutable objects, the Run Evidence Ledger, public projections, or
Cache entries and is not Node Outcome Publication. An Adapter failure or an
output-construction invariant failure fails the Operation without returning
partial outputs. Completed Engine Invocations remain honest evidence; no
sample is filled, repaired, retried, reordered through fallback, or published
partially.

Tests cross the shared interface for exact parent admission, multi-parent and
multi-sample closure, canonical order, axes, lineage, keys, confidence, closed
metadata, and all-or-nothing failure. Separate Method and Adapter tests own
ESMFold2 and SimpleFold parameter, randomness, batching, translation, and real
Provider semantics. Tests use the shared interface rather than another Method's
private helpers and do not inject malformed admitted records to demand a second
generic validator.

The shared module is the sole Candidate and Confidence Fact assembly path. It
has no compatibility helper, generic folding runner, alternate publication
path, or hypothetical Adapter. If the closed output metadata changes public
output semantics, the folding Node Type and all three Bindings move together;
the exact ESMFold2 and SimpleFold Method identities remain because their science
is unchanged.
