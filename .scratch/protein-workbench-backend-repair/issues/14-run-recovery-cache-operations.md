# 14 — Expose run recovery and Cache operations to backend clients

**What to build:** A backend client can inspect, recover, and deliberately recompute a run through stable project/run-scoped APIs without reading or deleting files directly.

**Blocked by:** 13 — Cancel and clean up active runs honestly.

**Status:** ready-for-agent

- [ ] Run status and output APIs retrieve the requested project/run manifest and artifacts rather than the newest file by modification time.
- [ ] Output responses preserve stable Candidate-to-artifact mapping and expose safe relative artifact references.
- [ ] A client can retry or force-rerun a selected Node according to documented dependency semantics.
- [ ] A client can list and clear Cache entries for one Node or the whole project.
- [ ] Recovery actions record their effective seeds, Cache decisions, and resulting Node states in the run manifest.
- [ ] Unknown, mismatched, or non-contained project/run/Node identifiers fail safely with structured errors.
