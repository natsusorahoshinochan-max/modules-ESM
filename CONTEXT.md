# Protein Workbench

A modular, node-based protein design and evaluation workbench for personal local use.
The system provides a stable module interface that lets developers add models, scoring
methods, and transformations without modifying the core engine.

## Language

**Module**: A self-contained unit of computation that declares typed input ports, output ports,
and configurable parameters, and implements a run() method. Modules are registered into the
system and become available for composition in workflows.
_Avoid_: Plugin, node implementation, model runner

**Workflow**: A directed acyclic graph of nodes (module instances with bound parameters)
connected by edges between compatible ports. A workflow is serializable to JSON and can be
saved and reloaded.
_Avoid_: Pipeline, recipe, protocol

**Node**: A single instance of a module in a workflow, with concrete parameter values
and connections to other nodes. Distinguished from Module: a Module is the reusable
definition, a Node is one use of it with specific settings.
_Avoid_: Block, step, task

**Port**: A named, typed endpoint on a module. Input ports receive data; output ports produce
data. Ports have a type ID string (e.g., protein.sequence) that the engine uses to check
compatibility before connecting.
_Avoid_: Slot, pin, socket

**ProteinPrompt**: The central multi-track data object that holds a user's ESM-3 input:
target residue layout, sequence track, structure coordinate track with per-residue
visibility, secondary structure track, SASA track, function annotations, and an optional
residue map from a template structure. Every track is aligned to a single target layout
and each track's per-residue state (specified / masked / visible) is independent.
_Avoid_: Prompt object, ESM input, multi-track input

**Candidate**: A single generated sequence or structure produced by a model module, along
with lineage (parent candidate IDs) and metadata. Candidates flow through the workflow and
are collected into CandidateCollections.
_Avoid_: Result, output sample, generation

**ScoreCollection**: A set of score entries, each tying a numeric value to a
score ID and a list of subject references (structures, sequences). Produced by scoring
modules and consumed by selection modules.
_Avoid_: Score set, metric bundle, evaluation result

**StructureAlignment**: The result of superimposing two protein structures: a
sequence-aware per-residue mapping with PDB-label provenance, aligned residue
indices and CA coordinates, per-residue distances, reference/mobile lengths, a
rotation matrix, a translation vector, RMSD, and coverage. Produced by
structure.align and consumed by TM-score and RMSD modules so that multiple
scorers reuse and reproduce the same alignment.
_Avoid_: Superimposition result, structural match

**DSSP**: Secondary structure assignment program. The workbench calls mkdssp as a
subprocess (v4.6.1 at /opt/homebrew/bin/mkdssp).
_Avoid_: Secondary structure assignment, stride

**PDB String**: The canonical structure exchange format. All three providers (ESM SDK,
ProteinMPNN, SimpleFold) can read and write PDB text. The workbench uses PDB strings
inside ProteinStructure rather than raw coordinate arrays.
_Avoid_: mmCIF, binary CIF, coordinate tensor

**YAML ModuleDefinition**: Each module declares its identity, ports, and parameters
in a definition.yaml file. The module registry loads and validates these definitions
at startup.
_Avoid_: Inline Python definition, JSON schema

**Execution Engine**: The subsystem that topologically sorts a workflow DAG, executes
nodes in dependency order, passes outputs to downstream inputs, handles caching, and
manages node states (idle to queued to running to completed / failed / cancelled).
Execution is strictly serial: one node at a time, in topological order. When a node
fails, its direct downstream dependencies are marked blocked; unrelated branches can
still complete.
_Avoid_: Scheduler, runner, orchestrator

**Module Registry**: The subsystem that holds all known modules (by module ID) and
resolves module lookups when workflows are loaded or nodes are instantiated. Each
module subpackage exposes a register(registry) function. discover_modules() imports
every subpackage under modules/ and calls its register(). The registry is fully
populated at startup and never modified at runtime.
_Avoid_: Plugin registry, module catalog, module index

**Type Registry**: The subsystem that maps type ID strings to their definitions,
allowing the engine to check port compatibility without understanding the internal
structure of the data.
_Avoid_: Type catalog, schema registry

**Cache**: Content-addressed storage of successful node outputs. The cache key is a
hash of (module_id, module_version, input hashes, normalized parameters, seed). Cached
results are loaded directly without re-executing the node. Cache is invalidated only by
manual deletion; there is no TTL or staleness check in the first version.
_Avoid_: Memoization store, result cache, checkpoint
