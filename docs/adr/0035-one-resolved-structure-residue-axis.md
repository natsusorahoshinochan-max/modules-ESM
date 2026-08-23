---
status: accepted
---

# One resolved structure residue axis owns component disposition and topology

A PDB coordinate record type is not a scientific polymer classification.
`ATOM` and `HETATM` describe deposition records; modified polymer residues,
ordinary ligands, and solvent can all require different scientific treatment.
No downstream Method or Adapter may therefore infer the protein residue axis
again by filtering record names.

The active `protein.structure@4.0.0` admission boundary owns the canonical
wwPDB v3.3 coordinate-record syntax before any residue-axis logic runs. Every
`ATOM` and `HETATM` record is exactly 80 columns; occupancy, temperature factor,
and right-justified ASCII element are required and finite; charge is blank or
one canonical magnitude-sign pair; and unassigned columns are blank. The
four-column PDB residue sequence field is signed and its authored sign and
optional insertion code remain part of the exact chain-qualified
`ResidueIdentity`. Structure transforms trust this admitted syntax and add only
their operation-specific biology and topology checks.

`structure_transform.resolve_residue_axis` is the single contract-owning seam
for one admitted structure. It preserves the exact input `ProteinStructure`
inside an immutable resolved value and records the disposition of every
observed coordinate component. The 20 standard parent amino-acid residues are
included in PDB segment order whether their admitted coordinate records are
`ATOM` or `HETATM`; record type remains deposition provenance, not scientific
classification. An unknown `ATOM` residue is not guessed to be sequence `X`;
it requires an exact parent contract. An exact `MODRES`
MSE-to-MET declaration, with one unique ordered correspondence in the same
chain's `SEQRES` polymer sequence, is normalized to parent methionine at the same
chain-qualified residue identity and carries an explicit source-to-parent atom
map. Water and ordinary non-polymer components are excluded from the protein
axis but remain present in the exact structure and in the component-disposition
inventory. A modified or peptide-like polymer component without an exact
repository-owned normalization contract fails closed at this seam; it is not
silently omitted, mapped to `X`, or treated as a ligand.

The resolved value owns one identity-complete `ResidueLayout`, parent sequence
and residue names, explicit ordered segment topology, selected named-atom
coordinates associated by residue identity, CA and complete-N/CA/C/O masks,
all component dispositions, and all applied modified-residue normalization
records. Alternate-location selection is fixed to blank first and `A` second;
any other ambiguous atom selection fails. Consumers use the associated
coordinate fields and masks. They do not parse the embedded PDB to rebuild a
second axis or reclassify `ATOM` and `HETATM` components.

`extract_sequence`, `extract_sequence_candidates`, and `extract_backbone`
consume the resolved scalar or exact-reference-associated Candidate axis
directly. Sequence extraction is an identity-preserving projection of the axis
parent sequence and residue identities. Backbone extraction projects the axis
parent residue names, selected N/CA/C/O coordinates, complete-backbone mask,
and segment topology; raw coordinate records never decide its residue
population. Candidate sequence extraction additionally consumes the input
Candidate Collection solely for exact lineage and declared output ordering,
then requires a complete `CandidateDataReference` bijection to its axes; it
does not inspect Candidate structure data. Chain selection precedes axis
resolution and therefore preserves the selected chains' `MODRES` and `SEQRES`
declarations together with their
coordinate records. Candidate chain selection uses that same scalar transform,
so resolving a retained Candidate does not lose or change its normalization
evidence.

A Provider Adapter that requires chain-native structure featurization must
project this admitted topology rather than collapse it. Each ordered resolved
axis segment becomes one distinct provider-safe chain with continuous
one-based positions starting at one; two segments of the same Workbench chain
remain two provider chains because a `TER` record alone does not define chain
topology to every provider parser. Workbench chain-level design/fixed
constraints apply to every provider segment belonging to that chain, while
residue-level fixed/designable/tied/bias/reference inputs and returned
sequences translate only through the exact canonical-residue-to-segment-local
mapping. Invocation provenance records the unique Workbench chain order, the
ordered provider structure-segment chains, the actual provider featurization
chain order, and each residue's segment index, provider chain, and local
position.

Structure-prediction confidence has a different authoritative population. A
`PredictionResidueAxis` records the exact prediction input source, the
identity-complete layout submitted to or produced for the prediction, and the
actual prediction sequence. Folding uses the admitted parent-sequence
`CandidateDataReference` as that source; ESM generation uses the exact admitted
ProteinPrompt Port-value reference. The prediction operation constructs this
axis from those admitted inputs and the actual prediction sequence. It must not
parse its output PDB to invent the prediction axis. A later resolved structure
axis may describe the admitted output structure for structure-based Methods,
but it neither replaces nor repairs the provider request/prediction population.

Prediction confidence values retain that population explicitly. Per-residue
pLDDT has exactly one position for every prediction-axis residue, including
explicit nulls. Mean-residue pLDDT is the equal-weight arithmetic mean over the
valid protein-residue pLDDT values on that same axis and retains the axis
reference. PAE is a square residue-pair matrix whose two dimensions are that
same prediction axis. The candidate-global pTM scalar is not assigned a residue
axis. No value is shortened to atoms present in the output PDB or repopulated
from a resolved-structure coordinate mask.

An upstream exact normalization may supply its typed mapping to axis
resolution. CSH normalization expands the locked component to its SER-HIS-GLY
parent span and removes a deposited `TER` only when that record lies exactly at
the covalent parent-span insertion boundary. The repaired structure must expose
one continuous segment across the expanded parents. Other deposited segment
boundaries remain unchanged. The source Project Input is immutable, and raw CSH
is rejected by residue-axis resolution.

CSH normalization also owns the declaration repair made necessary by that
expansion. Every `MODRES` and `SEQRES` record unrelated to a normalized CSH
component is retained byte-for-byte and in declaration order. A `MODRES` whose
exact chain-qualified identity declares the normalized CSH component is removed
because no CSH coordinate component remains; the typed normalization output is
the authoritative component-to-parent provenance. When a normalized chain's
`SEQRES` declaration contains `CSH`, the number of `CSH` tokens must equal the
number of normalized CSH coordinate components in that chain, and each token is
replaced by the ordered `SER HIS GLY` parent span. The affected chain's complete
`SEQRES` series is then emitted as canonical 80-column PDB v3.3 records with at
most 13 components per record and the corrected declared count. A normalized
chain whose `SEQRES` already contains no `CSH` is preserved exactly; the
normalizer does not guess a positional correspondence or synthesize missing
polymer declarations.

The active resolved-axis Port embeds the current exact
`protein.structure@4.0.0`, `residue.layout@3.0.0`, and
`structure_transform.modified_residue_normalizations@3.0.0` contracts. Its closed codec
binds structure content, axis identities, segment topology, component
dispositions, coordinates, masks, and normalization records into one content
identity. The resolver Node Type and direct Binding change whenever those
declared Port contracts or the output descriptor change. A Method changes only
when the scientific classification, normalization, coordinate-selection, or
topology algorithm changes. The CSH topology repair is such a scientific
change, so its normalization Method receives a new exact version as well as a
new Node Type and Binding version.

The scalar axis describes exactly one structure. Candidate Collection workflows
use `candidate.collection@4.0.0` together with
`structure_transform.candidate_resolved_residue_axis_associations@6.0.0` and,
when required,
`structure_transform.candidate_modified_residue_normalization_associations@6.0.0`.
Every association carries the complete
`CandidateDataReference`—Candidate identity, data type, and Candidate data-content
digest—beside its resolved axis. The codec canonically sorts associations only
for representation; collection index is never scientific correspondence. The
collection resolver requires exactly one admitted structure reference per input
Candidate, rejects missing, duplicate, extra, structure-conflicting, or
digest-conflicting evidence, and emits exactly one axis association for each
reference. If modified-residue normalizations are supplied for a Candidate
Collection, they use the same complete-reference association contract and must
cover exactly the same Candidate references; normalization list position never
selects a structure.

The exact nominal, Candidate-association, and single-active-operation contracts
defined by ADR-0028, ADR-0033, and ADR-0034 apply to every resolved residue axis.
