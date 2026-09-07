---
status: accepted
---

# Full-stack product boundary

Protein Workbench currently consists of a backend-owned scientific runtime and
its versioned public protocol. A future graphical client may author Workflows,
start Runs, and inspect scientific outputs and evidence only through that public
protocol. Core runtime and scientific modules have no dependency on the UI and
remain testable through their owning interfaces.

Scientific contracts are determined by the authoritative provider specifications,
ADRs, Node Definitions, Method and Metric Definitions, Port Type Definitions, and
their contract-owning boundaries. UI behavior may shape interaction and transport
ergonomics but cannot define or change scientific meaning, units, shapes, residue
identity, masking, randomness, lineage, provenance, or evidence.

A graphical client is one possible presentation of the current public contracts.
Its product feature scope belongs in product design and implementation plans
rather than in this architecture decision.

The retired `frontend/` source tree has been deleted and is not a current product
client or verification target. The backend and public protocol remain independently
deployable while a replacement is designed. Any future graphical client remains a
separate public-protocol consumer and does not become a scientific or runtime
contract owner.
