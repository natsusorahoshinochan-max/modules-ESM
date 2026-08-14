# 02 — 将 Run Evidence Ledger 切换为原子 transactions

**What to build:** 让一次 Node conclusion 的 logical facts 作为一个 durable state transition 整组提交，使用户、event consumer 和 restart 只能观察到提交前或提交后的完整状态。

**Blocked by:** 01 — 收口 Node Attempt finalization seam

**Status:** ready-for-agent

- [ ] Run Evidence Ledger 使用 current-generation physical transactions，并让所有写入统一经过 transaction interface；单 fact 写入只是单 fact transaction。
- [ ] Node publication 的 Operation terminal、当前 output/Artifact publication facts、Node terminal 与 disposition 全部提交或全部不可见。
- [ ] logical fact sequences 跨 transactions 连续，event replay 与 live events 只在整组 durable 后按 sequence 发布。
- [ ] commit 前故障不会公开 logical-fact 子集；commit outcome 无法确认时不写补偿或相反 terminal。
- [ ] 旧 Ledger reader、旧 sequential writer 与 compatibility path 已删除，旧开发 Ledger 明确 unsupported。
- [ ] 当前 ticket 的 focused transaction、causal reduction、event ordering 与 failure-injection tests 通过。
- [ ] 标记完成前，重跑 Tickets 01–02 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [ ] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。
