# 08 — 原子提交 Selection conclusions 与 Run Closure

**What to build:** 让 Run 只有在所有 Node dispositions 和必要 Selection conclusions 都 durable 后才得到 terminal conclusion，并让 Selection failure 与相应 Run failure 整组出现。

**Blocked by:** 06 — 准确记录 Operation、publication 与 Result Identity 失败

**Status:** completed

- [x] Run Closure 是独立 atomic transaction，只在所有 plan Nodes 已有 durable disposition 后执行。
- [x] required Selection terminals 与 Run terminal 在同一 Closure transaction 中提交或全部不可见。
- [x] Selection derivation 从 committed values 工作，不从 Projection、Cache 或 object enumeration 推断 visibility。
- [x] Run status 按既定 failed、interrupted、cancelled、succeeded precedence 从 durable dispositions 与 Selection conclusions 推导。
- [x] 无 Selection 且所有 Nodes 成功的 Run 可正常关闭；Selection derivation failure 原子产生 failed Selection 与 failed Run。
- [x] 当前 ticket 的 focused normal closure、selection success/failure、status precedence 与 public event tests 通过。
- [x] 标记完成前，重跑 Tickets 01–08 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Verification evidence

- Focused normal/no-Selection Closure、Selection success/failure、restart-audit
  completeness、status precedence、transaction failure 与 public event tests：
  `7 passed`。
- Tickets 01–08 cumulative Node finalization、public protocol、Typed Output、
  Result Cache、Run execution、cancellation/derivation、Protein I/O、Artifact、
  installed-backend、Selection 与 ESM-3 collection：`293 passed, 17
  deselected`。
- Final Standards 与 Spec `code-review` 两轴均 `APPROVED`；review 发现的额外
  completion seam、重复 Selection validation 与 restart audit completeness
  bypass 均已移除并由 focused regression 覆盖。
- `routine`：`1257 passed, 45 deselected`；`examples-v2`：`12 passed`；
  `deterministic-acceptance`：`8 passed`；`scientific-repro`：`1 passed`；
  `local-esmfold2-v2-contract`：`6 passed`；`installed-package`：`3 passed`；
  `provider-isolation`：`16 passed`；`security-failure`：`10 passed`。
- Frontend `npm run lint` 与 `npm run build` 通过；TypeScript 与 Vite transformed
  `178 modules`。Python compilation 与 `git diff --check` 通过。
- 所有 verification 严格串行；未使用 `xdist`、未调用真实 Provider、未并发
  加载本地模型，也未进入 Ticket 09。`provider-isolation` 显式使用 trusted
  SoluProt root 与 loopback `NO_PROXY`/`no_proxy`。
