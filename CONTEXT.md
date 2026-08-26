# Protein Workbench

Protein Workbench is a node-based environment for composing protein design,
folding, evaluation, transformation, and selection operations. Its language
separates scientific operations from the packages and deployment adapters that
make those operations executable.

## Workflow Language

**Node Type**:
A reusable scientific operation with declared inputs, outputs, and parameters.
Its scientific identity does not change when its deployment mechanism changes.
_Avoid_: Module, implementation, model runner

**Node Instance**:
A concrete use of a Node Type in a Workflow, with one explicitly selected
Execution Binding, bound parameters, and connections.
_Avoid_: Node Type, block, step, task

**Workflow**:
A directed acyclic graph of Node Instances connected through compatible Ports.
_Avoid_: Pipeline, recipe, protocol

**Workflow Draft**:
One unlocked immutable authoring revision, which may be incomplete or invalid
and cannot be executed.
_Avoid_: Workflow Commit, Execution Plan, runnable revision

**Workflow Commit**:
One immutable runnable publication of an admitted Workflow Draft. It stores the
admitted Workflow and the minimum scientific definition snapshots required to
interpret its results. The current Catalog recompiles its in-process Execution
Plan when needed.
_Avoid_: Workflow Draft, compile ID, mutable active Workflow

**Run**:
A single admitted execution of a Workflow, with its own evidence and terminal
outcome.
_Avoid_: Job, session, Workflow

**Execution Plan**:
The immutable, fully resolved in-process form of a validated Workflow, fixing
its stable contract IDs, implementations, codecs, parameters, and scientific
relationships for execution.
_Avoid_: Workflow document, scheduler state, Run

**Port**:
A named input or output of a Node Type whose values conform to one Port Type
Definition.
_Avoid_: Slot, pin, socket

**Port Type Definition**:
The nominal scientific contract for values crossing a Port, including their
scientific admission, canonical scientific representation, and content identity.
_Avoid_: Unregistered type string, implicit conversion, inferred datatype

## Extension Language

**Module Package**:
A cohesive repository-owned extension unit that provides one or more Node
Types, their Node Definitions, Methods, Execution Bindings, and required
implementations or Adapters. The Catalog builder admits its production
registration; focused owner tests exercise its scientific behavior and codecs.
_Avoid_: Plugin, single node, module directory

**Node Definition**:
The public contract that declares a Node Type's identity, Ports, cross-Binding
scientific parameters, and user-visible meaning. Each Node Type owns exactly
one Node Definition.
_Avoid_: Implementation metadata, Binding configuration, runtime state

**Adapter**:
The translator that converts a provider, model, runtime, or deployment mode
into Workbench inputs, outputs, errors, and provenance without changing the
Node Type's scientific meaning.
_Avoid_: Node Type, Execution Binding, provider name

**Execution Binding**:
The executable association of one Node Type with one Method and either a direct
implementation or a required Adapter. It owns route-specific parameters and the
Availability and Readiness contracts, while scientific model or algorithm
identity remains fixed by its stable Method ID.
_Avoid_: Node Definition, Adapter, provider name

**Provider Asset Closure**:
The minimal operational set of Provider files and source locations required by
one Execution Binding. It selects what is loaded or staged but does not make
source bytes, checkpoints, Git metadata, or installation form part of scientific
identity.
_Avoid_: Content proof, installation identity, Provider inventory

**Environment Configuration**:
Credentials, deployment endpoints, and runtime filesystem locations supplied by
the composition root to make an Execution Binding operable without becoming
scientific Workflow parameters. Adapter-owned device and performance policy do
not round-trip through this configuration.
_Avoid_: Node parameter, Binding parameter, scientific input

**Module Package Registration**:
The complete production contract through which a Module Package contributes
Node Types, Execution Bindings, Methods, Metric Definitions, Port Type
Definitions, Utility Transforms, and Availability and Readiness declarations.
The Catalog builder admits its stable IDs, implementation references, and
scientific relationships once when constructing the current Catalog.
Contract-test cases and fixtures are separate from it.
_Avoid_: Import side effect, per-node registration call, recursive discovery

**FrozenCatalog**:
The immutable admitted startup result containing the current stable-ID
registrations, scientific relationships, and diagnostic Binding Availability
observations used by authoring and compilation.
_Avoid_: Mutable Registry, discovery workspace, runtime plugin manager

**Availability**:
The startup-resolved snapshot of whether an Execution Binding's baseline
prerequisites appear to exist and, when they do not, the structured diagnostic
reason. It never authorizes or blocks execution.
_Avoid_: Readiness Attestation, discovery failure, disabled node

**Readiness Attestation**:
A run-scoped, point-in-time conclusion about whether one Adapter Execution
Binding's declared prerequisites allow a Cache miss or bypass to enter its
Provider seam. Cache replay does not require Readiness.
_Avoid_: Availability, provider call, guarantee of invocation success

**Binding Failure**:
The failed Node Execution Attempt produced when Run-scoped Readiness stops a
Cache miss or bypass before an Operation Attempt starts. It preserves the
Binding error and never invents an Operation or Engine Invocation. Availability
alone cannot produce a Binding Failure.
_Avoid_: Operation failure, admission failure, provider failure

**Contract Test Kit**:
Shared focused conformance helpers used by maintainers to verify a Module
Package's extension, execution, data, and provenance behavior. They do not
require exact-set equality over every registered Node, Binding, or Port.
_Avoid_: Package-specific smoke tests, manual checklist

## Scientific Data and Scoring

**ProteinPrompt**:
A residue-aligned, multi-track specification containing sequence, structure,
secondary-structure, accessibility, function, and masking information. Its SASA
track means nullable absolute per-residue solvent-accessible surface area in
square angstroms, with no relative-accessibility normalization.
_Avoid_: Prompt object, ESM input, multi-track input

**Candidate**:
A generated or transformed protein sequence or structure with stable
run-independent identity, lineage, and provenance.
_Avoid_: Result, output sample, generation

**Candidate Collection**:
An ordered collection of Candidates that flow together through evaluation and
selection operations.
_Avoid_: Batch, result list, candidate set

**Candidate Data Reference**:
The exact association key comprising a Candidate identity, its nominal data
type, and the canonical content digest of that Candidate's data. Derived
scientific values use it to name their subject without relying on collection
position.
_Avoid_: Candidate, list index, Node Instance locator

**Metric Definition**:
The canonical scientific meaning of a measured quantity, including its value
shape, unit, direction, range, granularity, and aggregation semantics.
_Avoid_: Score ID, output field, display label

**Method**:
The stable-ID scientific definition of the algorithm or model variant used to
perform a Node Type or observe a Metric, including the facts needed to interpret
its result.
_Avoid_: Metric, provider, arbitrary implementation

**Observation Context**:
The typed scientific context required to interpret a Score Observation, such as
an intrinsic measurement or role-labelled reference Candidate.
_Avoid_: Score ID suffix, free-form details, Method

**Score Observation**:
A value that binds one Candidate to one Metric Definition, one Method, and one
Observation Context.
_Avoid_: Bare score, score ID/value pair, evaluation result

**Score Collection**:
A collection of Score Observations consumed by comparison, filtering, and
selection Node Types.
_Avoid_: Score set, metric bundle, evaluation result

**Utility Transform**:
An explicit mapping from a selected Metric, Method, and Observation
Context's canonical value to a dimensionless `[0, 1]` value configured by a
Workflow's Selection Objective.
_Avoid_: Implicit normalization, dataset-relative scaling, raw score weight

**Selection Objective**:
A Workflow-owned preference that identifies exact Score Observations and fixes
their Utility Transform, weight, and missing-value policy.
_Avoid_: Metric Definition, implicit ranking rule, display preference

**Structure Alignment Evidence**:
The exact Candidate-associated structural superposition, residue-axis
provenance, correspondence, normalization, transform, and Method identity
shared by downstream structural Metrics.
_Avoid_: Built-in StructureAlignment, superimposition result, structural match

**Resolved Structure Residue Axis**:
The canonical, immutable interpretation of one admitted ProteinStructure,
including its parent residue sequence, identity-complete layout, segment
topology, selected named-atom coordinates, masks, component dispositions, and
modified-residue normalization provenance.
_Avoid_: ATOM-only view, reparsed CA list, implicit chain sequence

**Prediction Residue Axis**:
The exact residue population used by one structure prediction, binding its exact
input source to an identity-complete layout and the actual prediction sequence.
It is independent of any later interpretation of the output structure.
_Avoid_: Provider token positions, output-PDB residue list, Resolved Structure
Residue Axis

**Prediction Key**:
A content-derived association key shared by one predicted structure output and
its subjectless Prediction Confidence Fact before Candidate identity exists. It
does not identify a Candidate.
_Avoid_: Candidate ID, Candidate Data Reference, collection index

**Prediction Confidence Fact**:
A subjectless provider observation for one predicted structure, carrying its
Prediction Key, exact structure-content digest, Prediction Residue Axis, and
confidence values until an admitted Candidate can become the subject.
_Avoid_: Score Observation, Candidate annotation, unlabeled confidence array

**Confidence Materialization**:
The exact association of Prediction Confidence Facts with admitted structure
Candidates to create Candidate-associated Score Observations.
_Avoid_: Structure prediction, confidence recomputation, positional zip

**Component Disposition**:
The resolved decision that includes, excludes, or requires normalization of one
observed structure component, together with the exact reason and residue
identity known at the residue-axis seam.
_Avoid_: PDB record name, HETATM-is-ligand rule, downstream guess

**Candidate-associated Scientific Value**:
A derived scientific value that carries an exact Candidate Data Reference for
its subject. Collection order never establishes the association.
_Avoid_: Parallel list, positional zip, unlabeled annotation

**Residue Track**:
A value series aligned to the protein residue layout, with explicit validity and
masking semantics for each position.
_Avoid_: Raw array, token vector, residue metadata

**PDB String**:
The canonical text representation used to exchange protein structures at
Workbench boundaries.
_Avoid_: Coordinate tensor, provider-native structure object

## Execution and Evidence

**Result Identity**:
The canonical identity of a reproducible Node result, derived from resolved
stable scientific and execution IDs, normalized inputs, parameters, and
effective randomness. CPU/GPU device choice and its accepted tiny numerical
variation do not split Result Identity or Cache identity.
_Avoid_: Cache path, Run ID, Node Instance ID, arbitrary hash

**Typed Output**:
The admitted ordered values published for one exact output Port, retaining
their nominal Port Type, content identity, Result Identity, and producer
provenance independently of storage representation.
_Avoid_: Artifact, Cache entry, provider payload

**Node Execution Attempt**:
The record of one scheduled Node Instance outcome, including an execution
satisfied entirely by Cache replay.
_Avoid_: Operation Attempt, Engine Invocation, provider call

**Operation Attempt**:
One actual run of a Node Type implementation after Cache miss or bypass, which
may contain zero, one, or several Engine Invocations.
_Avoid_: Node Execution Attempt, composite provider call

**Engine Invocation**:
One actual entry into a declared scientific engine seam. Normal execution
records exactly one terminal fact for every invocation that starts; an
interrupted process is not reconstructed on restart. An already-known actual
device may be retained as non-gating provenance.
_Avoid_: Readiness check, Cache replay, outer operation summary

**Run Evidence Ledger**:
The ordered durable source of typed run facts from which the manifest and
lifecycle event stream are projected. It is rooted by `workflow_commit_id` and
stores minimum scientific and causal evidence without derived digest hierarchy.
_Avoid_: Provider log, mutable details map, independent manifest writer

**Node Outcome Publication**:
The all-or-nothing durable conclusion of one Node Execution Attempt, relating
its terminal outcome to any published Typed Outputs and Artifacts.
_Avoid_: Operation Attempt terminal, Projection refresh, Cache write

**Run Closure**:
The normal terminal conclusion of a Run after every Node disposition and every
required Selection conclusion is closed. Restart instead records one honest
`interrupted` Run terminal without inventing missing internal outcomes.
_Avoid_: Worker exit, restart marker, last Node completion

## Verification and Release

**Acceptance Campaign**:
The single serial run that builds one clean candidate and executes all canonical
real-Provider and source-bound tiers once with one Execution Profile.
_Avoid_: Qualification, Certification Generation, retryable campaign

**Execution Profile**:
The private local mapping of Environment Configuration paths and remote
transport policy used to execute one Acceptance Campaign.
_Avoid_: Workflow parameters, manifest paths, shell-state reconstruction

**Acceptance Result**:
The retained result of one canonical tier after its scientific assertions pass
in the current Acceptance Campaign. Failed or interrupted diagnostic output is
not an Acceptance Result.
_Avoid_: Qualification Result, Certification Result, promoted evidence
