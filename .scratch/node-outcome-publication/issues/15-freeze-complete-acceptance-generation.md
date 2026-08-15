# 15 — 冻结完整 acceptance generation

**What to build:** 把 1PGA、2EMO、canonical 3GB1、5G53 与全部 installed Provider gates 组成一个可重现、zero-skip、严格串行的 current-generation 验收面，然后冻结将要产生真实证据的 source、artifact、Catalog、protocol 和 Provider assets/configuration。

**Blocked by:** 14 — 准备 source-bound 5G53 科学验收

**Status:** in-progress

- [x] 保留 canonical 3GB1 现有科学合同：10 个 paired ESM-3 Candidates、top 3 selection、每个 selected parent 的 5 个 ProteinMPNN designs（3×5，共 15 个）、15 个最终 folds/Artifacts 和 exact lineage/provenance，并将其全部切换到 descriptor/retrieval public contract。
- [x] 1PGA、2EMO、3GB1 和 5G53 分别具有 clean-source、zero-skip、retain-evidence acceptance tier；四个 tiers 的静态收集、input digests、current Catalog references 和 public journey contracts 全部通过，本 ticket 不执行 Provider calls。
- [x] installed Provider matrix 精确包含 Biohub ESMC、Biohub ESM-3、Biohub ESMFold2、local ESM-3、local ESMFold2、mkdssp、ProteinMPNN、SimpleFold folding、SimpleFold confidence、SoluProt 和 Protein-Sol，所有 tiers 都 zero-skip。
- [x] verification controller 只逐一启动 tier/Workflow child process，不使用 pytest-xdist、不并发调度、不嵌套 local-model processes；只有上一 child 退出并释放后才进入下一项。
- [x] 每个 local-model gate 在单一进程内只加载一个该模型实例，并对该 gate 内的全部 calls 复用；不按 sample、Candidate 或 test case 创建并发/重复实例。
- [x] evidence manifest 能绑定 source revision、installed artifact digest、public bundle/Catalog identities、四个 input digests、Provider asset/configuration identities、tier order 和每次 result；不引入 authentication、distributed lock 或 adversarial coordination。
- [x] 标记完成前，重跑 Tickets 01–15 的全部累计 public journeys、fault regressions 和 acceptance criteria，并确认无待补的 scientific evidence gap。
- [x] 冻结 checkout 前的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Completion evidence

The evidence below was valid for the superseded runtime-asset identity, but is
invalidated by the exact macOS 26.6 Perl/Bash bytes admitted during the ESMC-6B
asset re-freeze. It cannot authorize the new generation until the complete
matrix is rerun on the replacement clean revision.

- Frozen generation controller：`modules.acceptance_verification` 是 controller 与 verifier 共享且随 artifact 安装的唯一 tier authority；精确 11 个 installed Provider tiers 后接 1PGA、2EMO、canonical 3GB1、5G53。controller 单 child 串行、清除 `PYTEST_ADDOPTS`、无 xdist/重试，失败 result 先持久化再永久终止 generation。
- Documented entrypoint：新增回归从 `sys.path` 移除 repository root，经 `scripts/acceptance_generation.py` 的 parser `start` 路径真实构建 wheel/sdist 并生成 exact 11+4 manifest；built wheel 含 `modules/acceptance_verification.py`。生产代码没有 `sys.path` 修改、兼容路径或 fallback。
- Generation authority：非自引用地绑定 clean completion commit、单次构建的 wheel/sdist、public bundle、current Catalog、四个 source/workflow digests、有效 Provider configuration、经 contract owner 重验的本地 assets、exact tier contracts/order 和每次 retained result digest。
- Source-bound public contracts：四条 live selectors 静态精确收集；1PGA、2EMO、3GB1、5G53 的 descriptor/retrieval、readiness、Method/invocation、randomness、lineage、confidence、PAE、comparison/filter、Artifact association 与 scientific Evidence 均由 current public journey 断言；本 ticket 未执行 live selectors。
- Local-model residency：local ESM-3 gate 跨三种 generation modes 复用一个 client；installed ProteinMPNN gate 跨全部 Adapter/Operation/test 复用一个 resident model，source-bound ProteinMPNN 仍在切换 Protein-Sol 前释放 operation-scoped residency。
- Reopened focused verification：isolated CLI/artifact-build、tier authority、verifier 及 core provider-boundary regressions `26 passed`；`compileall` 与 `git diff --check` passed。Standards 与 Spec 两轴在最终 seam 上串行复审，均 `APPROVED`，无剩余 finding。
- 完整后端矩阵：`routine` 1307 passed / 48 deselected；`examples-v2` 12 passed；`deterministic-acceptance` 8 passed；`scientific-repro` 1 passed；`local-esmfold2-v2-contract` 6 passed；`installed-package` 3 passed；`provider-isolation` 16 passed；`security-failure` 10 passed。
- Frontend：Oxlint passed；`tsc -b && vite build` passed（179 modules）。全部验证严格串行，使用约定的 SoluProt root 与 loopback `NO_PROXY`；未调用 Provider、未加载本地模型、未进入 Ticket 16。
