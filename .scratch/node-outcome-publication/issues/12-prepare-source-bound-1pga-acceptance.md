# 12 — 准备 source-bound 1PGA 科学验收

**What to build:** 用 current Catalog 和固化 1PGA input 建立一条可由 installed public REST/WebSocket surface 执行的 three-way structural-consistency Workflow，并在调用真实 Provider 前用 lawful provider-free values 证明它能表达全部科学 Evidence。

**Blocked by:** 11 — 完成 current-generation cutover 与 provider-free 验收

**Status:** ready-for-agent

- [ ] source-bound input 是 exact 75-residue 1PGA structure，SHA-256 为 `d4392068a70cd5cb21f1598a83b6eff29f829d510ae808be0f62f35a6d01dc30`；原始 structure 直接作为 Project Input，不在 Workbench 外转换。
- [ ] Workflow 从 input structure 导出带 exact parent lineage 的 sequence Candidate，并通过 current Catalog 中的 exact ESMFold2 remote 和 SimpleFold local Bindings 分别折叠同一 Candidate；ESMFold2 使用 `effective_seed=1075001` 和 1 sample，SimpleFold 使用 `effective_seed=1075002`、1 sample 和 `num_steps=50`；不复制历史 contract versions。
- [ ] 两个 Method outputs 按共同 sequence parent 显式建立 sibling pairing，不依赖 collection order、文件名或单值假设。
- [ ] public Evidence 包含 input–ESMFold2、input–SimpleFold 和 ESMFold2–SimpleFold 三条 explicit alignment/TM/RMSD edges，每条都有 subject/reference identities、residue/atom correspondence、normalization length、aligned atom count、Method provenance 和 evidence digest。
- [ ] 两个 Method 的 mean-residue pLDDT 分开发布并在 `>=70` 时才进入分类；输入 PDB B-factor 保留为未解释坐标字段，不成为 pLDDT。
- [ ] `close` 精确使用 reference-normalized TM-score `>=0.80` 且 Cα RMSD `<=2.50 Å`；分类只可为 `three_way_consistent`、`method_disagreement`、`input_disagreement`、`all_disagree` 或 `insufficient_evidence`，其中恰有两条 close 使用 `threshold_boundary_nontransitive` subreason。
- [ ] lawful provider-free fixtures 通过完整 public Run journey 证明 lineage、pairing、retrieval、classification 和 Run Closure；本 ticket 不调用 remote Provider，不加载本地模型。
- [ ] 标记完成前，重跑 Tickets 01–12 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [ ] 当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。
