# 16 — 串行执行完整 installed Provider matrix

**What to build:** 在 15/15 Qualification 已通过的同一 Acceptance Campaign 上启动 fresh Certification，逐一执行全部 installed Provider gates，证明 frozen installed artifact 中的 remote 与 local Provider capabilities 都能通过 current public contract 产生权威、zero-skip Evidence。

**Blocked by:** 15 — 准备并资格验证 Acceptance Campaign

**Status:** ready-for-agent

- [ ] `campaign.json` 显示 exact candidate 的 15 个 latest Qualification Results 全部 passed、Certification=`not_started`；Qualification evidence 不计入本 ticket。
- [ ] Biohub ESMC、Biohub ESM-3、Biohub ESMFold2、local ESM-3、local ESMFold2、mkdssp、ProteinMPNN、SimpleFold folding、SimpleFold confidence、SoluProt 和 Protein-Sol gates 依次执行，全部 zero-skip 通过。
- [ ] 任何时刻只运行一个 gate child process；当前 local-model gate 只有一个 resident model instance，同模型的所有 calls 复用它，child 退出并释放后才启动下一 gate。
- [ ] 每个 gate 的 public outcome、Provider/Method/Binding provenance、exact result counts、Artifacts/Typed Outputs 与 evidence bundle digest 都写入同一 campaign 的 Certification results。
- [ ] 不使用 mock、skip、历史 Cache 或历史 Artifact 替代真实 Provider execution；不用本 matrix 重复测试 core fault mechanics。
- [ ] 执行期间不修改 source、tests、contracts、generated artifacts、Provider assets/configuration、Execution Profile identity 或 installed artifact。任何修复都使本 campaign 失效，必须回到 Ticket 15 创建并重新资格验证新 candidate。
- [ ] 每个 tier 之间只核对 campaign authority、durable state 与无残留 child/model process；完整 provider-free/backend/frontend matrix 留到 Ticket 21 最终审查一次执行。
