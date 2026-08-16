# 21 — 审查完整 Acceptance Campaign Certification

**What to build:** 对同一 Acceptance Campaign 的 fresh Certification、全部 installed Provider gates、1PGA、2EMO、canonical 3GB1、5G53 与最终 repository gates 进行整体审查，只在无跨代拼接、无 skip、无回归且科学 Evidence 完整时宣告这组 tickets 完成。

**Blocked by:** 20 — 执行 fresh 5G53 科学验收

**Status:** ready-for-agent

- [ ] campaign manifest 证明所有 Certification evidence 绑定同一 source revision、installed artifact digest、public bundle/Catalog identities、Provider asset/configuration、Execution Profile identities 和四个 source-input digests。
- [ ] 15/15 Qualification Results 均属于同一 candidate 且明确 non-authoritative；Certification 从 ordinal 0 fresh 执行，没有提升、拼接或复用 Qualification evidence。
- [ ] 全部 11 个 installed Provider tiers 和 4 个 source-bound Workflow tiers 都是 fresh、zero-skip、terminal 且有 retained evidence bundle；没有 mock、历史 Cache/Artifact 或手工拼接。
- [ ] local-model execution log 证明 gates 严格串行，任何时刻只有一个 child process 和一个 resident model instance，同 gate 内的同模型 calls 复用单一实例，模型切换前上一进程已释放。
- [ ] 1PGA、2EMO、3GB1 和 5G53 的 exact counts、thresholds、lineage、pairing、residue mappings、confidence、Artifacts、Typed Output retrieval、Run Closure 和允许的 zero-passing scientific conclusions 分别通过合同审查。
- [ ] 最后一次重跑完整 provider-free repository matrix：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build；全部通过且没有改变冻结 revision。
- [ ] 从 Ticket 16 开始没有 source、test harness、contract、generated artifact、Provider asset/configuration、Execution Profile identity 或 installed artifact 变更。若存在，整个 campaign 失效并从 Ticket 15 重新 qualification、再从 Ticket 16 重跑 Certification，不允许保留之前的绿色结果。
- [ ] 只有 Tickets 01–21 的全部累计 acceptance criteria 在当前冻结 checkout 上同时成立时，本 ticket 才可标记完成。
