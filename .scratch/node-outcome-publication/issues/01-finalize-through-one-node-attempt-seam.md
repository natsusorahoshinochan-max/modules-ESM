# 01 — 收口 Node Attempt finalization seam

**What to build:** 在不改变当前公开行为的前提下，让 executed success、executed non-success、Cache replay success、cancellation 和 interruption 全部通过唯一的 Node Attempt completion seam，使后续 publication 改造只有一个权威入口。

**Blocked by:** None — can start immediately

**Status:** completed

- [x] 所有当前 Node completion outcomes 都由 closed finalization intents 表达，并通过唯一 finalizer 得到 disposition。
- [x] execution orchestrator 不再直接协调 terminal facts、output publication、Artifact publication、Cache order 或 rollback callbacks；被替代的路径已删除。
- [x] 现有 public Run、event、Cache replay、cancellation 与 restart 可观察行为保持不变。
- [x] 改造没有增加重复 validation、broad catches、silent coercion、fallback 或 undocumented retry。
- [x] 当前 ticket 的 focused tests 通过。
- [x] 标记完成前，重跑从 Ticket 01 到当前 ticket 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Verification evidence

- Focused finalization/public behavior matrix: `133 passed, 3 deselected`.
- Provider-free backend matrix: `routine` (`1198 passed, 45 deselected`), `examples-v2` (`12 passed`), `deterministic-acceptance` (`8 passed`), `scientific-repro` (`1 passed`), `local-esmfold2-v2-contract` (`6 passed`), `installed-package` (`3 passed`), `provider-isolation` (`16 passed`), and `security-failure` (`10 passed`).
- Frontend: `npm run lint` and `npm run build` passed serially.
- The repository `code-review` skill reported zero remaining Standards findings and zero remaining Spec findings against the pre-ticket fixed point.
- No real Provider was invoked; all verification commands ran serially without `xdist` or concurrent model loading.
