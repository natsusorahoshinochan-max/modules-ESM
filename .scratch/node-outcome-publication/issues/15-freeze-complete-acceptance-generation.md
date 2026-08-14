# 15 — 冻结完整 acceptance generation

**What to build:** 把 1PGA、2EMO、canonical 3GB1、5G53 与全部 installed Provider gates 组成一个可重现、zero-skip、严格串行的 current-generation 验收面，然后冻结将要产生真实证据的 source、artifact、Catalog、protocol 和 Provider assets/configuration。

**Blocked by:** 14 — 准备 source-bound 5G53 科学验收

**Status:** ready-for-agent

- [ ] 保留 canonical 3GB1 现有科学合同：10 个 paired ESM-3 Candidates、top 3 selection、每个 selected parent 的 5 个 ProteinMPNN designs（3×5，共 15 个）、15 个最终 folds/Artifacts 和 exact lineage/provenance，并将其全部切换到 descriptor/retrieval public contract。
- [ ] 1PGA、2EMO、3GB1 和 5G53 分别具有 clean-source、zero-skip、retain-evidence acceptance tier；四个 tiers 的静态收集、input digests、current Catalog references 和 public journey contracts 全部通过，本 ticket 不执行 Provider calls。
- [ ] installed Provider matrix 精确包含 Biohub ESMC、Biohub ESM-3、Biohub ESMFold2、local ESM-3、local ESMFold2、mkdssp、ProteinMPNN、SimpleFold folding、SimpleFold confidence、SoluProt 和 Protein-Sol，所有 tiers 都 zero-skip。
- [ ] verification controller 只逐一启动 tier/Workflow child process，不使用 pytest-xdist、不并发调度、不嵌套 local-model processes；只有上一 child 退出并释放后才进入下一项。
- [ ] 每个 local-model gate 在单一进程内只加载一个该模型实例，并对该 gate 内的全部 calls 复用；不按 sample、Candidate 或 test case 创建并发/重复实例。
- [ ] evidence manifest 能绑定 source revision、installed artifact digest、public bundle/Catalog identities、四个 input digests、Provider asset/configuration identities、tier order 和每次 result；不引入 authentication、distributed lock 或 adversarial coordination。
- [ ] 标记完成前，重跑 Tickets 01–15 的全部累计 public journeys、fault regressions 和 acceptance criteria，并确认无待补的 scientific evidence gap。
- [ ] 冻结 checkout 前的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。
