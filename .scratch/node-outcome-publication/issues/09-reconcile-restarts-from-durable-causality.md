# 09 — 从 durable prefix 恢复真实 Run 状态

**What to build:** 让 restart 只根据完整、连续的 committed transactions 恢复 Node、Selection 和 Run outcomes，从而区分真正未完成的执行与已经成功但原 Closure 未写入的 Run。

**Blocked by:** 07 — 公开 evidence unavailable，并精确排序 cancellation；08 — 原子提交 Selection conclusions 与 Run Closure

**Status:** completed

- [x] restart 载入并验证完整 contiguous transaction prefix；private staging 不产生 evidence，违反 current-generation Ledger contract 时 fail fast。
- [x] open Engine Invocation 恢复为 `outcome_unknown`；open Operation、未启动 Node 与 downstream Node 按 durable direct cause 得到准确 terminal/disposition。
- [x] committed successful Nodes 不因 restart、Projection、Cache 或 object read problem 被改写为 `interrupted`。
- [x] 所有 Node dispositions 成功时，restart 能重建必要 Selection 并应用正常 Run Closure；无 Selection 的 Run 也能恢复为 `succeeded`。
- [x] `restart_reconciliation_started` 只作为 audit evidence，不参与 Run status 决策。
- [x] commit outcome ambiguity 只由磁盘上的下一条完整 canonical transaction 解决，不产生冲突或补偿 facts。
- [x] recovery transaction 在再次 crash 后可由新 durable prefix 安全继续，不依赖隐藏 retry loop。
- [x] 当前 ticket 的 focused restart matrix、selection rebuild、missing Closure 与 repeated-restart tests 通过。
- [x] 标记完成前，重跑 Tickets 01–09 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Verification evidence

- Focused restart、direct-cause、cancellation、Selection rebuild、missing
  Closure、commit ambiguity 与 repeated-restart suites：`148 passed`。
- Tickets 01–09 cumulative public journeys、fault regressions、Typed Output、
  Result Cache、Protein I/O、Artifact、installed-backend、Selection、Workflow
  Commit 与 ESM-3 collection：`338 passed, 14 deselected`。
- Final Standards、Spec 与 Python reviews 均 `APPROVED`。Review 发现的 durable
  cancellation precedence、Engine failed/cancelled direct-cause 丢失及 guessed
  restart error fallback 均已由 RED regressions 驱动修复。
- `routine`：`1269 passed, 45 deselected`；`examples-v2`：`12 passed`；
  `deterministic-acceptance`：`8 passed`；`scientific-repro`：`1 passed`；
  `local-esmfold2-v2-contract`：`6 passed`；`installed-package`：`3 passed`；
  `provider-isolation`：`16 passed`；`security-failure`：`10 passed`。
- Frontend `npm run lint` 与 `npm run build` 通过；TypeScript 与 Vite transformed
  `178 modules`。Python compilation 与 `git diff --check` 通过。
- 所有 verification 严格串行；未使用 `xdist`、未调用真实 Provider、未并发
  加载本地模型，也未进入 Ticket 10。SoluProt verification 使用 trusted root
  `/Users/sorachan/Documents/ESM-workflow-NEXT`，安装与隔离 gates 显式使用
  loopback `NO_PROXY`/`no_proxy`。
