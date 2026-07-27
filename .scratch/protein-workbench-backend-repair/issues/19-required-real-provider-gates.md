# 19 — Run required real-provider gates without green skips

**What to build:** An acceptance operator can distinguish provider readiness from verified execution and obtain durable local-real and provider-specific evidence for every required scientific boundary.

**Blocked by:** 18 — Prove deterministic backend acceptance through REST and WebSocket.

**Status:** ready-for-agent

- [ ] Required local-real and provider-specific gates run through the documented project environment and installed-package contract where applicable.
- [ ] ESM3 prompt/output, structural alignment/TM-score, ProteinMPNN design/scoring, folding, and required local subprocess behavior are covered at the narrowest meaningful live seam.
- [ ] Each gate records provider/model identity, readiness, actual call count or call summary, effective seed, Cache decision, and terminal result.
- [ ] A missing required call, unavailable required provider, or skipped test leaves the gate failed or explicitly incomplete rather than green.
- [ ] JUnit, command transcript, environment summary, and redacted provider evidence are written to a dated run root.
- [ ] Historical Cache entries or PDB files cannot satisfy any current real-provider gate.
