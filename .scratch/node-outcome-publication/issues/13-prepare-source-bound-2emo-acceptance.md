# 13 — 准备 source-bound 2EMO 科学验收

> Historical completion evidence only. Checksums, symlink/security probes, Readiness-before-Cache, restart reconstruction, and old verification tiers mentioned below are not current requirements.

**What to build:** 用 current Catalog 和固化 2EMO input 建立从 exact CSH parent-span normalization 到 ProteinMPNN、ESMFold2、confidence、structure comparison 和 Protein-Sol 的 public Workflow，并用 lawful provider-free values 闭合四个已锁定科学 filters。

**Blocked by:** 12 — 准备 source-bound 1PGA 科学验收

**Status:** completed

- [x] source-bound input 的 SHA-256 为 `6ef4ef3102a71793373b5767b9a1a1cbbc324996527d1c9b3e7ebd00cf7b6700`，原始 structure 直接作为 Project Input。
- [x] Workflow 精确记录 CSH A:66 到 A:65–A:67 parent span 的 normalization，保留 224-aa target 和 fixed parent-span sequence `SHG`，并显式说明 A:64–A:68 的 residue mapping。
- [x] ProteinMPNN 使用 current Catalog exact Binding、`effective_seed=2066001`、`num_sequences=8`、`temperature=0.1` 和 backbone noise `0`；每个 sequence Candidate 保留 exact lineage 与 fixed-parent-span Evidence。
- [x] 生成 Candidate 的独立 ESMFold2 folding 使用 current Catalog exact remote Binding、`effective_seed=2066002` 和单 sample；结构比较使用 candidate-associated CSH normalization 和 explicit residue correspondence，不在 Workflow 外修改坐标或 mapping。
- [x] 每个 Candidate 发布 exact folding confidence 和 Protein-Sol scaled Observation，并精确应用 reference-normalized TM-score `>=0.80`、Cα RMSD `<=2.50 Å`、mean pLDDT `>=70` 和 Protein-Sol scaled `>=0.446` 四个 filters。
- [x] 零个 Candidate 通过 filters 是可接受的 scientific conclusion；缺失 Candidate execution、normalization、comparison、Observation、lineage 或 Evidence 必须使 acceptance 失败。
- [x] lawful provider-free fixtures 通过完整 public Run journey 证明 current Ports/Nodes 可表达全部 values、filters、retrieval 和 Run Closure；本 ticket 不调用 remote Provider，不加载 ProteinMPNN 或 Protein-Sol。
- [x] 标记完成前，重跑 Tickets 01–13 的全部累计 public journeys、fault regressions 和 acceptance criteria；任何回归都阻止完成。
- [x] 当前 checkout 的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Completion evidence

- Exact public Workflow：`examples/v2/source-bound-2emo.workflow.json`，覆盖固化 2EMO Project Input、CSH parent-span normalization、ProteinMPNN、ESMFold2、candidate-associated comparison、confidence、Protein-Sol 与四个 exact filters。
- Public acceptance：`tests/test_source_bound_2emo_v2.py`，覆盖 SHA-256、224-aa `SHG`、A:64–A:68 mapping、exact parameters/lineage、8 条 224-CA alignments、TM/RMSD Evidence digests、confidence/Protein-Sol Observation contracts、nonzero/zero-pass outcomes 和 evidence-gap rejection。受控 folding fixture 只发布已有 N/CA/C/O 主链坐标与 TER/END，不复制 source 侧链、ligand 或 solvent。
- Current Catalog：新增 candidate normalization facts/materialization、single-residue-axis projection、parent-child selection 与 four-way Candidate intersection；Port canonical content identity 由唯一 Port Type owner 负责，producer 不重复 admission validation。
- Code review：Spec、Standards 与 Python 三项最终复审均 `APPROVED`；无未解决 CRITICAL/HIGH/MEDIUM/LOW finding。
- 最终累计 backend gates：`routine` 1292 passed；`examples-v2` 12 passed；`deterministic-acceptance` 8 passed；`scientific-repro` 1 passed；`local-esmfold2-v2-contract` 6 passed；`installed-package` 3 passed；`provider-isolation` 16 passed；`security-failure` 10 passed。
- Frontend gates：Oxlint、TypeScript 与 production build 全部通过（179 modules）。
- 全程严格串行，使用 `NO_PROXY` 与已约定 SoluProt source root；未调用 remote Provider、未加载 ProteinMPNN/Protein-Sol/local models、未使用 pytest-xdist、未进入 Ticket 14。
