# 07 — 公开 evidence unavailable，并精确排序 cancellation

**What to build:** 当 worker 已结束但 required Ledger evidence 无法确认时，用户立即看到 evidence unavailable 而不是永久 `running`；同时 cancellation 与 Node finalization 由同一 durable ordering 决定谁先完成。

**Blocked by:** 06 — 准确记录 Operation、publication 与 Result Identity 失败

**Status:** completed

- [x] background worker 无法提交 required evidence 时，active Run record 同时保留 finished signal 与 sticky `evidence_unavailable`。
- [x] 同进程 Run Projection 和 Cancel Run 不再把这种状态报告为 `running`，且不虚构 terminal event 或发布 Cache entry。
- [x] transaction final-name publication 后 durability 无法确认时，不补偿、不删除 final-name transaction、不写相反 terminal，也不自动 retry。
- [x] cancellation 与 Node finalization 使用同一 Run ordering lock；success-first 保留 success，cancellation-first 阻止 outputs publication。
- [x] cancellation receipt 能区分 active worker、已结束但 evidence 未确认的 worker，以及已经 committed 的 terminal outcome。
- [x] 当前 ticket 的 focused same-process evidence failure、rename ambiguity、cancellation race、event 和 shared-object tests 通过。
- [x] 标记完成前，重跑 Tickets 01–07 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Verification evidence

- Focused same-process unavailable-evidence, pre/post-final-name ambiguity,
  success-first/cancellation-first ordering, event-stream, Cache nonpublication,
  and shared-object ownership suites: `46 passed, 2 deselected`.
- Tickets 01–07 cumulative Node finalization, public protocol, Typed Output,
  Result Cache, Run execution, Protein I/O, cancellation, Artifact, and
  installed-backend collection: `236 passed, 17 deselected`.
- Final Standards and Spec `code-review` axes both reported `APPROVED` with
  zero findings after the ordering-race repair.
- `routine`: `1250 passed, 45 deselected`; `examples-v2`: `12 passed`;
  `deterministic-acceptance`: `8 passed`; `scientific-repro`: `1 passed`;
  `local-esmfold2-v2-contract`: `6 passed`; `installed-package`: `3 passed`;
  `provider-isolation`: `16 passed`; `security-failure`: `10 passed`.
- Frontend `npm run lint` and `npm run build` passed; TypeScript and Vite
  transformed `178 modules`.
- All verification ran strictly serially without `xdist`, real Provider calls,
  or concurrent local-model loading. The trusted SoluProt root and loopback
  `NO_PROXY` were supplied explicitly to backend gates.
