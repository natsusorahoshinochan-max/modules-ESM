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

**Port**:
A named, typed input or output boundary of a Node Type.
_Avoid_: Slot, pin, socket

## Extension Language

**Module Package**:
A cohesive repository-owned extension unit that provides one or more Node Types,
their public Definitions, executable bindings or Adapters, and contract tests.
_Avoid_: Plugin, single node, module directory

**Node Definition**:
The YAML public contract that declares a Node Type's identity, Ports, parameters,
and user-visible metadata. Each Node Type owns exactly one Node Definition.
_Avoid_: Python definition, implementation metadata, JSON schema

**Adapter**:
The translator that converts a provider, model, runtime, or deployment mode
into Workbench inputs, outputs, errors, and provenance without changing the
Node Type's scientific meaning.
_Avoid_: Node Type, Execution Binding, provider name

**Execution Binding**:
The executable association of one Node Type with one Method and one Adapter or
factory. It owns execution availability while the Node Definition remains
independent of the current environment.
_Avoid_: Node Definition, Adapter, provider name

**Module Package Registration**:
The single explicit object exported by a Module Package to contribute Node
Types, executable bindings, Metric Definitions, and availability information.
_Avoid_: Import side effect, per-node registration call, recursive discovery

**Availability**:
The startup-resolved state describing whether an Execution Binding can execute
in the current environment and, when it cannot, the structured reason.
_Avoid_: Discovery failure, disabled node, import error

**Contract Test Kit**:
The shared conformance suite used by maintainers to verify that a Module Package
obeys the extension, execution, data, and provenance contracts.
_Avoid_: Package-specific smoke tests, manual checklist

## Scientific Data and Scoring

**ProteinPrompt**:
A residue-aligned, multi-track specification containing sequence, structure,
secondary-structure, accessibility, function, and masking information.
_Avoid_: Prompt object, ESM input, multi-track input

**Candidate**:
A generated or transformed protein sequence or structure with stable identity,
lineage, and provenance.
_Avoid_: Result, output sample, generation

**Candidate Collection**:
An ordered collection of Candidates that flow together through evaluation and
selection operations.
_Avoid_: Batch, result list, candidate set

**Metric Definition**:
The canonical scientific meaning of a measured quantity, including its value
shape, unit, direction, range, granularity, and aggregation semantics.
_Avoid_: Score ID, output field, display label

**Method**:
The exact algorithm or model variant used to perform a Node Type or observe a
Metric, including the identity needed to interpret and reproduce its result.
_Avoid_: Metric, provider, arbitrary implementation

**Score Observation**:
A value that binds one Candidate to one Metric Definition and one Method.
_Avoid_: Bare score, score ID/value pair, evaluation result

**Score Collection**:
A collection of Score Observations consumed by comparison, filtering, and
selection Node Types.
_Avoid_: Score set, metric bundle, evaluation result

**Utility Transform**:
An explicit, versioned mapping from one Metric and Method's canonical value to
a dimensionless `[0, 1]` value suitable for multi-Metric selection.
_Avoid_: Implicit normalization, dataset-relative scaling, raw score weight

**Structure Alignment**:
A residue-mapped structural superposition whose provenance and aligned residues
are shared by downstream structural Metrics.
_Avoid_: Superimposition result, structural match

**Residue Track**:
A value series aligned to the protein residue layout, with explicit validity and
masking semantics for each position.
_Avoid_: Raw array, token vector, residue metadata

**PDB String**:
The canonical text representation used to exchange protein structures at
Workbench boundaries.
_Avoid_: Coordinate tensor, provider-native structure object
