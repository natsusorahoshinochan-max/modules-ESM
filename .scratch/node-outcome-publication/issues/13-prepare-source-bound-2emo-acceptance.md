# 13 — 准备 source-bound 2EMO 科学验收

**What to build:** 用 current Catalog 和固化 2EMO input 建立从 exact CSH parent-span normalization 到 ProteinMPNN、ESMFold2、confidence、structure comparison 和 Protein-Sol 的 public Workflow，并用 lawful provider-free values 闭合四个已锁定科学 filters。

**Blocked by:** 12 — 准备 source-bound 1PGA 科学验收

**Status:** ready-for-agent

- [ ] source-bound input 的 SHA-256 为 `6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700`，原始 structure 直接作为 Project Input。
- [ ] Workflow 精确记录 CSH A:66 到 A:65–A:67 parent span 的 normalization，保留 224-aa target 和 fixed parent-span sequence `SHG`，并显式说明 A:64–A:68 的 residue mapping。
- [ ] ProteinMPNN 使用 current Catalog exact Binding、`effective_seed=2066001`、`num_sequences=8`、`temperature=0.1` 和 backbone noise `0`；每个 sequence Candidate 保留 exact lineage 与 fixed-parent-span Evidence。
- [ ] 生成 Candidate 的独立 ESMFold2 folding 使用 current Catalog exact remote Binding、`effective_seed=2066002` 和单 sample；结构比较使用 candidate-associated CSH normalization 和 explicit residue correspondence，不在 Workflow 外修改坐标或 mapping。
- [ ] 每个 Candidate 发布 exact folding confidence 和 Protein-Sol scaled Observation，并精确应用 reference-normalized TM-score `>=0.80`、Cα RMSD `<=2.50 Å`、mean pLDDT `>=70` 和 Protein-Sol scaled `>=0.446` 四个 filters。
- [ ] 零个 Candidate 通过 filters 是可接受的 scientific conclusion；缺失 Candidate execution、normalization、comparison、Observation、lineage 或 Evidence 必须使 acceptance 失败。
- [ ] lawful provider-free fixtures 通过完整 public Run journey 证明 current Ports/Nodes 可表达全部 values、filters、retrieval 和 Run Closure；本 ticket 不调用 remote Provider，不加载 ProteinMPNN 或 Protein-Sol。
- [ ] 标记完成前，重跑 Tickets 01–13 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [ ] 当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。
