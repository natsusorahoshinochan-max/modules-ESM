# Backend verification tiers

Backend verification is run through one public command so that the selected tier,
interpreter, isolated roots, and final result are visible in the transcript:

```bash
.venv/bin/python scripts/verify_backend.py <tier>
```

Every invocation creates temporary, distinct project, Cache, output, and run roots.
Configured production roots are replaced only in the child verification process and
are not written. Plain `.venv/bin/pytest` uses the same isolation policy and defaults
to the routine marker expression.

## Available tiers

| Tier | Command | Contract |
| --- | --- | --- |
| Routine backend regression | `.venv/bin/python scripts/verify_backend.py routine` | Fast deterministic tests only; excludes acceptance, remote providers, local providers, heavy models, and intentionally red reproductions. |
| Scientific reproduction | `.venv/bin/python scripts/verify_backend.py scientific-repro` | Runs deterministic pre-repair reproductions. SCI-001 is expected to exit nonzero until ticket 02 repairs the behavior. |
| Mocked Workflow | `.venv/bin/python scripts/verify_backend.py mocked-workflow` | Runs the current deterministic 3GB1 Workflow tests with provider boundaries replaced by fixtures. |
| Local provider | `.venv/bin/python scripts/verify_backend.py local-provider` | Runs non-heavy installed binaries and requires both zero skips and provider-call evidence. |
| Heavy local model | `.venv/bin/python scripts/verify_backend.py heavy-model` | Explicitly loads slow local models and requires both zero skips and provider-call evidence. |
| Live remote provider | `.venv/bin/python scripts/verify_backend.py live-provider` | Makes remote provider calls and requires both zero skips and provider-call evidence. Readiness alone cannot satisfy this gate. |

Installed-package and fresh remote 3GB1 acceptance are intentionally not placeholder
tiers here. Their commands become valid only when tickets 17 through 20 add the
installed artifact and source-bound evidence contracts.

Each command prints `BACKEND VERIFICATION TIER` before pytest starts and
`BACKEND VERIFICATION RESULT` after JUnit and provider evidence are checked.
Provider tiers fail when a required provider is unavailable; they never turn missing
provider work into a passing skip.

## Focused pytest arguments

For infrastructure diagnosis, paths may be supplied after `--`; the selected tier's
marker policy still applies:

```bash
.venv/bin/python scripts/verify_backend.py routine -- tests/test_server_projects.py
```

This is also the supported way to retain the isolation and result transcript while
running a focused test.
