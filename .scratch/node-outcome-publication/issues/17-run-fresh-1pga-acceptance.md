# 17 — 执行 fresh 1PGA 科学验收

**What to build:** 在同一 Acceptance Campaign 的 fresh Certification 上通过 installed public REST/WebSocket surface 执行一次 fresh 1PGA Workflow，证明 ESMFold2、SimpleFold 与 Node Outcome Publication 能产生完整的 three-way structural-consistency Evidence。

**Blocked by:** 16 — 串行执行完整 installed Provider matrix

**Status:** ready-for-agent

- [ ] 使用 SHA-256 为 `d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30` 的 source input 发起 clean-source public Run，不使用历史 Cache、Artifact 或 mock。
- [ ] exact ESMFold2 remote 与 SimpleFold local Bindings 各对同一 sequence Candidate 产生一个 structure Candidate，lineage、Method、Binding、Engine Invocation 和 public retrieval 完整。
- [ ] SimpleFold gate 期间只有一个 local-model instance，无并发 verifier/Workflow/model process；其进程退出并释放后才继续下一验收。
- [ ] 三条 alignment/TM/RMSD edges、两个 Method-specific confidence Observations、explicit sibling pairing 和 exact classification 全部可通过 public Evidence 审计；输入 B-factor 没有被当作 pLDDT。
- [ ] Run Projection 有界，Typed Outputs 可逐值 exact retrieval，Artifacts 使用独立 route，Ledger、Result Identity、Cache index、object ownership 和 Run Closure 与 public outcome 一致。
- [ ] 本 ticket 不修改 campaign candidate。任何修复都使 Certification 失效，必须回到 Ticket 15 创建并资格验证新 campaign，再从 Ticket 16 开始新的 canonical Certification。
- [ ] 标记完成前只核对 campaign authority、durable prefix 与无残留 child/model process；完整 repository/frontend gates 留到 Ticket 21。
