# 15 — 冻结完整 acceptance generation

**What to build:** 把 1PGA、2EMO、canonical 3GB1、5G53 与全部 installed Provider gates 组成一个可重现、zero-skip、严格串行的 current-generation 验收面，然后冻结将要产生真实证据的 source、artifact、Catalog、protocol 和 Provider assets/configuration。

**Blocked by:** 14 — 准备 source-bound 5G53 科学验收

**Status:** completed

- [x] 保留 canonical 3GB1 现有科学合同：10 个 paired ESM-3 Candidates、top 3 selection、每个 selected parent 的 5 个 ProteinMPNN designs（3×5，共 15 个）、15 个最终 folds/Artifacts 和 exact lineage/provenance，并将其全部切换到 descriptor/retrieval public contract。
- [x] 1PGA、2EMO、3GB1 和 5G53 分别具有 clean-source、zero-skip、retain-evidence acceptance tier；四个 tiers 的静态收集、input digests、current Catalog references 和 public journey contracts 全部通过；generation freeze 不执行 live selectors，一次独立的误选 Provider 事件按下文审计且不作为验收证据。
- [x] installed Provider matrix 精确包含 Biohub ESMC、Biohub ESM-3、Biohub ESMFold2、local ESM-3、local ESMFold2、mkdssp、ProteinMPNN、SimpleFold folding、SimpleFold confidence、SoluProt 和 Protein-Sol，所有 tiers 都 zero-skip。
- [x] verification controller 只逐一启动 tier/Workflow child process，不使用 pytest-xdist、不并发调度、不嵌套 local-model processes；只有上一 child 退出并释放后才进入下一项。
- [x] 每个 local-model gate 在单一进程内只加载一个该模型实例，并对该 gate 内的全部 calls 复用；不按 sample、Candidate 或 test case 创建并发/重复实例。
- [x] evidence manifest 能绑定 source revision、installed artifact digest、public bundle/Catalog identities、四个 input digests、Provider asset/configuration identities、tier order 和每次 result；不引入 authentication、distributed lock 或 adversarial coordination。
- [x] 标记完成前，重跑 Tickets 01–15 的全部累计 public journeys、fault regressions 和 acceptance criteria，并确认无待补的 scientific evidence gap。
- [x] 冻结 checkout 前的完整 provider-free repository matrix 全部通过：`routine`、`examples-v2`、`deterministic-acceptance`、`scientific-repro`、`local-esmfold2-v2-contract`、`installed-package`、`provider-isolation`、`security-failure`，以及 frontend Oxlint 和 TypeScript/build。

## Completion evidence

The generation authority at revision `7b6bd301591a7351cbfbdf95168b564fccd1de88`
is superseded and is not acceptance evidence. Its canonical 3GB1 gate inferred a
foreign-workspace ProteinMPNN root when the required configuration was absent,
so its manifest and all revision-bound completion results are invalid.

The generation authority at revision `c8326c3f43c72e2d59fb9f0b998dc9f0664eb08d`
is also superseded and is not acceptance evidence. Its immutable execution
stopped at the local ESMFold2 tier because the derived call seed exceeded the
official input builder's exact NumPy MT19937 seed domain; that manifest and its
retained prefix remain failure evidence and must not be retried or edited.

### Retained pre-failure freeze record

The following record describes the superseded `c8326c3...` authority and is
retained only to preserve its provenance. It is not current acceptance evidence.

- Frozen generation controller：`modules.acceptance_verification` 是 controller 与 verifier 共享且随 artifact 安装的唯一 tier authority；精确 11 个 installed Provider tiers 后接 1PGA、2EMO、canonical 3GB1、5G53。controller 单 child 串行、清除 `PYTEST_ADDOPTS`、无 xdist/重试，失败 result 先持久化再永久终止 generation。
- Documented entrypoint：新增回归从 `sys.path` 移除 repository root，经 `scripts/acceptance_generation.py` 的 parser `start` 路径真实构建 wheel/sdist 并生成 exact 11+4 manifest；built wheel 含 `modules/acceptance_verification.py`。生产代码没有 `sys.path` 修改、兼容路径或 fallback。
- Generation authority：非自引用地绑定 clean completion commit、单次构建的 wheel/sdist、public bundle、current Catalog、四个 source/workflow digests、有效 Provider configuration、经 contract owner 重验的本地 assets、exact tier contracts/order 和每次 retained result digest。
- Exact asset re-freeze：按 owner contract provision `biohub/ESMC-6B@45b0fa5d7fb06faefbd5e3b89bdcef35d564e79a` 的 11 个 manifest objects；ESMFold2 owner admission 得到 `sha256:fba1f5f47122ab623f4a4bbfd3011622e7f7a954dbdd80238bea95bcb396d8db`。完整 configuration/asset preflight 同时闭合 local ESM-3、mkdssp、ProteinMPNN、SimpleFold、SoluProt、Protein-Sol 及 exact macOS 26.6 Perl/Bash identities；没有替代 revision、fallback、Provider call 或 model load。
- Source-bound public contracts：四条 live selectors 静态精确收集；1PGA、2EMO、3GB1、5G53 的 descriptor/retrieval、readiness、Method/invocation、randomness、lineage、confidence、PAE、comparison/filter、Artifact association 与 scientific Evidence 均由 current public journey 断言；本 ticket 未执行 live selectors。
- Canonical 3GB1 configuration authority：public gate 只接受显式 absolute `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT`，在任何 live setup 前拒绝 unset、empty 或 relative value，并只把 `resolve(strict=True)` 后的同一目录传入 installed child；foreign-workspace fallback 已删除。RED→GREEN 回归覆盖 unset、relative 与 explicit valid root。
- Local-model residency：local ESM-3 gate 跨三种 generation modes 复用一个 client；installed ProteinMPNN gate 跨全部 Adapter/Operation/test 复用一个 resident model，source-bound ProteinMPNN 仍在切换 Protein-Sol 前释放 operation-scoped residency。
- Re-freeze focused verification：acceptance controller、canonical 3GB1、source-bound journeys、Protein-Sol、SoluProt 和 verification tier contracts 共 `78 passed / 4 deselected`；`compileall` 与 `git diff --check` passed。Standards 与 Spec 两轴在 explicit ProteinMPNN authority seam 上串行复审，均 `APPROVED`，无剩余 finding。
- 完整后端矩阵：`routine` 1308 passed / 48 deselected；`examples-v2` 12 passed；`deterministic-acceptance` 8 passed；`scientific-repro` 1 passed；`local-esmfold2-v2-contract` 6 passed；`installed-package` 3 passed；`provider-isolation` 16 passed；`security-failure` 10 passed。
- Frontend：Oxlint passed；`tsc -b && vite build` passed（179 modules）。全部验证严格串行，使用约定的 SoluProt root 与 loopback `NO_PROXY`；未调用 Provider、未加载本地模型、未进入 Ticket 16。

### Current completion evidence

- Local ESMFold2 failure diagnosis：在旧 generation 之外只运行一次 exact frozen installed diagnostic，单 child、单模型实例且无并发；durable Run 记录的 call seed 为 `3193293576546208`。不加载模型的精确上游探针证明 pinned ESMFold2 `_seed_context` 把该值传给 `np.random.seed()`，因超过 NumPy MT19937 的 unsigned 32-bit seed domain 而抛出同一 `ValueError`。CCD/RDKit warnings 不是原因，模型进程已释放；旧 failed generation 没有重试或改写。
- Scientific contract repair：local ESMFold2 call-seed derivation 切换为 `protein-workbench-esmfold2-call/v3`，仍由 configured base seed、canonical parent content digest、parent slot 和 sample slot 精确决定，但只把 SHA-256 前四个 bytes 解释为 unsigned big-endian integer。由 owning derivation boundary 直接产出 provider Python、NumPy MT19937、Torch shared seed context 的合法精确值；没有 catch、fallback、retry、response repair 或模型替换。
- Version cascade：local Method `folding.fold.esmfold2_hf_1ebf0e3` 升至 `5.0.0`，local Binding `folding.fold.esmfold2_local` 升至 `7.0.0`，folding package 升至 `6.0.0`；remote ESMFold2 Method/Binding、SimpleFold Method/Binding 与 fold Node Type 版本保持不变。current Catalog、capability inventory 与 repository workflow locks 已整体更新。
- RED→GREEN 与双轴复审：固定输入 seed 精确为 `299330669`，并断言所有派生值在 `0..2^32-1`、Candidate rename 不改变 seed、内容改变必须改变 seed；provider-free focused selection `46 passed`。Standards 与 Spec 先后 `APPROVED`，无剩余 finding。
- Current cumulative re-freeze gates：`routine` 1308 passed / 48 deselected；`examples-v2` 12 passed；`deterministic-acceptance` 8 passed；`scientific-repro` 1 passed；`local-esmfold2-v2-contract` 6 passed；`installed-package` 3 passed；`provider-isolation` 16 passed；`security-failure` 10 passed；frontend Oxlint passed，`tsc -b && vite build` passed（179 modules）；`compileall` 与 `git diff --check` passed。全部门禁严格串行，未加载本地模型、未进入 Ticket 16。
- Non-acceptance audit incident：focused 命令曾误选两个 `live_provider` tests；临时 Ledger 与测试的 exact call assertions 证明 Biohub ESM-3 执行 8 次、Biohub ESMFold2 执行 1 次，共 9 次成功 remote Provider calls。它们不属于 acceptance generation、不写入 generation manifest、未用于任何 completion/Ticket 16 evidence；其余本轮门禁均使用精确 provider-free tiers，且事故后未再调用 Provider 或加载模型。
