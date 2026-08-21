---
status: accepted
---

# Candidate-associated scientific values and deterministic structure alignment

A derived scientific value that describes a Candidate must identify its exact
subject. Collection position, parallel list position, Workflow edge order, and
Node Instance ID are not scientific association. The canonical association key
is `CandidateDataReference`: the admitted Candidate identity, its nominal data
type, and the canonical content digest of its data.

Candidate, parent, collection, pairwise-participant, and Score subject
identities use the same bounded public Identifier grammar at their Datatype or
Port owner. Every admitted Candidate can therefore be represented by a
Candidate Data Reference and every public Candidate fact can represent the
same identity. Package-local values that embed Candidate Data References move
atomically when that identity contract changes; they do not keep a decoder for
the prior shape.

Structure residue axes, modified-residue normalizations, DSSP annotations,
secondary-structure tracks, SASA tracks, and Structure Alignment evidence carry
an exact Candidate Data Reference for each subject. Collection-valued
associations have a canonical order for content identity, but consumers join
them by complete reference equality and require exact set closure. A missing,
duplicate, extra, wrong-data-type, wrong-content-digest, or embedded-structure
association fails before a scientific engine starts. A producer whose own
Candidate IDs will be normalized during output admission cannot manufacture
derived values with those future identities in the same operation; a later
operation consumes the admitted Candidates and creates their associated
values.

Structure prediction follows that rule through an explicit generation and
materialization sequence. A generation operation emits structure Candidates
and a subjectless `structure_prediction.confidence_facts@2.0.0` value. For each
confidence-bearing structure output, the producer places the same canonical
Prediction Key in Candidate metadata and in one Confidence Fact. The key is
derived only from the exact output role and slot, structure content digest, and
`structure_prediction.prediction_residue_axis@2.0.0` content digest. The fact
also carries those exact structure and axis facts plus pLDDT, optional pTM, and
optional PAE; the enclosing collection carries their one exact provider
observation Method. Neither value contains a Candidate ID, Candidate Data
Reference, Score Observation, Run identity, or Engine Invocation identity.

`structure_prediction.materialize_confidence@2.0.0`, through
`structure_prediction.materialize_confidence.direct@2.0.0` and
`structure_prediction.materialize_confidence.exact_reference_join@2.0.0`, is
the later shared seam.
It consumes the admitted structure Candidate Collection and the matching
Confidence Fact Collection, obtains exact Candidate Data References from its
admitted input identities, and requires full-set closure by Prediction Key. A
missing, duplicate, extra, wrong-type, structure-digest-conflicting, or
axis-conflicting association fails before any Score Observation is emitted.
Only after that closure does it assign the admitted Candidate Data Reference as
the Score subject and populate `score.collection@5.0.0`.

The confidence-facts Port owns two dynamic projections. Its scientific-axis
projection exposes each exact prediction-axis reference, and its observation-
Method projection exposes the exact provider Method carried by the collection.
The materializer Binding declares those projections as the axis and Method
sources of its Produced Observations. Consequently per-residue and mean-residue
pLDDT and PAE retain their exact prediction population, while each final Score
retains the provider Method that observed the confidence. The materializer's
`structure_prediction.materialize_confidence.exact_reference_join@2.0.0`
Method identifies only the deterministic association and population operation;
it must never be substituted for the provider Method in a Score.

Folding and ESM generation therefore no longer emit Candidate-associated
confidence Scores in the generation operation. Each confidence-bearing
structure or coordinate-conditioned reconstruction Candidate Collection has a
separate matching Confidence Fact Collection. Sequence-only Candidates have no
structure-confidence fact or Prediction Key. Mean-residue pLDDT is populated
from the fact's valid per-residue values; PAE remains on the same square
prediction axis rather than being split into an independently associated
output.

`structure_transform.resolve_candidate_residue_axes` is the collection seam
that applies the scalar residue-axis contract to admitted structure Candidates.
It consumes Candidate-associated modified-residue normalization sets when
needed and emits Candidate-associated resolved axes. Downstream structure
comparison consumes the subject and reference Candidate Collections together
with their exact axis associations. It never zips two unlabeled collections and
never reparses the embedded PDB.

The default sequence-primary CA correspondence is one exact algorithm:

1. Each ordered residue-axis segment is globally aligned with BLOSUM62 using
   integer scores scaled by two. Gap open/extend are `-6/-1`; terminal gap
   open/extend are `-4/-1`.
2. A residue alignment maximizes sequence score, then paired-residue count,
   then chooses the lexicographically least CIGAR with `M < D < I`. It uses a
   suffix dynamic program and does not enumerate optimal alignments or stop at
   an ambiguity threshold.
3. Segment assignment maximizes the sum of sequence scores, then paired counts,
   then uses ordered segment indices as a total lexicographic tie-break. It is
   solved in polynomial time. Chain names are ignored unless the Workflow
   explicitly enables matching-chain pinning; duplicate names under pinning
   fail rather than being paired by occurrence order.
4. Only after correspondence is fixed are CA-bearing pairs selected and one
   global subject-to-reference SVD transform fitted. Coordinates and RMSD never
   break a sequence or segment tie.

The alignment evidence distinguishes axis residue count, CA-coordinate count,
sequence-paired residue count, and aligned atom count. Coverage is aligned CA
pairs divided by the larger complete axis length. Reference-normalized TM-score
uses the complete reference axis length; a residue admitted to the axis but
missing CA coordinates remains visible in normalization rather than silently
disappearing. One assigned segment may legitimately contain zero paired
residues, including an all-gap `D`/`I` CIGAR selected by the declared affine
Method; its `paired_residue_count` is zero and remains explicit in the segment
map. The complete alignment must nevertheless contain at least one paired CA
correspondence before a transform, RMSD, coverage, or downstream Metric can
exist. A zero-pair segment is not permission to emit an empty or silently
under-populated global fit.

RMSD and TM-score consume the admitted alignment evidence and record its exact
content digest, alignment Method, subject-axis content digest, and
reference-axis content digest in Observation Context; they do not parse either
structure again. Their Metric contracts declare the `alignments` input as the
required evidence source. Produced Observation admission recomputes each
alignment content digest through that Port Type and joins by the exact
subject/reference Candidate Data References. It requires the Context's two
axis digests and alignment Method to equal the joined evidence, and also closes
normalization length and aligned atom count against that evidence. Missing,
partial, stale, substituted, duplicated, or extra alignment provenance fails
output admission rather than remaining an implementation convention.

Structure-first TM-align is a separate explicit Method and Binding, not an
ambiguity fallback. It invokes trusted `tmtools.tm_align` without a fixed
sequence correspondence, translates the documented correspondence and
subject-to-reference transform, and recomputes residual evidence from the
returned transform. Its current contract accepts one CA-bearing segment per
axis because the library interface has no declared multimer chain-break
semantics. A future multimer structure-first algorithm requires a distinct
Method and decision.

The rejected alternatives are positional association, output-time guesses of
future Candidate IDs, raw `ATOM`/`HETATM` or CA reparsing in comparison,
Biopython-first or threshold-dependent tie selection, coordinate-based sequence
tie-breaking, exponential chain-map enumeration, implicit same-name chain
pinning, direct same-operation Candidate confidence Scores, constructing a
prediction axis by reparsing output PDB, attributing provider observations to
the materializer Method, and hidden TM-align fallback. This decision introduces
the Candidate Collection association contract anticipated by ADR-0035 and
supersedes its statement that the collection contract is only future work.
