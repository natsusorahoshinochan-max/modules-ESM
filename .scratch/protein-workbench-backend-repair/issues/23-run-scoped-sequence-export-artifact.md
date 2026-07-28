# 23 — Materialize sequence exports in each run namespace

**What to build:** Every workflow run receives its own sequence-export artifact, even when an identical prior run is eligible for Cache reuse, so clients never receive a stale path owned by another run.

**Blocked by:** 22 — Preserve canonical secondary-structure intent in the final layout.

**Status:** completed

- [x] Two identical workflows with distinct run IDs each return a sequence-export artifact inside the correct run namespace.
- [x] Both exported files exist, contain the expected sequence, and have independently verifiable artifact metadata.
- [x] A Cache hit may reuse content but never returns the prior run's path or leaves the current run's artifact absent.
- [x] Run containment, traversal rejection, and symlink protections remain effective for the materialized export.
- [x] Before ticket 24 starts, all completed repair checks plus the routine, deterministic-acceptance, and installed-package gates pass; only explicitly deferred findings may remain red, and no unknown failure is accepted.

## Verification evidence

- `export.sequence.file_path` now uses the shared `file.path` artifact type under the semver-major `2.0.0` Node Definition, so the Executor's artifact-aware Cache contract does not publish run-owned absolute paths.
- Two identical runs use the same content-addressed Cache key but independently execute the export, return `outputs/<run-id>/out.fa`, and produce the expected 37-byte FASTA with SHA-256 `fc0335349b5216471f859559c7a35670776bbba860962f34621d12c206b89e5b`.
- Each run manifest publishes the explicitly discriminated standalone artifact's Node, output Port, run-relative reference, size, and digest, and public recovery independently verifies the file before returning that metadata.
- The exporter writes through the shared owner-only, no-follow, exclusive-create storage primitive; focused traversal, symlink-parent, and hardlink tests pass.
- `repair-findings`: 2 passed / 2 known deferred failures. The secondary-structure and sequence-export findings are green; only the Ticket 24 SimpleFold staging and Tickets 25–26 manifest findings remain red.
- `routine`: 649 passed / 40 deselected / exit 0.
- `deterministic-acceptance`: 8 passed / 4 deselected / exit 0.
- `installed-package`: 3 passed / exit 0.
- No React frontend source or frontend test was inspected, modified, or executed.
