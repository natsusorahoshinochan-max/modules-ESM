# 04 — 让 Artifacts 共享 immutable object store

**What to build:** 让 Artifact bytes 与 Typed Output values 共享 durable object ownership，同时保持 Artifact 的 nominal Port semantics、descriptor 和 retrieval contract 独立，并与同一 Node 的 outputs 原子可见。

**Blocked by:** 03 — 通过 immutable value objects 发布大型 Typed Outputs

**Status:** completed

- [x] Artifact bytes 在 Node publication transaction 前通过同一 Project-scoped immutable store durable。
- [x] transaction 未提交时，Artifact 不进入 public artifact index；成功时 Artifact 与 Typed Outputs、Node terminal 和 disposition 整组可见。
- [x] Artifact descriptor 保留 artifact intent、media type、filename provenance、Candidate association 与独立 public retrieval route。
- [x] ordinary Typed Output 不会被伪装成 Artifact；共享物理 bytes 不改变 nominal Port Type 或 scientific semantics。
- [x] 随机 Run-scoped Artifact file 不再是权威表示，被替代的写入和 rollback 路径已删除。
- [x] 当前 ticket 的 focused Artifact publication、retrieval、transaction failure 与 installed public journey tests 通过。
- [x] 标记完成前，重跑 Tickets 01–04 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 标记完成前，当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Verification evidence

- TDD RED：public Artifact journey 首先因 descriptor 缺少 `filename` 失败；UTF-8/引号/最大长度 response contract 以 `4 failed` 证明旧 quoted filename 不闭合；canonical 3GB1 consumer regression 首先因缺少新 helper 无法收集。
- Focused Tickets 01–04 cumulative：`222 passed, 7 deselected`。
- Controlled canonical 3GB1 full public journey：`1 passed`；canonical evidence consumer filename regression：`1 passed`。
- Final Standards review：APPROVED，P0/P1/P2/LOW 均为 0。
- Final Spec review：APPROVED，P0/P1/P2 均为 0。
- `routine`：`1231 passed, 45 deselected`。
- `examples-v2`：`12 passed`。
- `deterministic-acceptance`：`8 passed`。
- `scientific-repro`：`1 passed`。
- `local-esmfold2-v2-contract`：`6 passed`。
- `installed-package`：`3 passed`。
- `provider-isolation`：`16 passed`。
- `security-failure`：`10 passed`。
- Frontend `npm run lint` 与 `npm run build`：通过；Vite transformed `178 modules`。
- 所有门禁严格串行；未使用 `xdist`，未调用真实 Provider，未并发加载本地模型。
