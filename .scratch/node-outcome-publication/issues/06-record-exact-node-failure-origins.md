# 06 — 准确记录 Operation、publication 与 Result Identity 失败

**What to build:** 让每个 failed Node 的 durable evidence 精确说明失败发生在 scientific Operation、Node Outcome Publication 或 Result Identity comparison，而不改写已经完成的 Operation。

**Blocked by:** 05 — 让 Ledger 掌握 Result Identity，并将 Cache 改为引用

**Status:** completed

- [x] documented Provider translation、normalization、Candidate identity normalization、Port admission 与 Artifact contract processing 仍属于 Operation Attempt；这些步骤失败时 Operation 与 Node 因果一致。
- [x] object persistence 或 publication failure 在 Ledger 仍可写时保留 executed Operation `succeeded`，并以 `publication` origin 关闭 failed Node，且不公开 outputs 或 Artifacts。
- [x] Result Identity mismatch 保留 executed Operation `succeeded`，并以 `result_identity` origin 关闭 failed Node。
- [x] operation non-success、publication failure 与 Result Identity failure 均使用一个完整 transaction 写入所需 terminals 与 disposition。
- [x] public errors 精确使用 current-generation codes 与 bounded details，不暴露 paths、canonical values 或 raw exceptions。
- [x] 实现信任 admitted values 与官方 Provider contract，不新增 hypothetical malformed-response handling、schema repair、cross-check 或 fallback。
- [x] 当前 ticket 的 focused causal reducer、failure-origin、public error 与 publication fault tests 通过。
- [x] 标记完成前，重跑 Tickets 01–06 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Verification evidence

- Focused Node finalization、public protocol、typed-value publication、Result
  Cache、Run execution 与 Protein I/O 累计 collection：`208 passed, 1
  deselected`；Python compilation 与 `git diff --check` 通过。
- Final Standards review 与 Spec review 均 `APPROVED`，零 findings；reviewer
  定向累计分别为 `208 passed, 1 deselected` 与 `172 passed, 1
  deselected`。
- `routine`：`1244 passed, 45 deselected`；`examples-v2`：`12 passed`；
  `deterministic-acceptance`：`8 passed`；`scientific-repro`：`1 passed`；
  `local-esmfold2-v2-contract`：`6 passed`；`installed-package`：`3 passed`；
  `provider-isolation`：`16 passed`；`security-failure`：`10 passed`。
- `routine` 首轮发现 Project Input resolution 被误归为 pre-operation local
  invariant；修复后 Project Input、input admission、Candidate identity 与
  randomness resolution 均保留真实 Operation evidence，完整 matrix 重跑通过。
- Frontend `npm run lint` 与 `npm run build` 通过；Vite transformed `178
  modules`。
- 所有 verification 严格串行；未使用 `xdist`、未调用真实 Provider、未并发
  加载本地模型，也未进入 Ticket 07。
