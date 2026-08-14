# 03 — 通过 immutable value objects 发布大型 Typed Outputs

**What to build:** 让合法 Typed Outputs 不再内嵌于 Ledger 或 Run Projection，而是由 committed descriptors 指向 Project-scoped immutable values；用户可以按 Run、Node、Port 和 value index 精确获取单个 canonical value。

**Blocked by:** 02 — 将 Run Evidence Ledger 切换为原子 transactions

**Status:** ready-for-agent

- [ ] admitted canonical values 在 Ledger commit 前作为 content-addressed objects durable，Port Value Manifest 保留顺序、Port Type、aggregate digest、value count、per-value digest 与 size。
- [ ] successful Node publication transaction 只包含 bounded Typed Output descriptors，不包含 embedded canonical values。
- [ ] Run Projection 不再公开 `values`；single-value retrieval 严格 Run-scoped，并返回 exact canonical bytes、size、individual digest、aggregate Port digest、Port Type 和 manifest identity。
- [ ] 当前 frontend 能从 descriptor 选择并获取单个值；WebSocket 与 lifecycle events 不携带 scientific values。
- [ ] 使用真实注册 ESM-3 Port codecs 的 291-residue、2-sample、reconstruction 与两组 PAE fixture 可完整发布和逐值取回。
- [ ] declared `num_samples=100` 的 provider-free fixture 证明 Ledger transaction size 只随 descriptor metadata 增长，不随 scientific bytes 增长。
- [ ] embedded/reference dual path 与 superseded embedded-output producers、consumers、fixtures 和 examples 已一起删除。
- [ ] 当前 ticket 的 focused object-store、manifest、public protocol、frontend 与 large-output tests 通过。
- [ ] 标记完成前，重跑 Tickets 01–03 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [ ] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。
