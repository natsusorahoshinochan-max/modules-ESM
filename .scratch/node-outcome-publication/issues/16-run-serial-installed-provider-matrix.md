# 16 — 串行执行完整 installed Provider matrix

**What to build:** 在冻结 generation 上逐一执行所有已声明 Provider gates，证明 installed artifact 中的 remote 与 local Provider capabilities 都能通过 current public contract 产生真实、zero-skip Evidence。

**Blocked by:** 15 — 冻结完整 acceptance generation

**Status:** ready-for-agent

- [ ] 真实 Provider 调用前，Tickets 01–15 的累计 criteria 与完整 provider-free/frontend matrix 在冻结 checkout 上再次通过。
- [ ] Biohub ESMC、Biohub ESM-3、Biohub ESMFold2、local ESM-3、local ESMFold2、mkdssp、ProteinMPNN、SimpleFold folding、SimpleFold confidence、SoluProt 和 Protein-Sol gates 依次执行，全部 zero-skip 通过。
- [ ] 任何时刻只运行一个 gate child process；当前 local-model gate 只有一个 resident model instance，同模型的所有 calls 复用它，child 退出并释放后才启动下一 gate。
- [ ] 每个 gate 的 public outcome、Provider/Method/Binding provenance、exact result counts、Artifacts/Typed Outputs 与 evidence bundle digest 都写入同一 generation manifest。
- [ ] 不使用 mock、skip、历史 Cache 或历史 Artifact 替代真实 Provider execution；不用本 matrix 重复测试 core fault mechanics。
- [ ] 执行期间不修改 source、tests、contracts、generated artifacts、Provider assets/configuration 或 installed artifact。任何修复都使本 generation 失效，必须回到 Ticket 15 重新冻结并重跑本 ticket。
- [ ] 标记完成前，当前冻结 checkout 的完整 provider-free repository matrix 和 frontend gates 全部再次通过，且 Tickets 01–16 的全部累计 acceptance evidence 保持有效。
