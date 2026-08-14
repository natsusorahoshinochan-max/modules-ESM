# 10 — 只回收无引用 immutable objects

**What to build:** 让 publication failure 或 crash 留下的无主 immutable objects 可被安全回收，同时任何 committed Run、有效 Cache replay 或 active staging 所拥有的对象都不会被删除。

**Blocked by:** 05 — 让 Ledger 掌握 Result Identity，并将 Cache 改为引用；09 — 从 durable prefix 恢复真实 Run 状态

**Status:** ready-for-agent

- [ ] GC roots 只来自 committed Ledger object references、valid current-generation Cache indexes 与 active staging ownership。
- [ ] typed-value、Artifact 和 Node publication failure 留下但从未被 transaction 引用的 objects 可在 startup collection 中删除。
- [ ] 跨 Runs 或 Cache indexes 共享的 content-addressed object 在任一 owner 仍存在时保持可取回。
- [ ] GC 在当前 Ledgers 与 Cache indexes 验证完成后运行，不把 object enumeration 当作 public visibility authority。
- [ ] GC failure 可观测但不改变 scientific outcomes；任何 referenced object 都不会因为 cleanup failure 或 cancellation 被删除。
- [ ] 当前 ticket 的 focused orphan cleanup、shared ownership、active staging、Cache root 与 restart tests 通过。
- [ ] 标记完成前，重跑 Tickets 01–10 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [ ] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。
