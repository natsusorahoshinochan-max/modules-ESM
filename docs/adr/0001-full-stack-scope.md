# Full-stack scope for initial implementation

The first implementation delivers the full module system, type system, execution engine,
workflow persistence, all modules listed in the architecture, and a node-based graphical
user interface. Users build and run workflows through a visual canvas rather than through
a Python API.

The frontend and backend are developed in interleaved iterations. Each core subsystem
(types → execution engine → modules) is built on the backend first, then immediately
surfaced in the UI before moving to the next subsystem. This ensures every backend
API decision is validated against real UI usage as early as possible.

## Supersedes

This ADR replaces the original backend-first decision. The original ADR deferred the UI
to avoid coupling the core engine to a specific frontend framework. That concern is
addressed by a clean FastAPI REST + WebSocket contract between frontend and backend:
the core engine has no knowledge of the UI and remains testable in isolation.

## Frontend scope

In scope:
- Node editor canvas (add, delete, drag, connect, disconnect, group, copy, annotate)
- Parameter forms auto-generated from module YAML definitions
- ProteinPrompt editor with per-residue track editing
- Structure viewer (3D molecular visualization)
- Sequence viewer
- Candidate viewer with lineage browsing
- Score viewer with filtering and sorting
- Workflow save, load, and project management

Not in scope: mobile UI, multi-user collaboration, plugin marketplace, container isolation.
