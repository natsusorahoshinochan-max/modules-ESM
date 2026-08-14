# 11 — 完成 current-generation cutover 与 provider-free 验收

**What to build:** 让整个当前 checkout 只暴露新的 Node Outcome Publication contract，并以完整 provider-free public journey 和 failure matrix 证明前十张 tickets 在组合状态下仍然成立。

**Blocked by:** 03 — 通过 immutable value objects 发布大型 Typed Outputs；04 — 让 Artifacts 共享 immutable object store；05 — 让 Ledger 掌握 Result Identity，并将 Cache 改为引用；06 — 准确记录 Operation、publication 与 Result Identity 失败；07 — 公开 evidence unavailable，并精确排序 cancellation；08 — 原子提交 Selection conclusions 与 Run Closure；09 — 从 durable prefix 恢复真实 Run 状态；10 — 只回收无引用 immutable objects

**Status:** ready-for-agent

- [ ] backend、public protocol、frontend、Contract Test Kit、fixtures、examples、documentation 与 generated contract artifacts 全部使用 current-generation Ledger、Cache、manifest 与 public bundle contracts。
- [ ] superseded embedded values、sequential publication、random authoritative Artifact storage、old Cache payload、old error names、legacy readers、aliases、shims 和 dual paths 已删除。
- [ ] 完整 public Run journey 覆盖 Start Run、bounded Projection、single-value retrieval、Artifact retrieval、event replay/live events、Cancel Run 与 restart recovery。
- [ ] 完整 fault matrix 覆盖 typed-value object、Artifact object、Result Identity comparison、Ledger transaction durability、Projection materialization、Cache publication 和 Run Closure。
- [ ] 291×2 双 PAE regression、declared 100 samples、byte-for-byte retrieval、digests、Candidate identities、lineage、Prediction Keys、confidence facts 与 PAE shapes 全部通过。
- [ ] trust-model review 确认没有 hypothetical malformed Provider handling、重复 contract validation、repair、cross-check、fallback、catch-and-continue 或 undocumented retry。
- [ ] 当前 ticket 的 integration、Contract Test Kit 与 current-generation cutover tests 通过；本 ticket 不调用真实 Provider。
- [ ] 标记完成前，重跑 Tickets 01–11 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [ ] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。
