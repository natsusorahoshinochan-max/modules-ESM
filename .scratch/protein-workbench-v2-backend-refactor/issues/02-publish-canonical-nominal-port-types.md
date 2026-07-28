# 02 — Publish canonical nominal Port Types

**What to build:** A client can query exact, versioned nominal Port Types from the v2 Catalog Snapshot and rely on their validators, canonical codecs, content digests, and contract identities to mean the same thing in source and installed deployments.

**Blocked by:** 01 — Freeze the v2 public protocol contract.

**Status:** implementation-complete-awaiting-controller-gate

- [x] Every Port Type has an exact ID, version, closed canonical descriptor, contract digest, runtime validator, canonical codec, and content-digest procedure.
- [x] Callable behavior is represented by explicit stable behavior ID/version and immutable declaration parameters, never by object repr, memory address, source path, source text, or bytecode.
- [x] Catalog Snapshot exposes stable Port Type contracts without exposing private Python implementation details.
- [x] Direct connection compatibility accepts only the same Port Type ID/version; unknown types, structural similarity, subtyping, implicit coercion, and version ranges fail closed.
- [x] Codec round-trip and content-digest tests cover complete valid values, malformed values, non-canonical values, and the requirement for explicit conversion Nodes.
- [x] Golden and differential vectors prove the required ordering, default materialization, Unicode, I-JSON, RFC 8785, and SHA-256 rules, including rejection of negative zero, NaN, Infinity, duplicate keys, and unversioned behavior.
- [x] Source-checkout and installed-artifact Catalog probes produce byte-identical Port Type descriptors and digests.

## Executor evidence

This status records executor completion only. Controller cumulative multi-ticket
acceptance is still required before Ticket 03 may start.

- Fixed review base: `916da90d55464f789e468d2b4dae69c78521e339`.
- Focused Port Type contract suite:
  `.venv/bin/pytest -q tests/test_port_types_v2.py` → `27 passed`.
- Routine backend gate:
  `.venv/bin/python scripts/verify_backend.py routine` →
  `723 passed, 44 deselected`; retained result
  `verification-results/routine/20260728T223203.684126Z-13554-1e2e4f96a0cfb567`.
- Deterministic acceptance gate:
  `.venv/bin/python scripts/verify_backend.py deterministic-acceptance` →
  `9 passed, 5 deselected`; retained result
  `verification-results/deterministic-acceptance/20260728T223335.885770Z-14124-20d927e3be7e0828`.
- Installed-package gate:
  `.venv/bin/python scripts/verify_backend.py installed-package` → `3 passed`;
  retained result
  `verification-results/installed-package/20260728T223421.715625Z-14263-c9548a8da09cd87c`.
  The installed-wheel probe compares exact Catalog bytes, every Port Type
  descriptor byte sequence and digest, and the installed API response against
  the source checkout.
- `compileall`, `pip check`, `uv lock --check`, and `git diff --check` passed.
  No standalone static type checker is installed/configured in the checkout, so
  this evidence does not claim a separate mypy/pyright result.
- Mandatory parallel Standards and Spec review initially identified incomplete
  nested/runtime invariant checks, public-semver drift, non-atomic Catalog
  publication, a tautological API digest assertion, and ProteinMPNN constraint
  drift. The executor added recursive I-JSON/semver checks, validation on every
  encode, startup-atomic Catalog publication, independent source/wheel/API
  comparisons, and one shared authoritative ProteinMPNN constraint validator.
  Both reviews then passed with no hard finding. Review retained only
  non-blocking design-smell observations about nominal identity data clumps and
  the legacy ProteinMPNN compatibility re-export.
