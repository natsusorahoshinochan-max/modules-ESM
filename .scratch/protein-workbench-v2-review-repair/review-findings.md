# Independent review findings

This is the durable input inventory for
[Restore Protein Workbench v2 acceptance after independent review](map.md).
It records the independently reproduced findings against
`21810a494fe66ed3d8cf7bb47c59a1c29d735dcf...fb9b79775ada74f21f389c632dba08e46d0db7d1`.
It is an input to wayfinding, not a repair specification and not evidence that
every proposed remedy is already decided.

## Blocking implementation findings

1. TM-score computation accepts alignment evidence whose coordinates are not
   bound back to the exact Candidate PDB bytes; a forged correspondence produced
   `TM-score=1.0` for coordinates that actually differed by 100 Å.
2. ProteinMPNN constraint authoring drops the source Residue Layout, so chain
   order can move a fixed position to another chain; residue-number gaps also
   create phantom positions and incorrect target lengths.
3. The structure-annotation package calls locked `mkdssp 4.6.1` without
   accessibility calculation, treats real coil `.` as missing, and rejects real
   PPII `P`.
4. Candidate values remain mutable across the extension seam; an implementation
   can mutate input content in place and retain the old Candidate identity.
5. ESM-3 rejects the legal 31.75 Å PAE bin center, paired generation drops
   coordinate conditioning, and direct ESMC permits an unverified injected
   client to emit exact Biohub identities.
6. Folding accepts an explicitly multi-chain ProteinSequence, sends only a
   concatenated sequence, and can publish a single-chain structure under the
   multi-chain parent's lineage.
7. Cancellation can race with scheduling; Cache publication can leave a
   permanently unusable provisional entry; standalone-artifact outputs can be
   cached and replayed despite an explicit prohibition.
8. Selection Objectives are validated globally rather than per consuming Node:
   legal independent branches are rejected while a zero-total consumer can pass
   compile and fail only after upstream execution.
9. Public-protocol and Port validation omit declared constraints including
   `uniqueItems`, type-sensitive `const`, exact pairwise evidence references,
   normalization fields, and complete ProteinPrompt track validation.
10. Presentation-only metadata enters Workflow Contract Locks, and a
    semantically unordered Produced Observation set changes digest when
    construction order changes.
11. SoluProt no-TM Readiness hashes and depends on the full-model sibling assets,
    violating independent Binding Readiness.
12. Multi-record FASTA input is silently concatenated into a new scientific
    sequence.
13. WebSocket replay framing is synthesized outside the durable Ledger and
    reuses a durable sequence/cursor with terminal events.

## Additional contract deviations

- Utility Transform parameters bypass the Environment Configuration boundary.
- Declared Metric decimal precision is not enforced.
- FrozenCatalog accepts Port Type identifiers that its public schema cannot
  publish.
- Production prompt authoring cannot construct common internal insertion
  layouts used by its own editing contract.
- Structure-to-sequence extraction silently chooses one residue name from
  contradictory atom records.
- A Protein-Sol Method descriptor contains workspace-location labels.

## Acceptance and evidence gaps

- The installed test environment injects ambient absolute `.pth` entries,
  including provider sources inside the current checkout, instead of proving a
  closed dependency installation.
- The deterministic installed canonical 3GB1 journey and installed zero-Core
  extension journey that once existed are absent from the final tree.
- Several installed local-provider gates construct internal services rather than
  traverse the closed REST and Run Event Stream transport.
- The retained Ticket 37 bundle is internally self-consistent, but its ignored
  checksum set lacks a tracked external anchor, its lineage/proof is validated
  by the same implementation that generated it, and the claimed wheel/sdist
  bytes are not bundled.
- The top-level v2 spec remains `ready-for-agent` while all 37 ticket files say
  `completed`.

## Defensive behavior requiring adjudication

- Derived Run additionally depends on the current mutable Workflow revision.
- A new Readiness proof is compared to a timestamp sampled before its checker
  ran and can be rejected as coming from the future.
- Global value-shape redaction rewrites legitimate scientific and entity IDs.
- Parameter-name token blacklists reject declared scientific fields.
- Provider and SoluProt integrity checks hash unrelated siblings or repeat full
  tree scans.
- Generic pairwise and ProteinMPNN Port contracts impose method-specific bans
  such as no self-comparison or no tied-position residue bias.
- The fresh-remote validator scans arbitrary JSON text for forbidden keywords
  after already checking structured identities.
- Retained JUnit summaries remove all testcase and failure-location detail.
- Private create/replace storage paths duplicate the same no-follow staged-write
  orchestration; the safety invariants are required, the duplication is not.

## Verification observed during review

- Routine: `659 passed, 30 deselected`.
- Deterministic acceptance: `8 passed`.
- Installed package: `3 passed`.
- Security/failure: `10 passed`.
- Local ESMFold2 contract: `5 passed`.
- `uv lock --check`, `uv pip check`, compileall, full-range
  `git diff --check`, and tracked-worktree cleanliness passed.
- Retained Ticket 37 checksums and offline validator passed for one Run and
  fifteen 71-residue PDB artifacts.
- No remote-provider gate was rerun during independent review.
