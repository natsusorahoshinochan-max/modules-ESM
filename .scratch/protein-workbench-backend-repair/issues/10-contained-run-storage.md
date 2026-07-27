# 10 — Contain every project and run in an isolated storage namespace

**What to build:** Backend execution treats project and run identifiers as contained namespaces so API-controlled paths cannot escape configured roots or collide with another run.

**Blocked by:** 09 — Reject invalid Workflows before creating a run.

**Status:** completed

- [x] Project IDs, run IDs, Node IDs, uploaded names, requested artifact names, and output paths are validated before filesystem access.
- [x] Absolute paths and traversal attempts outside configured roots are rejected without creating or modifying external files.
- [x] Temporary work, outputs, logs, and other mutable execution state are namespaced by run ID.
- [x] Two different runs cannot resolve to the same mutable temporary or output path.
- [x] Valid project and run paths remain compatible with the established hybrid project-storage contract.
