# 08 — 原子提交 Selection conclusions 与 Run Closure

**What to build:** 让 Run 只有在所有 Node dispositions 和必要 Selection conclusions 都 durable 后才得到 terminal conclusion，并让 Selection failure 与相应 Run failure 整组出现。

**Blocked by:** 06 — 准确记录 Operation、publication 与 Result Identity 失败

**Status:** ready-for-agent

- [ ] Run Closure 是独立 atomic transaction，只在所有 plan Nodes 已有 durable disposition 后执行。
- [ ] required Selection terminals 与 Run terminal 在同一 Closure transaction 中提交或全部不可见。
- [ ] Selection derivation 从 committed values 工作，不从 Projection、Cache 或 object enumeration 推断 visibility。
- [ ] Run status 按既定 failed、interrupted、cancelled、succeeded precedence 从 durable dispositions 与 Selection conclusions 推导。
- [ ] 无 Selection 且所有 Nodes 成功的 Run 可正常关闭；Selection derivation failure 原子产生 failed Selection 与 failed Run。
- [ ] 当前 ticket 的 focused normal closure、selection success/failure、status precedence 与 public event tests 通过。
- [ ] 标记完成前，重跑 Tickets 01–08 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [ ] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。
