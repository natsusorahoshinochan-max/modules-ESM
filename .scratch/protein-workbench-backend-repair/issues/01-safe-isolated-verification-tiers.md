# 01 — Make backend verification safe, isolated, and tiered

**What to build:** A maintainer can run the routine backend regression suite without touching user-visible projects, calling remote providers, or loading heavy models, while explicitly requested live gates produce unambiguous evidence that the required work actually ran.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Routine backend tests use isolated temporary project, Cache, output, and run roots and leave the configured production roots unchanged.
- [ ] The default test command excludes live-provider and slow/heavy-model acceptance tests.
- [ ] Each verification tier has an explicit command and reports its tier clearly in the result.
- [ ] A required live-provider gate cannot pass through a skip or through provider-readiness checks alone.
- [ ] The first scientific repair has a deterministic failing reproduction that runs inside the project environment.
