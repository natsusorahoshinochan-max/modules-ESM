# 02 — 将 Run Evidence Ledger 切换为原子 transactions

> Historical completion evidence only. Checksums, symlink/security probes, Readiness-before-Cache, restart reconstruction, and old verification tiers mentioned below are not current requirements.

**What to build:** 让一次 Node conclusion 的 logical facts 作为一个 durable state transition 整组提交，使用户、event consumer 和 restart 只能观察到提交前或提交后的完整状态。

**Blocked by:** 01 — 收口 Node Attempt finalization seam

**Status:** completed

- [x] Run Evidence Ledger 使用 current-generation physical transactions，并让所有写入统一经过 transaction interface；单 fact 写入只是单 fact transaction。
- [x] Node publication 的 Operation terminal、当前 output/Artifact publication facts、Node terminal 与 disposition 全部提交或全部不可见。
- [x] logical fact sequences 跨 transactions 连续，event replay 与 live events 只在整组 durable 后按 sequence 发布。
- [x] commit 前故障不会公开 logical-fact 子集；commit outcome 无法确认时不写补偿或相反 terminal。
- [x] 旧 Ledger reader、旧 sequential writer 与 compatibility path 已删除，旧开发 Ledger 明确 unsupported。
- [x] 当前 ticket 的 focused transaction、causal reduction、event ordering 与 failure-injection tests 通过。
- [x] 标记完成前，重跑 Tickets 01–02 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Verification evidence

- Focused cumulative transaction/finalization/public behavior matrix: `150 passed, 3 deselected`.
- Provider-free backend matrix on the final checkout: `routine` (`1210 passed, 45 deselected`), `examples-v2` (`12 passed`), `deterministic-acceptance` (`8 passed`), `scientific-repro` (`1 passed`), `local-esmfold2-v2-contract` (`6 passed`), `installed-package` (`3 passed`), `provider-isolation` (`16 passed`), and `security-failure` (`10 passed`).
- Frontend: `npm run lint` and `npm run build` passed serially.
- The final repository `code-review` pass reported zero remaining Standards findings and zero remaining Spec findings against fixed point `22ae0595884c42450a88a6946a492be5755cb701`.
- No real Provider was invoked; all verification commands ran serially without `xdist` or concurrent model loading.
