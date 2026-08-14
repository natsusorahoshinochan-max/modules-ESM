# 10 — 只回收无引用 immutable objects

**What to build:** 让 publication failure 或 crash 留下的无主 immutable objects 可被安全回收，同时任何 committed Run、有效 Cache replay 或 active staging 所拥有的对象都不会被删除。

**Blocked by:** 05 — 让 Ledger 掌握 Result Identity，并将 Cache 改为引用；09 — 从 durable prefix 恢复真实 Run 状态

**Status:** completed

- [x] GC roots 只来自 committed Ledger object references、valid current-generation Cache indexes 与 active staging ownership。
- [x] typed-value、Artifact 和 Node publication failure 留下但从未被 transaction 引用的 objects 可在 startup collection 中删除。
- [x] 跨 Runs 或 Cache indexes 共享的 content-addressed object 在任一 owner 仍存在时保持可取回。
- [x] GC 在当前 Ledgers 与 Cache indexes 验证完成后运行，不把 object enumeration 当作 public visibility authority。
- [x] GC failure 可观测但不改变 scientific outcomes；任何 referenced object 都不会因为 cleanup failure 或 cancellation 被删除。
- [x] 当前 ticket 的 focused orphan cleanup、shared ownership、active staging、Cache root 与 restart tests 通过。
- [x] 标记完成前，重跑 Tickets 01–10 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Verification evidence

- TDD focused startup orphan/stale-staging、shared Run ownership、committed
  Artifact、active writer、invalid Ledger/Cache owner 与 observable collection
  failure suite：`7 passed`；扩展 object/finalizer/Cache focused suite：`84
  passed`。
- Tickets 01–10 cumulative public journeys、fault regressions、Typed Output、
  Result Cache、Run/restart/cancellation、Protein I/O、Artifact、Contract Test
  Kit、Selection、Workflow Commit/Compiler 与 ESM-3 collection：`486 passed,
  17 deselected`。
- Final Standards 与 Spec `code-review` 两轴均 `APPROVED`。Review 发现的
  Port Value Manifest 重复验证、Project output-root 重复解析与静默 cleanup
  failure 均已移除；damaged Ledger/invalid Cache 保留 Ticket 09 的
  Project-scoped fail-closed isolation，并在 sweep 前停止该 Project collection。
- `routine`：`1276 passed, 45 deselected`；`examples-v2`：`12 passed`；
  `deterministic-acceptance`：`8 passed`；`scientific-repro`：`1 passed`；
  `local-esmfold2-v2-contract`：`6 passed`；`installed-package`：`3 passed`；
  `provider-isolation`：`16 passed`；`security-failure`：`10 passed`。
- Frontend `npm run lint` 与 `npm run build` 通过；TypeScript 与 Vite
  transformed `178 modules`。Python compilation 与 `git diff --check` 通过。
- 所有 verification 严格串行；未使用 `xdist`、未调用真实 Provider、未并发
  加载本地模型，也未进入 Ticket 11。SoluProt verification 使用 trusted root
  `/Users/sorachan/Documents/ESM-workflow-NEXT`，backend gates 显式使用
  loopback `NO_PROXY`/`no_proxy`。
