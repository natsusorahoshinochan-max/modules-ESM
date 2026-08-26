# Known implementation gaps

This file records accepted current architecture that the implementation has not
yet reached. It is not a compatibility plan or an alternative contract.

## Automatic Module Package discovery

Normative decision: [ADR-0018](adr/0018-module-packages-and-startup-discovery.md)
requires startup to scan each immediate child directory under `modules/` and
consume exactly one explicit `package.py:MODULE_PACKAGE` registration object.

Current implementation gap:
[`protein_workbench_public/bootstrap.py`](../protein_workbench_public/bootstrap.py)
imports and enumerates the twelve current Module Package registrations explicitly.
Adding a conforming repository-owned Module Package therefore still requires
editing the composition root.

The gap is closed when:

- adding a conforming immediate-child Module Package requires no bootstrap edit;
- discovery scans only immediate package roots and never recursively searches for
  definitions;
- each discovered package exports exactly one `MODULE_PACKAGE` registration;
- malformed imports, duplicate stable IDs, missing required references, or
  unresolved factories fail startup atomically; and
- optional Provider dependencies remain lazy and Binding-scoped.

The current documentation cleanup records this divergence but does not change
runtime discovery.

## Stable Catalog and Workflow identity

Normative decisions: ADR-0026, ADR-0034, ADR-0036, and ADR-0037 use stable
contract IDs, one `workflow_commit_id`, and minimum scientific definition
snapshots. They do not use internal contract semver, inactive generations,
Contract Locks, descriptor digests, or parallel Workflow/Catalog/Plan digests.
When a current result-affecting definition changes without a new stable ID,
ADR-0031, ADR-0034, and ADR-0036 require an atomic cutover that clears or
isolates Cache entries written by the superseded definition.

Current implementation gap:

- Catalog declarations and lookup still use ID plus version;
- Workflow Nodes still persist Node/Binding versions and a complete Contract Lock;
- Commit, Plan, Result Identity metadata, examples, fixtures, Capability
  Inventory, and tests still carry version and digest fields;
- no stable-ID cutover mechanism yet makes superseded Cache entries unreachable;
- canonical 3GB1 still contains 166 version fields and 95 Contract Lock entries.

The gap is closed when every current producer, consumer, test, example, and
document uses stable IDs and the minimum definition snapshots together, with no
legacy reader, migration, alias, or dual path, and a result-affecting definition
change cannot replay Cache entries written by the superseded definition.

## Catalog scientific relationship gate

Normative decisions: ADR-0018 and ADR-0034 place the complete repository-owned
scientific relationship gate in build/test and keep runtime startup limited to
stable-ID uniqueness, required references, and implementation resolvability.

Current implementation gap: `core/catalog/builder.py` still recomputes both the
scientific relationship gate and descriptor/version/digest/dependency identity
checks on every startup. The gap is closed when build/test owns Candidate,
Observation, Metric, Port, residue-axis, dependency-closure, and codec-owner
checks, while runtime consumes the admitted typed registrations.

## Availability and Run-scoped Readiness

Normative decisions: ADR-0025, ADR-0029, and ADR-0041 make Availability
diagnostic only. Only a fresh Run-scoped Readiness conclusion may block Adapter
Provider entry.

Current implementation gap: `core/execution/node_attempt.py` still returns
`binding_unavailable` from the startup Availability snapshot before invoking
fresh Readiness. The gap is closed when Availability can be published to
Catalog, UI, and Ledger diagnostics but never suppresses Readiness or execution.

## Typed public output construction

Normative decisions: ADR-0034 and ADR-0042 require typed response, event, and
error constructors to guarantee the complete public wire shape before direct
serialization.

Current implementation gap: REST success, WebSocket events, and Structured Error
envelopes are still assembled as mappings and revalidated against the Bundle
Schema in the production emission path. The gap is closed only after complete
typed constructors and protocol tests replace that hot-path validation.

## Provider operability instead of installation identity

Normative decisions: ADR-0029, ADR-0032, ADR-0034, ADR-0041, ADR-0045, and
`provider-install-contract.md` remove Provider source/checkpoint/model hashes,
PEP 610, Git checkout, and source-tree identity gates. Readiness checks actual
operability only.

Current implementation gap: local ESM-3, ESMFold2, SimpleFold, ProteinMPNN, and
solubility routes still hash assets or source sets and still use PEP 610/Git
installation checks. The gap is closed when equivalent operable wheels,
containers, copied trees, and configured roots are admitted without a replacement
manifest, stat fingerprint, or content-proof cache.

## Environment Configuration ownership

Normative decisions: Environment Configuration contains external paths,
credentials, and endpoints only. Adapter-owned device, model labels, performance
policy, and other fixed constants do not round-trip through it.

Current implementation gap: configuration is still indexed by Binding version,
wrapped in `{"values": ...}`, and carries Adapter-owned constants that Readiness
recomputes. The gap is closed when the composition root validates external fields
once and Adapters own their fixed operational policy directly.

## Ledger and internal persistence

Normative decisions: ADR-0037 and ADR-0042 use `workflow_commit_id` as the single
execution root, retain minimum scientific and causal evidence, and do not require
internal metadata self-digests, repeated namespaces/kinds, exact closed fields,
or canonical JSON text.

Current implementation gap: Workflow/Plan/Readiness digests, attestation digest,
reducer recomputation, and strict internal codec admission remain. The gap is
closed when scientific value content identity is preserved but ordinary internal
metadata uses only fields needed for normal reading and causal transitions.

## Focused scientific test ownership

Normative decision: exact-set CTK and Capability Inventory locking are replaced
by focused Node/Binding tests, owner valid/invalid/round-trip tests for every
scientific Port codec, and real-Provider acceptance.

Current implementation gap: CTK still requires package-wide exact Node/Binding
and Port case sets, and Capability Inventory still locks full Catalog identity.
The four current local source-bound routes—`fresh-local-1pga`,
`fresh-local-2emo`, `fresh-local-canonical-3gb1`, and `fresh-local-5g53`—are not
part of this gap and must remain.
