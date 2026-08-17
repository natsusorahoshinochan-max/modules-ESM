# Acceptance Evidence follow-up audit

Date: 2026-08-17

Status: implementation complete; real Provider Qualification pending a clean
candidate and configured Execution Profile

Authority: [redesign-switch-1.md](./redesign-switch-1.md),
[codebase-redesign.md](./codebase-redesign.md), and the repository
`AGENTS.md`

This document records the remaining problems found after the lightweight
Acceptance Evidence migration. It is an implementation checklist, not a new
architecture. Fixes must close the listed contracts with the smallest direct
change and must not create another Evidence system, validation layer, lifecycle
framework, or compatibility path.

## Non-negotiable requirements

1. **Scientific correctness is first.** Node Types, Methods, Binding identity,
   units, shapes, residue mappings, masking, randomness, lineage, provenance,
   readiness, Engine Invocations, Typed Values, and Artifacts must retain their
   specified meaning. A green infrastructure test cannot compensate for a
   weakened scientific assertion.
2. **Use the project trust model.** This is a trusted, single-user,
   loopback-only project. Users and developers use it as specified. There is no
   attacker and no requirement to handle use outside the documented workflow.
3. **Validate once at the contract-owning boundary.** After the public client or
   Service adapter has validated a value, downstream Evidence code copies it;
   it does not reinterpret or revalidate it.
4. **Do not add defensive programming for hypothetical misuse.** Do not add
   authentication, authorization, sandboxing, path-traversal handling, symlink
   scanning, secret-pattern fuzzing, malformed-provider recovery, provider
   cross-checks, retries, fallbacks, or catch-and-continue behavior.
5. **Reject brittle programming.** Tests must assert scientific and public
   outcomes, not AST shape, helper count, function length, private call order,
   or incidental module layout. Shared test infrastructure must have an
   explicit test-harness owner instead of being imported from another test
   module's private namespace.
6. **Keep the solution simple and robust.** Prefer a direct assertion or one
   small helper over a manager, policy object, state machine, registry, or
   generalized validator. Delete superseded paths instead of retaining aliases
   or compatibility layers.
7. **Fail fast on real local contracts.** Exact schema checks, durable writes,
   credential hygiene, and detection of accidental loss or mutation of retained
   Evidence remain required. These protect scientific evidence from local
   mistakes; they are not attacker-oriented hardening.

## Implementation resolution

- `SCI-1`: implemented in the canonical 3GB1 acceptance assertions; the
  authoritative `fresh-canonical-3gb1` Qualification remains pending.
- `EVD-1`: implemented with an exact installed ProteinMPNN single-load receipt
  assertion and fast positive/negative contracts; real Provider Qualification
  remains pending.
- `EVD-2`: implemented by retaining the same validated REST Catalog snapshot
  used by the ESMC gate; real Provider Qualification remains pending.
- `EVD-3`: closed by exact direct Run-directory and payload inventories.
- `CAM-1`: closed by rechecking every recorded result directory with the one
  Campaign directory digest.
- `VER-1`: closed by provider-free success and failure assembly probes through
  the complete verifier `run()` Interface.
- `DES-1`: closed by the shared `tests/acceptance/installed_harness.py` Module
  and three named source-bound scientific assertion functions.
- `DOC-1`: closed by the unified
  `PROTEIN_WORKBENCH_ACCEPTANCE_EVIDENCE_STAGING` name and corrected verifier
  and fifteen-tier documentation.

The provider-free contracts, routine backend verification,
deterministic acceptance, installed-package verification, frontend lint/build,
compileall, and diff checks pass. A Certification Generation must not begin
until all fifteen tiers have run through the configured Execution Profile and
produced passing Qualification Results from a clean candidate.

## Findings and repairs

### SCI-1 — canonical 3GB1 scientific and provenance acceptance is incomplete

Severity: high

Owner: `tests/test_fresh_remote_3gb1_v2.py::_assert_science`

The migrated test proves successful execution and several important scientific
relationships, but it does not yet preserve every assertion from the canonical
Qualification contract. The following incorrect outcomes can still pass:

- `node_dispositions` has the expected length but contains the wrong Node IDs;
- either remote Binding lacks its required passing Readiness fact;
- fixed alignments do not contain exactly one reference, or paired alignments
  do not contain ten references;
- fixed or paired alignments repeat subjects while keeping a total length of
  ten;
- exported Artifacts have the right candidate IDs but the wrong export Node,
  output port, PDB filename, media type, or media provenance.

Minimal repair:

- assert exact equality between Workflow Node IDs and disposition Node IDs;
- assert one passing Readiness fact for the remote ESM-3 Binding and one for the
  remote ESMFold2 Binding actually used by the Run;
- assert fixed reference cardinality `1`, paired reference cardinality `10`,
  fixed subject cardinality `10`, and paired subject cardinality `10`, together
  with the intended subject/reference mapping;
- assert the export Node/port, PDB filename, media type, and media provenance for
  every retained final-fold Artifact.

Keep these assertions in the canonical 3GB1 acceptance test. Do not create a
generic science validator or move scientific interpretation into the Evidence
writer.

### EVD-1 — installed ProteinMPNN does not enforce `load_count == 1`

Severity: high

Owners: `tests/acceptance/retained_evidence.py::require_retained_evidence` and
`tests/test_installed_backend_v2.py::_require_configured_installed_evidence`

The session observer writes the measured load count, but the installed outer
gate only checks that `model-lifecycle.json` exists. A receipt with
`load_count: 0` or `load_count: 2` currently satisfies the generic Evidence
contract, even though gate-wide single loading is an explicit requirement.

Minimal repair: keep `require_retained_evidence()` limited to the common file
schema. In the installed ProteinMPNN outer gate, directly assert the exact JSON
receipt:

```json
{"model":"proteinmpnn","load_count":1}
```

Add a small negative regression for an incorrect count. Do not add a generic
lifecycle validator, release-policy enum, object identity map, or state machine.

### EVD-2 — REST ESMC retains the wrong Catalog source

Severity: high

Owner: `tests/test_installed_backend_v2.py::test_installed_biohub_esmc_gate`

The gate fetches and validates the installed server's Catalog and uses it to
select and interpret the ESMC Binding. Retention then discards that snapshot and
writes `SOURCE_CATALOG`. Even when the two documents are equal, the retained
Catalog is not the document observed by this installed acceptance Run.

Minimal repair: preserve the already-validated Catalog snapshot returned by
the installed REST client and pass its canonical bytes to the REST Evidence
adapter. Do not fetch it again, compare providers, or introduce a third writer.

This finding does **not** apply to `public-protocol.json`. The source-process
`PublicProtocolAcceptanceClient` uses the source public protocol as its actual
contract owner when constructing and validating this REST exchange. Retaining
that client contract is correct; fetching and revalidating the server's
published copy would duplicate protocol proof.

### EVD-3 — the unique Evidence schema is exact only at its root

Severity: medium

Owner: `tests/acceptance/retained_evidence.py::require_retained_evidence`

The root inventory is exact, but each `runs/<label>/` directory is checked only
for the presence of required entries. The contract currently accepts:

- a nested legacy file such as `manifest.json`, `run-index.json`, or
  `checksums.sha256`;
- an unexpected file beside the six Run entries;
- a value or Artifact payload that is not referenced by
  `typed-values.json` or `artifacts.json`.

Minimal repair:

- compare the direct Run-directory inventory with the exact six entries:
  `projection.json`, `events.json`, `typed-values.json`, `artifacts.json`,
  `values`, and `artifacts`;
- compare each payload directory's direct file set with the payload paths
  referenced by its JSON inventory;
- add parameterized RED fixtures covering one nested legacy file and one orphan
  payload. The existing root-level `workflow.json` RED case is not sufficient.

These are explicit schema assertions. Do not recurse through arbitrary files,
inspect file contents for secrets or paths, or add symlink/traversal defenses.

### CAM-1 — the Campaign records a directory digest but does not enforce it

Severity: medium-high

Owner: `scripts/acceptance_campaign.py::_assert_candidate`

`_attach_evidence()` records `verification_result` and
`evidence_bundle_digest`, but later candidate checks and completion checks use
only the attempt outcome. A completed Qualification result can be deleted or
modified and Certification can still begin. A completed Certification result
can likewise be deleted or modified while Campaign status remains passed.

Minimal repair: in `_assert_candidate()`, for each completed attempt with a
retained verification result:

1. resolve the recorded result directory under the expected Campaign result
   root;
2. require that directory to exist;
3. recompute it with the existing `_directory_digest()`;
4. require equality with the recorded digest.

Add regressions for deleting and modifying a completed result directory before
Certification/status evaluation. Reuse the one Campaign directory digest; do
not add per-file manifests, secondary checksums, or a second integrity owner.

### VER-1 — final Evidence assembly lacks a provider-free wiring test

Severity: medium

Owner: `scripts/verify_backend.py::run`

The verifier creates staging, runs pytest, writes `tier-result.json`, and copies
the Evidence tree to the final result directory. Existing provider-free tests
do not call the full path with `retain_evidence_bundle=True`. A wiring regression
between staging, JUnit interpretation, tier-result creation, and `copytree`
would therefore be discovered only by an expensive real Qualification.

Minimal repair: add one provider-free verifier-wiring test using a small probe
tier. Assert that the final result contains the exact minimal Evidence tree and
`tier-result.json`, and that a failing pytest result is not reported as passed.
This test verifies verifier assembly only; it must not replace or weaken any
real Provider acceptance gate.

### DES-1 — acceptance test organization retains avoidable refactor coupling

Severity: medium maintainability risk

Owners: `tests/test_fresh_source_bound_acceptance_v2.py`,
`tests/test_fresh_remote_3gb1_v2.py`, and `tests/test_installed_backend_v2.py`

Two fresh acceptance files import the private `_run_external_acceptance()`
helper from `test_installed_backend_v2.py`. A test file is therefore acting as a
private infrastructure module. Renaming or reorganizing an unrelated installed
test can break fresh Qualification without changing a public or scientific
contract.

The source-bound `_assert_science()` also contains three large scenario
branches. Changes for 1PGA, 2EMO, and 5G53 converge on one long function even
though their scientific assertions are independent.

Minimal repair:

- move the existing external-run function, unchanged in responsibility, to one
  explicitly named module under `tests/acceptance/` and update its three
  callers;
- split `_assert_science()` into three named scenario functions selected by one
  short dispatch;
- do not introduce a harness class, plugin framework, strategy objects, or a
  generic scientific assertion DSL.

The narrow test-only lifecycle observers that count ProteinMPNN loads and prove
2EMO release order are accepted. They observe facts unavailable in public
events and are not AST/call-shape assertions. Keep them small and local; do not
generalize them into a production observer interface.

### DOC-1 — design documents and names contain stale scope statements

Severity: low

Owners: `docs/redesign-switch-1.md`, `docs/backend-verification.md`, and the
Evidence staging configuration name

`redesign-switch-1.md` requires deletion of the AST selector but later says not
to modify `scripts/verify_backend.py`. The intended rule is that the verifier
remains the single shallow owner while receiving the minimal staging and copy
wiring; it is not an absolute prohibition on edits.

Several names still describe the old installed/fresh split:

- the former fresh-only staging name served all retained tiers and has now been
  replaced by `PROTEIN_WORKBENCH_ACCEPTANCE_EVIDENCE_STAGING`;
- the fast contract module docstring says "installed" only;
- `backend-verification.md` says every installed tier retains the schema even
  though all fifteen acceptance tiers use it.

Minimal repair: update the documents and rename the staging variable across all
current producers, consumers, and tests in one change. Do not preserve the old
name as an alias.

## Confirmed non-findings

The following were examined and must not be turned into new work:

- installed ProteinMPNN gate-wide model reuse is an explicit contract, not a
  cache bug;
- using the source public-protocol bundle in the REST ESMC client is consistent
  with validate-once and is not Catalog source substitution;
- exact direct-directory inventory and Campaign digest rechecking are allowed
  local-contract checks, not adversarial hardening;
- the current small lifecycle observers are sufficient; no resident-model
  framework or release-policy state machine is required;
- mocks or provider-free probes may test writer/verifier wiring, but cannot
  replace authoritative real-Provider Qualification.

## Repair order

1. Close `SCI-1`; scientific acceptance must be authoritative before Evidence
   mechanics are considered complete.
2. Close `EVD-1` and `EVD-2`; lifecycle and Catalog provenance must describe the
   actual accepted execution.
3. Close `EVD-3` and `CAM-1`; enforce the one schema and the one Campaign digest.
4. Close `VER-1` with a seconds-level wiring test.
5. Close `DES-1` and `DOC-1` with direct moves, splits, and renames only.

After each repair, run the smallest affected provider-free tests first. Then
run the repository-required backend gates. Real Provider Qualification remains
mandatory for scientific/provider changes and must be launched through the
Execution Profile.

## Exit criteria

This follow-up is complete only when:

- canonical 3GB1 rejects every scientific/provenance mismatch listed in
  `SCI-1`;
- installed ProteinMPNN rejects any lifecycle receipt other than the exact
  single-load fact;
- REST ESMC retains the Catalog snapshot actually returned by its validated
  installed REST exchange;
- every retained Run directory and payload inventory matches the unique schema
  exactly;
- Campaign candidate/status checks reject missing or changed completed result
  directories using the existing directory digest;
- the final verifier Evidence assembly has a fast provider-free contract test;
- fresh acceptance tests no longer import private infrastructure from another
  test module;
- design documents and configuration names describe the unified current
  system;
- no fix adds a compatibility path, secondary validator, security scan,
  generalized lifecycle framework, fallback, or speculative abstraction.
