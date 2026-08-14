# 09 — 从 durable prefix 恢复真实 Run 状态

**What to build:** 让 restart 只根据完整、连续的 committed transactions 恢复 Node、Selection 和 Run outcomes，从而区分真正未完成的执行与已经成功但原 Closure 未写入的 Run。

**Blocked by:** 07 — 公开 evidence unavailable，并精确排序 cancellation；08 — 原子提交 Selection conclusions 与 Run Closure

**Status:** ready-for-agent

- [ ] restart 载入并验证完整 contiguous transaction prefix；private staging 不产生 evidence，违反 current-generation Ledger contract 时 fail fast。
- [ ] open Engine Invocation 恢复为 `outcome_unknown`；open Operation、未启动 Node 与 downstream Node 按 durable direct cause 得到准确 terminal/disposition。
- [ ] committed successful Nodes 不因 restart、Projection、Cache 或 object read problem 被改写为 `interrupted`。
- [ ] 所有 Node dispositions 成功时，restart 能重建必要 Selection 并应用正常 Run Closure；无 Selection 的 Run 也能恢复为 `succeeded`。
- [ ] `restart_reconciliation_started` 只作为 audit evidence，不参与 Run status 决策。
- [ ] commit outcome ambiguity 只由磁盘上的下一条完整 canonical transaction 解决，不产生冲突或补偿 facts。
- [ ] recovery transaction 在再次 crash 后可由新 durable prefix 安全继续，不依赖隐藏 retry loop。
- [ ] 当前 ticket 的 focused restart matrix、selection rebuild、missing Closure 与 repeated-restart tests 通过。
- [ ] 标记完成前，重跑 Tickets 01–09 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [ ] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。
