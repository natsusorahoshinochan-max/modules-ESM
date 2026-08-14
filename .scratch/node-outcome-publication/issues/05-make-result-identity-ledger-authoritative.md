# 05 — 让 Ledger 掌握 Result Identity，并将 Cache 改为引用

**What to build:** 让 committed Node Result Manifests 决定 Project-scoped Result Identity，使 Cache 只是一项引用相同 immutable objects 的 replay 优化，而不是 evidence 或 identity authority。

**Blocked by:** 04 — 让 Artifacts 共享 immutable object store

**Status:** completed

- [x] Node Result Manifest 覆盖 Result Identity、compiler-owned result contract metadata 以及所有 ordinary 与 artifact-capable output Port manifests。
- [x] Project-scoped Result Identity index 可完全从 committed current-generation Ledgers 重建；publication lock 原子覆盖 equality comparison、Run transaction commit 与 index advance。
- [x] 相同 Result Identity 与相同 manifests 可跨 Runs 再发布；冲突 manifests 即使没有 Cache directory 也以 `result_identity_conflict` 失败。
- [x] Cache v4 只引用 Node Result Manifest 和 immutable objects，不复制或 base64 编码 canonical values。
- [x] Cache replay 保留原 producer provenance 和当前 Run materialization，不生成 Operation Attempt 或 Engine Invocation facts。
- [x] Cache publication failure 不回滚 Node success；Cache absence 是 miss，违反 current-generation Cache contract 时 fail fast。
- [x] scientific Result Identity 继续使用既定 hashing namespace；旧 Cache schema、旧 conflict name 与 rollback path 已删除。
- [x] 当前 ticket 的 focused Result Identity concurrency、Cache replay、Cache failure 与 public error tests 通过。
- [x] 标记完成前，重跑 Tickets 01–05 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Verification evidence

- Focused Node finalization、public protocol、Result Identity、Cache replay、
  cancellation 与 execution matrix：`187 passed, 3 deselected`。
- Tickets 01–05 扩展累计 public/fault/installed collection：`215 passed,
  21 deselected`。
- Final Standards review 与 Spec review 均 `APPROVED`，零 findings；reviewer
  定向累计为 `172 passed, 1 deselected`。
- `routine`：`1237 passed, 45 deselected`；`examples-v2`：`12 passed`；
  `deterministic-acceptance`：`8 passed`；`scientific-repro`：`1 passed`；
  `local-esmfold2-v2-contract`：`6 passed`；`installed-package`：`3 passed`；
  `provider-isolation`：`16 passed`；`security-failure`：`10 passed`。
- `provider-isolation` 首次调用因未声明 required trusted SoluProt root 按合同失败；
  显式指定现有 trusted runtime root 后完整 `16 passed`。
- Frontend `npm run lint` 与 `npm run build` 通过；Vite transformed `178
  modules`。`git diff --check` 与 Python compilation 通过。
- 所有 verification 严格串行；未使用 `xdist`、未调用真实 Provider、未加载
  本地模型，也未进入 Ticket 06。
