# Workflow usability debug：2026-08-03 修复后复测

状态：修复后正式复测完成；三个理论 Workflow 仍无一达到 `FULLY_USABLE`。本轮只记录
缺口和 Evidence，未修改实现。

## 1. 执行边界与快照

- 分支：`codex/workflow-usability-repair`；
- Git HEAD：`ea9d5658177a36286a2cad9ec73ab0f0e15db7c6`；
- 被复测修复的 parent：`47e1b85cedfeb3a2ab46fdc93e8822c21e982272`；
- FrozenCatalog contract digest：
  `sha256:9eda73b50a0d6f63076b034ee6be68a9a67c75bc5248c827b0c8cc21893a5e9f`；
- Catalog 含 62 个 Node Type、73 个 Execution Binding、69 个 Method、32 个 Port Type、
  14 个 Metric 和 2 个 Utility Transform；
- 当前 React 前端按任务约定排除在测试范围外；唯一验收 surface 为 public v2
  REST/WebSocket protocol；
- 输入为 Git 管理的 `pdbs/1PGA-75-gen1_0690.pdb`、`pdbs/2EMO.pdb` 和
  `pdbs/5G53.pdb`；
- 未安装依赖、未补下载模型资产、未修改 credential，也未用外部结构/序列处理绕过
  Workbench 合同；
- `verification-results/` 中的 runtime、public responses、Ledger 和 console log 均为本轮
  原始 Evidence，不属于实现修改，也不应提交。

本轮先执行能力链路测试；只有完整链路产生终态和要求的科学 Observation 后，才允许进入
端到端科学判定。没有终态的 Run 不得按 provider 调用成功或中间 output 推断为成功。

## 2. 基线验证结果

### 2.1 Provider-free gates

| Gate | 结果 | Evidence |
|---|---:|---|
| `routine` | 1190 passed | `verification-results/routine/20260803T122126.681308Z-42970-b754fd8f4bc4c6df/` |
| `deterministic-acceptance` | 8 passed | `verification-results/deterministic-acceptance/20260803T122407.930942Z-48561-a30cd9e6167ce479/` |
| `examples-v2` | 12 passed | `verification-results/examples-v2/20260803T122422.914636Z-49081-7eaaf7e119e7efb8/` |
| `scientific-repro` | 1 passed | `verification-results/scientific-repro/20260803T122425.531540Z-48560-629f86d11e1bfac5/` |
| `installed-package` | 3 passed | `verification-results/installed-package/20260803T122455.364620Z-49532-45a04666c33b8f3d/` |
| `local-esmfold2-v2-contract` | 6 passed | `verification-results/local-esmfold2-v2-contract/20260803T122459.989706Z-49531-5f02c9babc81fdb2/` |

### 2.2 当前环境中的真实 provider gates

| Gate | 结果 | Evidence |
|---|---|---|
| Biohub ESM C | passed | `verification-results/installed-biohub-esmc/20260803T122525.661111Z-49814-a03aca94a411eab9/` |
| Biohub ESM-3 | passed | `verification-results/installed-biohub-esm3/20260803T122557.767791Z-49949-838145141167528b/` |
| Biohub ESMFold2 | first failed, immediate rerun passed | `verification-results/installed-biohub-esmfold2/20260803T122621.223072Z-50292-f1135783fa3fdda6/` 与 `verification-results/installed-biohub-esmfold2/20260803T122659.684162Z-50510-8b479aa790b62985/` |
| local ESM-3 | passed | `verification-results/installed-local-esm3/20260803T122815.786782Z-50674-333c0e5b80d9f125/` |
| mkdssp | passed | `verification-results/installed-mkdssp/20260803T122833.470041Z-51006-b83fe8ed6372a4c5/` |
| ProteinMPNN | passed | `verification-results/installed-proteinmpnn/20260803T122849.693755Z-51100-42154860c08ea0a3/` |

Biohub ESMFold2 的第一次失败只保留了公开 `node_execution_failed` / `RuntimeError`，同一
命令随即通过。因此它是一个暂时性、原因不透明的 observation，不足以单独判为稳定回归。

当前环境未提供以下五个真实 gate 所需的受信模型资产：local ESMFold2、SimpleFold
folding、SimpleFold confidence、SoluProt 和 Protein-Sol。本轮不为测试补装资产；其缺失
按 `availability_gap` / `readiness_gap` 原样记录。

## 3. 三个 Workflow 结果总览

| 顺序 | 输入 | Workflow Commit | Phase 1 | 顶层状态 | 最早阻断/失败 |
|---:|---|---|---|---|---|
| 1 | `1PGA-75-gen1_0690.pdb` | `workflow-commit-da0c8353592aaa1518379a9872972bf4e7eaf3c4f56e0d70428f8ae8065159db` | compile succeeded；Run admission 503 | `SAFELY_BLOCKED` | SimpleFold `readiness_gap` |
| 2 | `2EMO.pdb` | `workflow-commit-fa2598801b72cf99a905800c32a07c77c1be15bf95ec65633f0c999db0fde6de` | compile succeeded；Run admission 503 | `SAFELY_BLOCKED` | Protein-Sol `readiness_gap`；另有候选结构归一化 `composition_gap` |
| 3 | `5G53.pdb` | `workflow-commit-1e1b77fa200cb82194521f6c5fa8fd443197cf4f55e8eed092a024740ec1eada` | admitted；稳定停在同一 publication seam | `OPAQUE_FAILURE` | `execution_gap` + `evidence_gap` |

三个 Workflow 的 Phase 2 均未完成。不能作 three-way consistency、GFP 设计质量、
resolved-core、loop、junction、clash 或 confidence 阈值结论。

## 4. Finding `WFRET-5G53-001`：Operation 成功后的 output publication 失败不产生终态

严重度：高；分类：`execution_gap` + `evidence_gap`；顶层状态：`OPAQUE_FAILURE`。

### 4.1 准确复现范围

- Project ID：`9575bb9d-f0b3-4381-b866-4186d82a4937`；
- Workflow Commit：
  `workflow-commit-1e1b77fa200cb82194521f6c5fa8fd443197cf4f55e8eed092a024740ec1eada`；
- primary Run：`run-ed4d7ca98825406598f9a72be3993760`；
- confirmation Run：`run-bb061283112f4f91ad99ecb73fb863a3`；
- confirmation 使用相同 Project、Workflow Commit、Catalog、Execution Binding、输入和
  Node parameters；没有改写 Workflow；
- shorter 分支固定为 8 个插入 residue、seed `5353008`、2 samples、20 steps、
  temperature `0.7`、top-p `1.0`、cosine/random、temperature annealing；
- 两次都在 `generate-shorter` 的相同边界复现。

### 4.2 已由 durable/public Evidence 证明的事实

primary Run 中，`generate-shorter` 的四个 ESM-3 Engine Invocation 全部为
`succeeded`；sequence 122 为 `operation_attempt_terminal=succeeded`，随后没有
`outputs_published`、`node_attempt_terminal` 或 `node_disposition`。原始 driver 在用户判定
测试失败后由 `KeyboardInterrupt` 停止。confirmation app 后续加载同一 runtime 时，才以
restart reconciliation 将该旧 Run 标为 `interrupted`；这不是原 worker 自己产生的终态。

confirmation Run 复现了同一顺序：

1. sequence 80：`generate-shorter` Node Attempt started；
2. sequence 81：Operation Attempt started；
3. sequence 82–89：四个真实 ESM-3 Engine Invocation started/terminal，四个均
   `succeeded`；
4. sequence 90：Operation Attempt terminal `succeeded`；
5. 之后 121.3 秒没有 Node terminal 或 output publication；
6. watchdog 通过 public cancel endpoint 请求取消，sequence 91 得到
   `cancellation_requested`；
7. 再观察 60 秒，public Projection 仍为 `running`、无 `terminal_sequence`；
8. public event stream 仍未关闭；TestClient shutdown 不能自然完成，最终由
   `KeyboardInterrupt` 退出并保留 traceback。

确认 Run 在此前九个 Node Instance 均有成功 disposition，`generate-shorter` 之前公开
Projection 有 14 个 outputs；没有生成 artifact。失败不是 ESM-3 provider terminal
failure，也不是 authoring、compile、Run admission、Prompt insertion 或 Result Cache replay
失败。

### 4.3 最早失效 seam

当前实现只有在 raw outputs 已完成 Candidate normalization、Port admission、artifact
materialization 和 Result Cache publish 后，才在 `commit_node_publication` 内写成功的
`operation_attempt_terminal`。下一条预期 Ledger fact 是 `outputs_published`。

因此，本轮能证明的最早失效 seam 是：

```text
Operation Attempt terminal = succeeded
→ [缺失：outputs_published]
→ [缺失：Node Attempt terminal]
→ [缺失：Node disposition]
→ [缺失：Run terminal]
```

取消事实能够随后取得 Ledger ordering lock 并写为 sequence 91，排除了 worker 一直持有
publication lock 的简单死锁解释。当前 `start_background` 会捕获 worker 的
`BaseException`，但只把异常保存在进程内 `record.execution_error` 并设置 finished event；
在 HTTP admission receipt 已返回后，该异常没有被转成 durable/public terminal Evidence。
所以 worker 即使已经退出，public Run 仍可永久显示 `running`，之后的取消也没有执行者收束。

### 4.4 最可信的直接触发因素（代码级推断，不是公开 Run Evidence）

`outputs_published` 把每个 output Port 的完整 wire `values` 放入单个 Ledger fact，而单个
fact 上限为 4 MiB。shorter Prompt 有 291 residues；两个 ESM-3 paired samples 可携带完整
sequence/structure Candidate、pairing、per-residue pLDDT、pTM、PAE，以及 provider 返回时的
可选 sequence reconstruction confidence。这个 payload 很可能越过单 fact 上限。

若越界，`RunLedger.append` 会在写入 `outputs_published` 前抛出
`V2RunError(evidence_unavailable)`；调用方会继续上抛，background worker 捕获后退出，却不写
Node/Run terminal。这一控制流与两轮 Ledger 序列、Result Cache rollback、取消仍能取得锁、
以及 public Projection 永久 `running` 完全一致。测试时磁盘仍有 113 GiB 可用，重复性也不
支持普通空间耗尽。

由于当前系统没有持久化 background execution exception，本轮不能从 public Evidence
证明具体异常一定是 4 MiB bound，而只能把它列为最高可信根因。即使直接触发最终被证明为
schema validation 或 durable write error，publication exception 未被 terminalize 的缺口仍然
成立。

### 4.5 修复后必须满足的复测条件

- Operation 成功后的 output publication 要么完整提交，要么产生结构化、持久化的失败终态；
- background worker 在 admission receipt 返回后抛出的异常必须能从 public Projection 和
  Run Evidence 定位，不能只留在内存；
- `outputs_published` 的 evidence 表达和大小合同必须能承载该 Node Type 声明允许的真实
  `num_samples`、structure 和 confidence 输出，或在 Run 前给出准确、可解释的 bound；
- 对已退出 worker 的 cancel 必须返回真实终态或准确说明执行已经失败，不能留下永久
  `running`；
- 使用相同 5G53 Workflow Commit 复测时，至少要越过 `generate-shorter` 的 Node terminal；
  未越过不得继续评价后续两个长度分支或 Phase 2 科学结果。

### 4.6 Evidence

- confirmation 完整 console：
  `verification-results/workflow-usability-debug/2026-08-03/5g53-confirmation/driver-console.log`；
- confirmation public events：同目录
  `public/run-events.live.jsonl`；
- public admission、cancel、Projection、event-reader state 和 summary：同目录 `public/`；
- primary admission 与原始终止记录：
  `verification-results/workflow-usability-debug/2026-08-03/current-run/public/5g53/`；
- 两个 Run 的 durable Ledger：
  `verification-results/workflow-usability-debug/2026-08-03/current-run/runtime/runs/9575bb9d-f0b3-4381-b866-4186d82a4937/`。

上述 confirmation log 和 public Evidence 已保留，未删除或覆盖。

## 5. Finding `WFRET-RUN-001`：Readiness rejection 留下无公开 Run ID 的 orphan Run

严重度：高；分类：`evidence_gap` / Run lifecycle gap。

1PGA-75 和 2EMO 均成功 authoring/compile，但 `start_run` 分别以结构化 503 拒绝：

- 1PGA-75：`folding.fold.simplefold_local@6.0.0`，
  `simplefold_runtime_unavailable`；
- 2EMO：`solubility.protein_sol.local@4.0.0`，
  `protein_sol_runtime_unavailable`。

这两个公开响应本身是正确的 `readiness_rejected`，且没有返回 Run ID；但 runtime 中分别
留下：

- `run-338252cd1d844302ba4e611f23078f85`：manifest `status=admitted`，11 个 facts，
  无 `terminal_sequence`；
- `run-12bd570c37044a959226d3adc45131e3`：manifest `status=admitted`，19 个 facts，
  无 `terminal_sequence`。

两者最后一条 fact 都是 readiness attestation，且因 public response 没有 Run ID，用户不能
通过 public API 检查、取消或解释这些 durable Run。Readiness rejection 应当不建立 durable
Run，或必须返回一个可检查且 terminal 的准确 Run identity；当前状态同时污染 runtime 和
Evidence 语义。

Evidence：

- `verification-results/workflow-usability-debug/2026-08-03/current-run/public/1pga-75/run-admission.json`；
- `verification-results/workflow-usability-debug/2026-08-03/current-run/public/2emo/run-admission.json`；
- 对应 runtime 位于
  `verification-results/workflow-usability-debug/2026-08-03/current-run/runtime/runs/`。

## 6. Finding `WFRET-2EMO-001`：CSH normalization 缺少 Candidate-associated producer

严重度：高；分类：`composition_gap`。

当前 Catalog 的 `structure_transform.normalize_csh_parent_span@5.0.0` 只产生单值
`protein.structure` 和 `structure_transform.modified_residue_normalizations`；
`structure_transform.resolve_candidate_residue_axes@5.0.0` 若要为 Candidate Collection
应用同一 normalization，则需要
`structure_transform.candidate_modified_residue_normalization_associations`。

当前 62 个 Node Type 中没有任何 output Port 生产该 Port Type。因此 2EMO 可以在单值路径
建立规范化后的 residue axis、Prompt 和 identity-addressed constraints，却无法把规范化的
CSH 结构准确连接为 ProteinMPNN 所需的 structure Candidate 与 associated residue axis。
本轮提交的 Workflow 只能让 ProteinMPNN Candidate 路径使用未规范化的原始 import
Candidate；这不满足理论 Workflow 的科学合同。

Protein-Sol Readiness 在 Run admission 阶段更早地阻断了实际执行，所以本缺口来自当前
public Catalog 的静态 composition 检查，不冒充该 Run 已执行到 ProteinMPNN 的动态结果。

Evidence：

- `verification-results/workflow-usability-debug/2026-08-03/current-run/public/catalog.json`；
- `verification-results/workflow-usability-debug/2026-08-03/current-run/public/2emo/workflow-source.json`。

## 7. Finding `WFRET-5G53-002`：Phase 2 的 loop-specific 判定能力仍未闭合

严重度：中；分类：`contract_gap`。

当前 Catalog 已有 fixed-reference/counterpart alignment、TM-score、RMSD，以及 confidence
materialization，但没有 junction geometry、steric clash 或把 per-residue pLDDT 按新增 loop
residue scope 汇总/判定的 Node Type。因而即使 `WFRET-5G53-001` 修复，当前 Workflow 仍
不能完整实现测试合同要求的：

- 两端 junction C–N/连续性检查；
- 新生成 loop 与 receptor core 的 clash 检查；
- 新增 loop scope 的 mean-residue pLDDT 判定。

本轮 Run 未进入这些 Node，因此这是 Catalog capability 缺口，不是运行时 observation。

## 8. 结论与后续复测门槛

修复已经把三个样例从首轮的 authoring/compile 缺口推进到：1PGA-75 与 2EMO 可 compile，
5G53 可实际调用 ESM-3。这证明修复提供了真实能力增量，但当前任务要求仍未闭合：

1. 1PGA-75 被 SimpleFold Readiness 安全阻断；
2. 2EMO 被 Protein-Sol Readiness 安全阻断，并仍缺 Candidate-associated CSH normalization
   composition；
3. 5G53 在真实 ESM-3 Operation 成功后发生稳定的 output publication / terminal evidence
   失败，且取消不能收束；
4. 5G53 的 loop-specific Phase 2 能力仍不完整；
5. 没有任何样例产生允许端到端科学判定的完整 Run terminal 和 Observation 集合。

因此本轮不能把项目判为 Workflow-usable，也不能用 provider gate 通过替代完整 Workflow
验收。

本轮未修改 `core/`、`modules/`、`datatypes/`、public protocol、测试或前端。对 current-run
和 confirmation 共 331 个 Evidence 文件执行 credential byte scan，命中数为 0。
