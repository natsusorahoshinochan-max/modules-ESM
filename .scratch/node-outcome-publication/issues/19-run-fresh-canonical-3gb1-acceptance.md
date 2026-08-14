# 19 — 执行 fresh canonical 3GB1 验收

**What to build:** 在同一冻结 generation 上通过 installed public REST/WebSocket surface 执行 canonical 3GB1 Workflow，证明现有基准科学链在 descriptor/retrieval publication contract 下仍然完整。

**Blocked by:** 18 — 执行 fresh 2EMO 科学验收

**Status:** ready-for-agent

- [ ] 使用 SHA-256 为 `ee623d3d9fd77a131895dc367c31ac8d7266b1d4f241b56325170e5f62ed7811` 的 source input 发起 clean-source public Run，不使用历史 Cache、Artifact 或 mock。
- [ ] Run 精确产生 10 个 paired ESM-3 Candidates、top 3 selection、每个 selected parent 的 5 个 ProteinMPNN designs（3×5，共 15 个）和 15 个最终 folds/Artifacts，并保留 current canonical Workflow 的 science、lineage、pairing、Method 与 provenance。
- [ ] ProteinMPNN local-model stage 只加载一个 resident instance 并对全部设计 calls 复用；无并发 verifier/Workflow/model process，进程退出并释放后才继续下一验收。
- [ ] Run Projection 有界，15 个最终 Artifacts 和全部 Typed Outputs 通过各自 public routes 可取，Ledger、Result Identity、Cache index、object ownership 和 Run Closure 与 public outcome 一致。
- [ ] 本 ticket 不修改冻结 generation。任何修复都使 Tickets 16–19 证据失效，必须回到 Ticket 15 重新冻结并从 Ticket 16 开始重跑。
- [ ] 标记完成前，完整 provider-free repository matrix 和 frontend gates 在冻结 checkout 上再次通过，且 Tickets 01–19 的全部累计 acceptance evidence 保持有效。
