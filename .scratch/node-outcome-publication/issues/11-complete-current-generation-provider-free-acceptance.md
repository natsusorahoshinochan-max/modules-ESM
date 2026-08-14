# 11 — 完成 current-generation cutover 与 provider-free 验收

**What to build:** 让整个当前 checkout 只暴露新的 Node Outcome Publication contract，并以完整 provider-free public journey 和 failure matrix 证明前十张 tickets 在组合状态下仍然成立。

**Blocked by:** 03 — 通过 immutable value objects 发布大型 Typed Outputs；04 — 让 Artifacts 共享 immutable object store；05 — 让 Ledger 掌握 Result Identity，并将 Cache 改为引用；06 — 准确记录 Operation、publication 与 Result Identity 失败；07 — 公开 evidence unavailable，并精确排序 cancellation；08 — 原子提交 Selection conclusions 与 Run Closure；09 — 从 durable prefix 恢复真实 Run 状态；10 — 只回收无引用 immutable objects

**Status:** completed

- [x] backend、public protocol、frontend、Contract Test Kit、fixtures、examples、documentation 与 generated contract artifacts 全部使用 current-generation Ledger、Cache、manifest 与 public bundle contracts。
- [x] superseded embedded values、sequential publication、random authoritative Artifact storage、old Cache payload、old error names、legacy readers、aliases、shims 和 dual paths 已删除。
- [x] 完整 public Run journey 覆盖 Start Run、bounded Projection、single-value retrieval、Artifact retrieval、event replay/live events、Cancel Run 与 restart recovery。
- [x] 完整 fault matrix 覆盖 typed-value object、Artifact object、Result Identity comparison、Ledger transaction durability、Projection materialization、Cache publication 和 Run Closure。
- [x] 291×2 双 PAE regression、declared 100 samples、byte-for-byte retrieval、digests、Candidate identities、lineage、Prediction Keys、confidence facts 与 PAE shapes 全部通过。
- [x] trust-model review 确认没有 hypothetical malformed Provider handling、重复 contract validation、repair、cross-check、fallback、catch-and-continue 或 undocumented retry。
- [x] 当前 ticket 的 integration、Contract Test Kit 与 current-generation cutover tests 通过；本 ticket 不调用真实 Provider。
- [x] 标记完成前，重跑 Tickets 01–11 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Verification evidence

- Frontend cutover 使用 `/api/v2/catalog`、Project Draft/Commit、Run Start/Cancel、
  Run-scoped event stream、bounded Run Projection、single-value retrieval 与
  Artifact retrieval；Vite `/api` proxy 支持 WebSocket upgrade，legacy `/ws`
  proxy、旧 canvas consumer 与 dead `ProteinPromptEditor` 已删除。
- Frontend current public journeys、Selection semantics exact roundtrip、typed
  array/object parameter editing、Typed Output/Artifact retrieval 与 proxy contract：
  `5 passed`；Oxlint、TypeScript 与 production build 通过，Vite transformed
  `179 modules`。
- Tickets 01–11 cumulative Node finalization、object publication/collection、
  Result Cache、Run/restart/cancellation、Selection、Workflow Compiler/Commit、
  public protocol、Protein I/O 与 ESM-3 regressions：`488 passed, 3 deselected`。
- Final Standards 与 Spec `code-review` 两轴均 `APPROVED`；trust-model audit
  确认 Provider values 只在合同所有边界验证一次，没有 repair、cross-check、
  fallback、catch-and-continue、retry、兼容 alias 或 dual path。
- `routine`：`1276 passed, 45 deselected`；`examples-v2`：`12 passed`；
  `deterministic-acceptance`：`8 passed`；`scientific-repro`：`1 passed`；
  `local-esmfold2-v2-contract`：`6 passed`；`installed-package`：`3 passed`；
  `provider-isolation`：`16 passed`；`security-failure`：`10 passed`。
- Python compilation 与 `git diff --check` 通过。所有 verification 严格串行；
  未使用 `xdist`、未调用真实 Provider、未并发加载本地模型，也未进入 Ticket
  12。SoluProt 使用 trusted root `/Users/sorachan/Documents/ESM-workflow-NEXT`，
  backend gates 显式设置 loopback `NO_PROXY`/`no_proxy`。
