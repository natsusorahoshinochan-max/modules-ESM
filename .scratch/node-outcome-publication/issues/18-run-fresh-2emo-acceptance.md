# 18 — 执行 fresh 2EMO 科学验收

**What to build:** 在同一 Acceptance Campaign 的 fresh Certification 上通过 installed public REST/WebSocket surface 执行一次 fresh 2EMO Workflow，证明 CSH normalization、ProteinMPNN、ESMFold2、confidence、structure comparison、Protein-Sol 与 publication 形成完整科学 Evidence。

**Blocked by:** 17 — 执行 fresh 1PGA 科学验收

**Status:** ready-for-agent

- [ ] 使用 SHA-256 为 `6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700` 的 source input 发起 clean-source public Run，不使用历史 Cache、Artifact 或 mock。
- [ ] A:66 → A:65–A:67 parent-span normalization、224-aa fixed `SHG` target、8 个 ProteinMPNN Candidates、candidate-associated normalization、ESMFold2 structures、confidence、residue correspondence 和 Protein-Sol Observations 全部完整发布。
- [ ] ProteinMPNN 与 Protein-Sol 两个 local-model stages 严格串行：同一 stage 只有一个 resident model instance 并对全部 Candidates 复用；前一本地模型进程退出并释放后才启动后一模型。
- [ ] 四个 exact filters 在 public Evidence 中使用 TM-score `>=0.80`、Cα RMSD `<=2.50 Å`、mean pLDDT `>=70` 和 Protein-Sol scaled `>=0.446`；零个 Candidate 通过可作为完整 scientific conclusion，但缺失 Evidence 使 acceptance 失败。
- [ ] Run Projection 有界，Typed Outputs 可逐值 exact retrieval，Artifacts 使用独立 route，Ledger、Result Identity、Cache index、object ownership 和 Run Closure 与 public outcome 一致。
- [ ] 本 ticket 不修改 campaign candidate。任何修复都使 Certification 失效，必须回到 Ticket 15 创建并资格验证新 campaign，再从 Ticket 16 开始新的 canonical Certification。
- [ ] 标记完成前只核对 campaign authority、durable prefix 与无残留 child/model process；完整 repository/frontend gates 留到 Ticket 21。
