---
status: accepted
---

# Full-stack product boundary

Protein Workbench consists of a backend-owned scientific runtime and a graphical
client for authoring Workflows, starting Runs, and inspecting scientific outputs
and evidence. The frontend communicates only through the current versioned public
protocol. Core runtime and scientific modules have no dependency on the UI and
remain testable through their owning interfaces.

Scientific contracts are determined by the authoritative provider specifications,
ADRs, Node Definitions, Method and Metric Definitions, Port Type Definitions, and
their contract-owning boundaries. UI behavior may shape interaction and transport
ergonomics but cannot define or change scientific meaning, units, shapes, residue
identity, masking, randomness, lineage, provenance, or evidence.

The graphical client is one presentation of the current public contracts. Product
feature scope belongs in product design and implementation plans rather than in
this architecture decision.

The existing `frontend/` source tree is a retired implementation and is not a
current product client or verification target. The backend and public protocol
remain independently deployable while its replacement is designed. Any future
graphical client remains a separate public-protocol consumer and does not become
a scientific or runtime contract owner.
