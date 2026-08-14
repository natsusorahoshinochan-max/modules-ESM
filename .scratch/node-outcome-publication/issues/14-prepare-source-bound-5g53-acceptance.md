# 14 — 准备 source-bound 5G53 科学验收

**What to build:** 用 current Catalog 和固化四链 5G53 input 建立完整的可变长度 paired-generation Workflow，并用 lawful provider-free values 同时证明大型 Typed Output publication 与 resolved-core、counterpart、loop、junction 和 clash Evidence。

**Blocked by:** 13 — 准备 source-bound 2EMO 科学验收

**Status:** ready-for-agent

- [ ] source-bound input 的 SHA-256 为 `a928fad49a755050d981bb9e02c94ca29e1ba09b92f129c71bb95e98a35e3537`；原始 A/B/C/D 四链 complex、HETATM、raw text 和 provenance 直接导入，再由显式 Node 选择 chain A。
- [ ] Workflow 保留 chain A 的 283 个 resolved residues 与 A:146→A:159 unresolved discontinuity，只在 A:211 与 A:224 之间构建 8、12、16-residue target layouts，并保留已锁定的 chain-qualified residue identities。
- [ ] 三个 ESM-3 paired branches 使用 current Catalog exact Biohub Medium Binding、`effective_seed` 5353008/5353012/5353016、每分支 2 samples、20 steps、temperature `0.7`、top-p `1.0`、cosine/random 与 temperature annealing，按 shorter-8、numbering-implied-12、longer-16 合并为 6 对 exact counterparts。
- [ ] 每个 generated sequence 通过 current Catalog exact ESMFold2 remote Binding 独立折叠，使用 `effective_seed=5353999` 和单 sample；所有 reference/counterpart comparisons 使用 explicit residue correspondence 和 pairing。
- [ ] 每个 Candidate 发布 resolved-core TM-score/RMSD、counterpart TM-score/RMSD、resolved-core mean pLDDT、单独 loop pLDDT、两个 junction C–N distances 与排除共价相邻 atom 后的 loop/core nonbonded heavy-atom minimum distance。
- [ ] 科学 gates 精确为 resolved-core TM-score `>=0.75` 且 RMSD `<=3.00 Å`，counterpart TM-score `>=0.70` 且 RMSD `<=3.50 Å`，resolved-core mean pLDDT `>=70`，两个 junction 均为 `1.15–1.55 Å`，且无 `<2.00 Å` 的非键合 loop/core heavy-atom clash。零个 Candidate 通过是允许的 scientific result；缺失 loop-scoped Evidence 不是。
- [ ] lawful 291/295/299-residue provider-free values 包含 6 对 Candidates、reconstruction、两组 confidence collections 和全部 PAE，并通过 public Projection、single-value retrieval、Artifact retrieval、events 和 Run Closure；本 ticket 不调用 Provider。
- [ ] 标记完成前，重跑 Tickets 01–14 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [ ] 当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。
