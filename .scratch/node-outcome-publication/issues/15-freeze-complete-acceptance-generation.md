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

### Reopened after repeated Biohub ESM-3 generation failures

The `19d3284...` completion is superseded as current acceptance evidence. Two
independent generations at that exact clean HEAD, artifact, Catalog, protocol,
assets, and configuration both retained `installed-biohub-esmc=passed` and then
terminated `installed-biohub-esm3=failed` with durable `AttributeError`. The
first failed during Biohub medium `generate_structure`; the second failed during
the Biohub medium paired `structure_child`. Both generation roots and their
prefixes remain immutable and must not be retried, edited, or combined.

- Controlled reproduction budget：一次 temporary untracked installed-wheel reproduction 驱动完整 8-invocation public journey；8 个 requests 与 8 个 responses 全部精确记录，所有 responses 都是官方 `esm.sdk.api.ESMProtein`，测试 `1 passed`。raw output 保存在 `verification-results/ticket15-biohub-esm3-controlled-reproduction-19d3284/raw-output.txt`，SHA-256 `d3f3fffc69f0749a43f7a2fa2db3985702f55a52dad53c1a05faed552c312d46`。该 reproduction 未进入 generation manifest，之后不再调用 Provider。
- Provider-call audit：最初误选 live tests 为 ESM-3 8 calls + remote ESMFold2 1 call；generation 外 direct ESM-3 diagnostic 为 1 call；第一次完整 uninstrumented ESM-3 diagnostic 为 8 calls；本次唯一 controlled reproduction 为 8 calls。一次 diagnostic interpreter 预备失败发生在 import 前且为 0 calls。以上均不是 acceptance evidence；两个 Ticket 16 failed generations 的 retained results 独立保存在各自 generation root。
- Official-contract audit：pinned SDK 的 `ProteinType` 明确包含 `ESMProteinError`，Forge `generate()` 与 `__generate_protein()` 明确返回 `ESMProtein | ESMProteinError`，且 ADR-0015 要求 returned error member 成为 Operation failure。production Adapter 已拥有该分类边界；installed acceptance `RecordingESM3Client` 却在返回 Adapter 前访问 `.sequence/.ptm/.plddt/.pae`，静态违反官方 union。
- Provider-free RED→GREEN：使用官方 `ESMProteinError(503, "provider unavailable")` 精确复现同一 `AttributeError: 'ESMProteinError' object has no attribute 'sequence'`。修复只让 recorder 原样转发 documented error member，并由现有 Adapter 转为明确 `RuntimeError` Operation failure；官方 error object 作为 exception cause 保留。没有 schema guessing、response repair、fallback、retry、cross-check 或额外 Provider validation。
- Contract scope：ESM-3 scientific Method、Execution Binding、Node Type、request、normal successful-response translation 与 package contract 均未改变，因此不创建虚假的 Method/Binding version cascade；当前变更只恢复既有 documented provider non-success 和 acceptance harness 语义。focused provider-free suites `39 passed`。
- Final dual-axis review：Standards 与 Spec 均 `APPROVED`，确认 recorder 只原样转交官方 union error member，owning Adapter 将其转为既有 Operation failure 并保留 exact cause；无 defensive response handling、repair、retry、fallback 或科学合同/版本变更。
- Final cumulative provider-free gates：`routine` 1309 passed / 48 deselected；`examples-v2` 12 passed；`deterministic-acceptance` 8 passed；`scientific-repro` 1 passed；`local-esmfold2-v2-contract` 6 passed；`installed-package` 3 passed；`provider-isolation` 16 passed；`security-failure` 10 passed；frontend Oxlint passed，`tsc -b && vite build` passed（179 modules）；`compileall` 与 `git diff --check` passed。全部门禁严格串行，`HF_HUB_OFFLINE=1`，未调用 Provider、未加载本地模型、未进入 Ticket 16。

### Reopened after the local ESMFold2 CPU precision failure

The `2401739c5da4a385f6d0216b94c5747b71a1bdac` completion and frozen
generation are superseded and are not current acceptance evidence. That
immutable generation retained four passed prefix tiers, then terminated at
`installed-local-esmfold2=failed`; its manifest remains at
`verification-results/acceptance-generation-2401739-ticket15-reboot-stable-refreeze/generation.json`
with SHA-256
`4cfcda2547dd6aeb5700bb4a02863afb15856eb41693d7254d255d72e6214ad4`.
It must not be retried, edited, or combined with a later generation.

- Controlled diagnosis：在 failed generation 之外只运行一次 exact installed local ESMFold2 diagnostic，单 child、单模型实例且无并发；实际 call seed 为 `3806398562`，forward 终止于 `RuntimeError: expected m1 and m2 to have the same dtype, but got: c10::BFloat16 != float`。raw output 保存在 `verification-results/ticket15-local-esmfold2-controlled-diagnostic-2401739/raw-output.txt`，SHA-256 为 `b51d1b3d7b0cf49e29b7bc83a80247c768c3c6fc27c03a7c8a7f0463e1a7d05d`；该 diagnostic 不是 acceptance evidence，模型进程已退出。
- Scientific contract repair：pinned transformers ESMFold2 loader 的官方 `esmc_precision` 参数从 CPU 上不合法的 implicit `bf16` default 切换为 exact `fp32`。ESMC snapshot、ESMFold2 snapshot、device、种子、fold 参数、输出语义与资产 digests 均不变；没有 catch、fallback、retry、Provider response repair 或模型替换。
- Exact identity cascade：precision 纳入 Method model identity、Binding readiness/implementation/route identity 和 `protein-workbench-local-esmfold2-runtime/v3` fingerprint。local Method `folding.fold.esmfold2_hf_1ebf0e3` 升至 `6.0.0`，local Binding `folding.fold.esmfold2_local` 升至 `8.0.0`，folding package 升至 `7.0.0`；remote ESMFold2、SimpleFold 和 shared fold Node Type 版本不变。current Catalog、capability inventory 和 repository Workflow lock 已整体更新。
- TDD seams：public Method/Binding/FrozenCatalog contract、official installed engine-load precision seam、runtime fingerprint/readiness evidence 与 capability/version cascade 均由 provider-free tests 闭合。针对双轴审查发现的唯一 partial test-closure finding，在 isolated `2401739` worktree 中新 package/fingerprint tests 精确 RED 为 2 failed，当前 implementation GREEN 为 3 passed；最终 focused selection `37 passed / 7 deselected`，明确排除 `live_provider` 和 `local_provider`。
- Current cumulative provider-free gates：`routine` 1312 passed / 48 deselected；`examples-v2` 12 passed；`deterministic-acceptance` 8 passed；`scientific-repro` 1 passed；`local-esmfold2-v2-contract` 6 passed；`installed-package` 3 passed；`provider-isolation` 16 passed；`security-failure` 10 passed；frontend Oxlint passed，`tsc -b && vite build` passed（179 modules）；`compileall` 与 `git diff --check` passed。provider-isolation 的第一次 invocation 因执行 shell 未传入必需的 `PROTEIN_WORKBENCH_SOLUPROT_ROOT` 而不是 gate evidence；显式使用与 superseded manifest identity 匹配的 trusted root 后精确重跑为 16 passed。全部有效门禁严格串行，`HF_HUB_OFFLINE=1`，未调用 Provider、未加载本地模型、未进入 Ticket 16。
- New freeze boundary：新 authority 必须由本 Ticket 的 clean completion commit 通过 `scripts/acceptance_generation.py start` 创建，以避免 source revision 自引用。`start` 只构建 wheel/sdist、验证 Provider assets/configuration 并写入无 result 的 manifest；Ticket 15 不执行任何 Ticket 16 Provider tier。
