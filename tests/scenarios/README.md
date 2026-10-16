# Shared scenarios

These modules own inputs, assembly and expected relationships reused by more
than one test entry point. Tests import scenarios; scenarios never import
collectible tests. General operations remain in `tests/support` and do not
load scientific fixtures.

- `folding` assembles an explicit folding route. A supplied client replaces
  that route's tool boundary; `client=None` uses the configured real tool.
  `_write_local_runtime_fixture` roots contain dummy model files
  and are only for controlled readiness/translation tests, never real gates.
- `folding_outputs` reads the exact scenario outputs without judging success.
- `proteinmpnn_real` selects the configured real Provider and retains the
  source-bound generation/scoring scenario. It does not prove independent
  sequence/backbone evaluation; that requirement has its own module tests.
- `pairwise_scoring`, `structure_comparison` and `alignment_evidence` contain
  explicit contract fixtures and expected relationships for their owners.
- `source_bound` shares public-value reading, exact invocation checks and the
  1PGA relationship oracle. Sharing an oracle between controlled and real runs
  does not create two independent proofs of its assumptions.
- `workflow_stress` owns controlled tool behavior, scientific registrations,
  candidate reading and its compact report. Its callers choose the assembly
  explicitly. A report is emitted only after the owning assertions succeed.

`generate_workflow_stress_fixtures` is the maintenance source for
`tests/fixtures/workflow_stress/*.workflow.json`. Update source and generated
files together when contracts change. Regeneration and executable consistency
checks follow the repository's remote verification policy.
