# Provider acceptance 调用与翻译契约调研

- 状态：已被当前架构与单阶段 Acceptance Campaign 取代的非规范历史调研
- 日期：2026-08-03
- 范围：mkdssp、ProteinMPNN design/score/chain-order、local ESMFold2、Biohub ESMC/ESM-3/ESMFold2 Binding、SimpleFold confidence、Protein-Sol、SoluProt
- 调研边界：初始调研没有调用真实 Provider；实施阶段执行了当前机器上可用的零跳过安装包门禁，并对 Biohub ESMC 返回 tensor 形状做了只输出类型、shape 与 dtype 的真实探针

不得按下文恢复 monkeypatch observer、digest-heavy gate、Provider cross-check
或旧修复顺序。SoluProt 当前明确是 project-maintained port，不声称与官方
release 等价。已经吸收进当前 Method、Adapter 与科学测试的结论仍有效；当前
权威状态以 `protein_workbench_architecture.md` 和 `backend-verification.md` 为准。

## 2026-08-03 实施后更新

本文件下文保留发现问题时的证据与修复理由；其中描述的 ProteinMPNN mask/seed/chain-order、mkdssp identifier mapping、ESM-3/ESMFold2 翻译以及真实 Provider 门禁缺口已经在本轮后端修复中处理。最新门禁结果应以 `verification-results/` 中对应 tier 的保留证据为准。

真实 Biohub ESMC 门禁另外揭示了一个 Mock 未覆盖的科学合同错误：锁定 SDK revision `917af90b624535eed1e072d343c717e3ec11fef4` 的真实服务返回 `mean_embedding` shape `(1, 1, 1152)`，`logits.sequence` shape `(L + 2, 64)`。固定 SDK 的 `ESMCForgeInferenceClient._process_logits_response` 仅把服务值转为 float32 tensor，不会添加或删除 batch 轴；上游 cookbook 也明确把 sequence logits 记为 `(L + 2, V)`。原 Adapter 读取 `mean_embedding[0]` 并把 logits 合同写成 `(1, L + 2, 64)`，因此两个 Provider 调用成功后仍以 `TypeError` 失败。

修复后的唯一翻译是：从官方返回的 `(1, 1, 1152)` 取 `[0, 0]`，发布 canonical 1152-vector；原样记录锁定 SDK 规范化后的 `(L + 2, 64)` logits shape。该 axis 是 `CLS + L 个 residue token + EOS`，64 是 ESMC model head 的 class width，不应称为公开 tokenizer vocabulary size。float32 也明确归因于锁定 SDK 的 `to_float32`，而不是未公开的网页 response schema。对应 Port Type、Node Type、Binding 与 Method 分别升级为 `4.0.0`、`5.0.0`、`5.0.0` 与 `3.0.0`，并同步更新安装包真实门禁、Contract Test Kit、示例 Workflow 与能力清单。这里没有增加宽容解析、Provider shape fallback 或重复 Provider 校验。

## 初始只读调研结论

本节及其后的各 Provider 分节保留实施前快照；其中“当前”“现有”均指本轮修复开始前的实现。实施后的状态以紧邻上方的更新段、当前代码和保留的 verification evidence 为准。

当时的安装包 acceptance 框架已经在源码树之外使用安装产物，并通过
`PROTEIN_WORKBENCH_REQUIRE_PROVIDER_CALL=1` 配合 zero-skip 约束真实调用。当前实现已删除
该重复 preflight 开关，仅由 zero-skip 和 public Binding Readiness 负责；保留的公共运行证据
仍证明 Readiness 先于 Operation Attempt、真实执行而非 Cache hit、Method digest 匹配、
Engine Invocation 与 Run 正常终止。

但是，“确实调用过某个 Provider”不等于“按官方契约正确调用并正确翻译”。现有门禁的共同缺口是：多数测试只检查输出存在、长度或范围，没有在真实调用周围观察 Provider 收到的精确输入和参数，也没有用足以识别翻译漂移的正向 golden 结果闭合输出、残基轴和 provenance。

按修复优先级，结论如下。

| 优先级 | 发现 | 判定 |
|---|---|---|
| P0 | 当前所谓 SoluProt `1.1.0` 是本地现代化 wheel；官方站点目前提供的是 legacy standalone `1.0.1.0`。仓库没有固定前者的源码树、构建配方或从官方 release 派生的可复现证据 | 在来源身份闭合前，不能把它称为“官方 SoluProt 1.1.0 Provider contract”；现有 golden 只能证明本地 wheel 自洽 |
| P1 | ProteinMPNN score 的实际 loss mask 是 `mask * chain_M`，固定上游 score-only 使用 `mask * chain_M * chain_M_pos`；score invocation provenance 又没有记录固定 seed `42` | 真实算法和 Method/evidence 身份存在可修复漂移；固定上游更好 |
| P1 | mkdssp 输出已经提供官方 label identifiers，但 Adapter 用残基名加 CA 坐标容差重新匹配 canonical residue axis | 应使用官方标识符和 canonical mapping；当前坐标启发式既更弱，又制造了 Provider 矛盾假设 |
| P1 | Biohub ESM-3/ESMFold2 和 local ESMFold2 gate 证明了 Binding/Method 被执行，却没有证明 prompt/config、tensor/wire 翻译和输出尺度；ESM-3 PAE 还“接受两种形状” | 应增加 record-and-delegate 观察层和富输入正向 gate；不能用宽容解析替代固定契约 |
| P1 | SimpleFold existing-structure confidence 不是上游公开操作，而是项目用固定上游模块组成的新 Method；当前 gate 很好地证明了“不 refold”，但只用范围/均值证明输出 | 当前组合可以保留，但必须明确是 project-defined composition，并用精确输出 digest 与 mask fixture 固化语义 |
| P2 | 多个 Adapter 在验证“可信 Provider 是否返回了错误类型、错误长度、矛盾坐标、越界置信度或被并发篡改的文件” | 这些分支及其反例测试不属于本项目 trust model；应删除，保留 canonical scientific input、精确配置/来源身份和真实 operational outcomes |

## 什么才是一个完整的 Provider acceptance gate

对本项目，真实 Provider gate 应同时证明四层事实，而不是只证明调用发生。

1. **Identity**：实际加载/连接的是 Method 声明的固定源码 revision、模型/权重/数据资产、Provider model name、运行设备和结果相关 runtime。可变下载 URL 不能单独作为 identity，必须固定 archive/file digest。
2. **Invocation**：公共 Workflow 通过目标 Binding 到达唯一 canonical Adapter；Adapter 向官方 API/CLI/模型发出的函数、参数、命令行、环境和随机性与 Method descriptor 完全相同。
3. **Translation**：至少一个富输入 fixture 覆盖所有非平凡输入翻译；正向输出 fixture 覆盖单位、尺度、shape、mask、chain order、residue identity 和 candidate association。这里测试“项目是否会翻译”，不是测试“Provider 会不会撒谎”。
4. **Evidence**：readiness 在调用前通过；Method/Binding digest 正确；每个实际 Provider call 对应一个有正确 role、parent link、randomness、source/model identity 和 residue projection 的 Engine Invocation；Run 无 skip 地结束。

`tests/test_installed_backend_v2.py` 当前的源码树外安装、`python -I`、零 skip 和 Provider-call-required 机制应保留。`tests/acceptance/test_installed_provider_gates_v2.py` 当前的 readiness/Method/Invocation/terminal 断言也应保留。需要补的是每个 Provider 的 invocation observer 与科学翻译断言，而不是再加一层通用“结果看起来合理”验证。

在 trusted Provider 边界中，下面三类检查必须区分：

- **保留——canonical scientific input invariant**：输入是否属于目标 Candidate/Residue Axis，链/残基/约束映射是否一一对应，所选 Method 是否要求完整 backbone，值域和单位是否属于 Port/Datatype 合同。
- **保留——本地配置与 Method identity**：可执行文件/源码/权重/数据资产是否是声明的固定版本和 digest，模型名、seed、设备、Provider endpoint 是否精确。
- **保留——官方 operational outcome**：进程无法启动、非零退出、超时、官方 SDK 明确定义的 error return，以及 durable output 不存在。它们是实际运行结果，不是“恶意 Provider”假设。
- **删除——conforming Provider malformed/contradictory 假设**：Provider 返回错误容器、错误字段类型、非法字母、错误长度、越界分数、与自身 PDB 矛盾的序列/坐标等。固定官方合同已经保证这些事实；Adapter 只做确定性翻译，异常自然暴露为 Provider/Adapter 集成错误即可。
- **删除——单用户本地环境的攻击者模型**：`nofollow`、路径 containment、文件在两次 stat 间被替换、可信源码目录内 symlink 攻击等。精确 digest 仍须保留，但理由是科学身份，不是安全防御。凭据权限属于仓库明确允许保留的 credential hygiene，不在删除范围。

## 1. mkdssp 4.6.1

### 官方/固定契约

当前 Adapter 声明 PDB-REDO/dssp `v4.6.1` 和 archive SHA-256 `5ddb8274f03ac0338adffcd661989f515fffb95d40afca404cf2677024256ae3`；调研下载官方 tag archive 后得到同一 digest。固定来源是 [DSSP v4.6.1 tag](https://github.com/PDB-REDO/dssp/tree/v4.6.1)，当前实现见 [structure_annotation adapter](../modules/structure_annotation/adapter.py)。

官方 CLI 明确说明：没有输出文件时写 stdout，默认格式是 mmCIF；`--calculate-accessibility` 决定是否计算 accessibility。参见 [mkdssp v4.6.1 CLI source](https://github.com/PDB-REDO/dssp/blob/v4.6.1/src/mkdssp.cpp#L63-L81) 和 [execution path](https://github.com/PDB-REDO/dssp/blob/v4.6.1/src/mkdssp.cpp#L184-L222)。当前命令：

```text
mkdssp --calculate-accessibility input.pdb
```

与官方契约一致。

`_dssp_struct_summary` 的 key 是 `entry_id + label_asym_id + label_seq_id + label_comp_id`；它直接提供 secondary structure、CA 坐标和 accessibility。accessibility 单位是 square Ångström。参见 [DSSP extension dictionary](https://github.com/PDB-REDO/dssp/blob/v4.6.1/libdssp/mmcif_pdbx/dssp-extension.dic#L1503-L1615)、[accessibility definition](https://github.com/PDB-REDO/dssp/blob/v4.6.1/libdssp/mmcif_pdbx/dssp-extension.dic#L1778-L1786) 和 [summary writer](https://github.com/PDB-REDO/dssp/blob/v4.6.1/libdssp/src/dssp-io.cpp#L600-L711)。DSSP 4 论文也把该 category 定义为 per-residue core table：[DSSP 4 FAIR paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC12268231/)。

### 当前漂移

Adapter 虽读取 `label_seq_id`，实际却用 `label_asym_id + label_comp_id + CA xyz`，以约 `0.05 Å` 容差把 DSSP 行重新匹配到输入 PDB。这个做法的问题不是 Provider 可能恶意，而是它放弃了官方 identifier：

- 残基名和 CA 坐标不是 residue identity；modified residue、alternate location、缺失 CA 或相同坐标都会使语义变弱。
- 官方输出是注释后的完整 mmCIF，`atom_site` 和 `_dssp_struct_summary` 已提供 label/auth 标识体系，足以构造确定性映射。
- 当前检查大量讨论“DSSP 声称的坐标是否与输入矛盾”，这不是 conforming Provider 下的有效分支。

正确 seam 是：canonical `ResolvedStructureResidueAxis` 在进入 Adapter 前已决定 residue identity；Adapter 用确定性 label/auth 映射把 canonical axis 渲染为 DSSP 可识别输入，再按官方 label identifiers 取回输出。modified polymer 的 normalization/rejection 必须由更早的 canonical structure seam 决定，不能由 DSSP 坐标匹配悄悄决定。

### gate 必须证明

- readiness 证明实际 executable 的 `--version` 是 `mkdssp version 4.6.1`，来源 archive/file digest 与 Method 相同；
- 实际 argv 恰为 `--calculate-accessibility` 加 canonical input，输出按 stdout mmCIF 解析；
- 使用包含非平凡 residue numbering、insertion code、至少两条 chain，以及明确 modified-residue policy 的 fixture，证明 canonical residue ID 到 `label_asym_id/label_seq_id` 的一一映射；
- SS8 翻译明确：DSSP loop 的空值映射到本项目所选 canonical code，SASA 保持 `Å²`，missing semantics 与 Port Type 一致；
- 对固定结构验证完整 SS8/SASA 序列或稳定 digest，而不只是 `len == 56`；
- 每次调用只有一个正确 role 的 Engine Invocation，provenance 含 DSSP revision、archive/file digest、argv 和 residue projection。

### 删除与保留

删除：Provider mmCIF 列长度不一致、unsupported SS code、SASA 非数值/越界、Provider CA 与输入不一致、重复 summary row 等“官方输出自相矛盾”反例；删除基于 CA 坐标容差的身份判定。

保留：单一 model 和 exact residue representability 等 scientific input invariants；固定 executable/version/digest；进程启动、timeout、nonzero exit；按官方字段做确定性数据转换。

现有真实 gate [test_mkdssp_executes_exact_method_through_public_run](../tests/acceptance/test_installed_provider_gates_v2.py) 证明了公共执行和输出长度，但尚未闭合 argv、identifier mapping 和 SS/SASA golden。

## 2. ProteinMPNN

### 官方/固定契约

仓库固定 [ProteinMPNN source](../repositories/ProteinMPNN) 到 commit `8907e6671bfbfc92303b5f79c4b5e6ce47cdef57`。官方 README 定义 `score` 为 designed residues 的平均 negative log probability，`global_score` 为全部 residues 的平均 NLL，并记录 model、git hash 和 seed：[pinned README](https://github.com/dauparas/ProteinMPNN/blob/8907e6671bfbfc92303b5f79c4b5e6ce47cdef57/README.md#L80-L95)。

固定上游的重要行为是：

- `parse_PDB` 使用 canonical chain alphabet，把 MSE HETATM 规范为 MET，并以 N/CA/C/O 构造 backbone；缺失坐标为 NaN：[protein_mpnn_utils.py](https://github.com/dauparas/ProteinMPNN/blob/8907e6671bfbfc92303b5f79c4b5e6ce47cdef57/protein_mpnn_utils.py#L54-L187)。
- `tied_featurize` 先排序 masked/design chains 与 visible/fixed chains，再把 design chains 放在前面：[chain ordering](https://github.com/dauparas/ProteinMPNN/blob/8907e6671bfbfc92303b5f79c4b5e6ce47cdef57/protein_mpnn_utils.py#L191-L225)。因此 Provider sequence order 与 Workbench structure order 可能不同，恢复顺序是必要翻译。
- 官方 CLI 同时设置 torch、Python random 和 NumPy seed：[protein_mpnn_run.py](https://github.com/dauparas/ProteinMPNN/blob/8907e6671bfbfc92303b5f79c4b5e6ce47cdef57/protein_mpnn_run.py#L24-L31)。
- score-only 使用 `mask * chain_M * chain_M_pos` 传入 `_scores`：[score-only path](https://github.com/dauparas/ProteinMPNN/blob/8907e6671bfbfc92303b5f79c4b5e6ce47cdef57/protein_mpnn_run.py#L239-L264)。design 在 sample 后使用实际 decoding order 再 forward，并以同一 designed-residue mask 计分：[design path](https://github.com/dauparas/ProteinMPNN/blob/8907e6671bfbfc92303b5f79c4b5e6ce47cdef57/protein_mpnn_run.py#L309-L340)。

当前 Provider runtime 的模型结构、21-token alphabet、hidden dimension/layers/neighbors、checkpoint、CPU/eval、`parse_PDB` 和 `tied_featurize` 大体遵循该固定上游，见 [provider_runtime.py](../modules/proteinmpnn/provider_runtime.py)。Adapter 也显式记录 Workbench chain order、Provider chain order和 chain-local one-based residue projection，并把生成序列恢复回 Workbench order，见 [adapter.py](../modules/proteinmpnn/adapter.py)。这个翻译方向是正确的。

### 已确认的算法/evidence 漂移

当前 `_compute_score` 用 `mask * chain_M` 计算 NLL，没有乘 `chain_M_pos`。在现有没有 fixed-position constraint 的 score operation 中结果可能恰好相同，但这仍不是固定上游声明的完整算法；Method identity 不应依赖“当前 fixture 没触发差异”。应统一为固定上游 score-only 语义。

另外，score path 实际在 `torch.manual_seed(request.seed)` 下产生 random decoding order，request 的固定 seed 是 `42`，但 score Engine Invocation provenance 只记录 residue projection，没有记录 `effective_randomness = exact_seed, effective_seed = 42`。这使证据不能完整重放实际调用。

### gate 必须证明

- 固定 commit、checkpoint digest、model name、CPU/device、模型结构参数以及 `backbone_noise`；
- design 精确进入 `tied_sample`，并证明 seed、temperature、number of sequences、omit `X`、fixed-position/chain constraints、backbone noise 等参数；
- score 精确进入固定上游 forward，loss mask 是 `mask * chain_M * chain_M_pos`，decoding order 的随机种子与 provenance 一致；
- 输入 residue IDs 到 Provider `chain-local 1-based` position 的完整 mapping；至少一个 fixture 的 Workbench chain order 与 Provider design-first order 不同，并分别测试“同一 partition 内的顺序”和“design/fixed partition 间的顺序”；
- design 输出 exact sequence digest、effective seed 和恢复后的 residue IDs；score 输出固定结构/序列的 exact native NLL；
- designable residue 缺失所需 N/CA/C/O 时在调用前 fail fast；fixed parent 中缺失 backbone atom 时仍按固定上游 mask 语义保留。这两个是科学输入/translation 事实，不是 malformed Provider 测试。

现有门禁已有很好的正向基础：

- [installed design and score gate](../tests/acceptance/test_installed_provider_gates_v2.py) 证明真实 Binding/Method 执行；
- [native scoring gate](../tests/acceptance/test_proteinmpnn_scoring_v2.py) 固定 seed 在 resident model 解析后应用时的 3GB1 NLL `1.385357141494751`；
- 同一文件固定 design sequence digest 与 effective seed；
- [chain-order gate](../tests/acceptance/test_proteinmpnn_chain_order_v2.py) 证明 design B/fix A 后恢复 A,B，并验证 fixed CSH parent 缠有 missing backbone atom 时的保留行为。

需要补的是调用观察、`chain_M_pos`、score seed provenance 和更强的 chain-order fixture，而不是再验证返回对象是否“看起来像序列”。

### 删除与保留

删除：Provider 是否返回 tuple/list、返回 count 是否不足、返回序列是否有非法 alphabet/length、是否自行附带 residue IDs、score 是否刚好可 binary32 round-trip、是否落在人工 maximum 内等 trusted-result admission；对应反例测试也删除。canonical `ProteinSequence`/Metric admission 只在它们各自拥有的边界执行一次。

保留：Candidate/structure/sequence association；canonical alphabet；layout 与 constraint partition；residue mapping；designable backbone completeness；fixed missing-backbone mask；固定 source/checkpoint/model/device；seed/temperature/count/noise；Provider chain order 到 Workbench order 的确定性翻译。

## 3. Biohub ESM-3 Bindings

### 官方/固定契约

仓库固定 [Biohub ESM SDK](../repositories/esm) 到 commit `917af90b624535eed1e072d343c717e3ec11fef4`。`ESMProtein`、`ESMProteinError` 和 `GenerationConfig` 的类型及默认值由 [pinned SDK api.py](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/api.py#L27-L48) 与 [GenerationConfig](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/api.py#L315-L360) 定义。

固定 SDK 的 Forge 客户端把 sequence、secondary structure、SASA、function annotations、coordinates 和 GenerationConfig 映射到 wire request；坐标 NaN 在 wire 上转为 `None`，response 字段再转回 `ESMProtein`：[request/response translation](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/forge.py#L521-L594)。`generate` 的官方结果是 `ESMProtein | ESMProteinError`，并会把 `num_steps` 限制到目标 track 长度：[generate behavior](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/forge.py#L842-L902)。因此，处理 `ESMProteinError` 是官方 operational contract，应保留。

当前 Adapter 的关键翻译是：

- masked sequence 使用 SDK 的 `_`；
- Workbench secondary-structure 表达被确定性映射到 SDK track；
- SASA 保持 per-residue list；
- backbone/atom37 coordinates 转 float32，以 NaN 表示 mask；
- function annotations 转 SDK `FunctionAnnotation` intervals；
- GenerationConfig 传 track、steps、temperature、top-p、schedule、strategy、annealing，并设置 `condition_on_coordinates_only=True`；
- paired generation 先生成 sequence parent，再把 sampled sequence 与原 prompt 的非 structure conditions 组成 structure child，并用 parent invocation link 记录谱系。

见 [ESM-3 adapter](../modules/esm3/adapter.py)。这些是 Adapter 自己拥有的翻译，必须被真实 gate 观察，而不能只由 mock unit test 证明。

### gate 必须证明

在真实 `ESM3ForgeInferenceClient` 外包一层 **record-and-delegate** observer：记录 Adapter 交给官方 SDK 的 `ESMProtein` 与 `GenerationConfig`，然后委托真正 SDK/Provider。它不伪造结果，因此仍是 real-provider acceptance。

富 prompt 至少要同时覆盖 masked sequence、SS、SASA、一个 function interval、部分 coordinates/NaN mask；分别验证 sequence、structure 和 paired operations，medium/open 两个 route。应断言：

- endpoint、credential handle、SDK revision、model name、request timeout/retry 与 Method 相同；
- 传入 SDK 的每个 track 和 GenerationConfig 字段精确；
- SDK 可能截短后的 effective `num_steps` 在 invocation evidence 中可见；
- 输出 sequence/structure/confidence 对应正确 Candidate 和 residue axis；pLDDT 的 `[0,1] -> [0,100]` 翻译、PAE 单位/轴和 paired condition preservation 有正向断言；
- paired 调用有 `sequence_parent -> structure_child` parent link；Biohub randomness 继续标为 `provider_uncontrolled`。

当前 [all remote bindings gate](../tests/acceptance/test_installed_provider_gates_v2.py) 已覆盖 medium/open × sequence/structure/paired 六个 Binding、八次 Invocation、Method identity、角色、parent link 和不受控随机性。这一覆盖面应保留。但它的简单 ACD/单 mask 输入和“输出 count/PDB 非空”断言没有覆盖上述翻译。

### 不应保留的宽容解析

当前 PAE admission 同时接受 `L × L` 和带 batch/BOS/EOS 的形状再裁剪。固定 Forge SDK 只是把 endpoint `outputs.pae` 转成 tensor，没有声明 Adapter 可以任选两种 shape。除非固定模型的官方 endpoint contract 明确规定其中一个 shape，否则“两个都接受”是 Adapter 猜测。应观察固定 Biohub model 的规范输出，并把唯一 shape/裁剪规则写入 Method 与 gate。

删除：response container/type/length/alphabet/coordinate shape/range 检查、PDB sequence 与 response sequence 的二次一致性检查、“有 confidence 却没有 structure”等 Provider 自相矛盾分支。保留：Prompt 在 SDK 中是否可表达、当前单链限制、mask/axis/单位翻译、官方 `ESMProteinError`，以及精确 SDK/model/endpoint identity。

## 4. Biohub ESMFold2 与 local ESMFold2

### 官方/固定契约

同一固定 ESM commit 的官方 README 给出 local ESMFold2 路径：`ESMFold2Model.from_pretrained`、`StructurePredictionInput` 和 `ESMFold2InputBuilder().fold(..., num_loops=20, num_sampling_steps=100, num_diffusion_samples=1, seed=0)`，结果含 pLDDT 和 pTM：[local ESMFold2 example](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/README.md#L187-L254)。README 也给出 Biohub SequenceStructure client 路径：[Biohub folding example](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/README.md#L258-L298)。

`FoldingConfig` 的字段和默认值来自 [sdk/api.py](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/api.py#L389-L423)。`SequenceStructureForgeInferenceClient` 的 wire request 与 ESMProtein response 翻译见 [sdk/forge.py](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/forge.py#L102-L190)，`fold` 官方返回 `ESMProtein | ESMProteinError`：[fold method](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/sdk/forge.py#L220-L301)。

本地实现的固定调用由 [ESMFold2 processor](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/models/esmfold2/processor.py#L327-L419) 定义：seed context、LM dropout、model args 和 no-grad 都是结果身份的一部分；raw model 到 `MolecularComplexResult` 的 pLDDT/pTM/PAE 解码见 [processor decode](https://github.com/Biohub/esm/blob/917af90b624535eed1e072d343c717e3ec11fef4/esm/models/esmfold2/processor.py#L237-L325)。

当前 [folding adapter](../modules/folding/adapter.py) 的 remote 路径调用官方 `client.fold(sequence, model_name=..., config=...)`，固定 model `esmfold2-fast-2026-05`，FoldingConfig 包含 PAE、100 sampling steps、20 recycles/loops、dropout、LM mask、MSA depth/column mask等；随机性记录为 `provider_uncontrolled`。local 路径固定 SDK revision、snapshot/artifact digests、CPU device 和 ESMC `fp32` precision，并构造 chain A 的 `ProteinInput`/`StructurePredictionInput`，用固定 fold 参数与 seed 调 `ESMFold2InputBuilder.fold`。

### gate 必须证明

**Biohub ESMFold2**：record-and-delegate observer 应记录实际 sequence、model name 和 FoldingConfig 全字段，同时委托真实 client；断言 SDK/model/url/token/timeout/retry identity、官方 error union、provider-uncontrolled randomness、输出 structure/residue axis、pLDDT `[0,1] -> [0,100]`、pTM 原尺度和 PAE `Å`/axis。

**local ESMFold2**：observer 应包裹真实 `ESMFold2InputBuilder.fold`，证明实际 `ProteinInput`、chain A、没有 MSA、loops/steps/samples/seed/dropout/mask/config 与 Method 完全一致；真实加载的 snapshot、checkpoint、CCD/data assets、device、ESMC precision 和 SDK commit 必须在 readiness/evidence 中闭合。对固定短序列或 3GB1 fixture 记录 deterministic structure/confidence digest，而不只断言输出非空。

当前 [remote/local installed gates](../tests/acceptance/test_installed_provider_gates_v2.py) 已证明公共 Binding、Method、role、seed/provenance 和真实执行，remote 另有 3GB1 shape/range acceptance；但它们没有观察实际 config，也没有用精确输出捕获单位、axis 或 tensor projection 漂移。

### 删除与保留

删除：Provider result 类型/shape/range、sequence 与生成 PDB 的二次交叉检查、同时接受多个 speculative shape；本地 artifact 目录的 nofollow/path-containment/两次 stat 间未变化等攻击者防御；对可信 SDK global initialization 的“外来初始化”猜测。

保留：canonical complete input sequence、Candidate/axis association；固定 SDK/source/snapshot/checkpoint/CCD identity 与 digest；model/config/device/seed；官方 `ESMProteinError`；实际加载/启动/超时/网络或模型运行失败。CCD 身份检查保留是因为它影响科学结果，但只需在 readiness seam 验证一次，之后信任该配置。

## 5. SimpleFold existing-structure confidence

### 上游事实与当前 Method 的性质

仓库固定 [Apple ml-simplefold](../repositories/ml-simplefold) 到 commit `c7a5570a6be9f5c695126e27c804e77567209934`。上游 `ModelWrapper.from_pretrained_plddt_model` 加载 `plddt.ckpt` 的 confidence head、`simplefold_1.6B.ckpt` latent model 并设 eval：[wrapper.py](https://github.com/apple/ml-simplefold/blob/c7a5570a6be9f5c695126e27c804e77567209934/src/simplefold/wrapper.py#L117-L196)。官方 folding path 的 processor 使用 coordinate scale 16/reference scale 5；sampler 生成坐标后，以 `t = 1` 调 latent module 和 output module，最后 `plddt * 100`：[processor/sampler setup](https://github.com/apple/ml-simplefold/blob/c7a5570a6be9f5c695126e27c804e77567209934/src/simplefold/wrapper.py#L264-L291) 和 [confidence decode](https://github.com/apple/ml-simplefold/blob/c7a5570a6be9f5c695126e27c804e77567209934/src/simplefold/wrapper.py#L321-L354)。官方 inference CLI 使用相同模块与尺度：[inference.py](https://github.com/apple/ml-simplefold/blob/c7a5570a6be9f5c695126e27c804e77567209934/src/simplefold/inference.py#L119-L179)。

上游没有公开“给定现有结构，仅评估 confidence 而不采样/refold”的 API。当前项目的 [simplefold_confidence_adapter.py](../modules/folding/simplefold_confidence_adapter.py) 是一个 **project-defined composition**：

1. 用固定上游 feature pipeline 和 ESM2 representation 构造输入；
2. 解析给定 PDB，中心化坐标并除以 16，按 CA presence 构造 mask；
3. 不加载 folding sampler/contact-regression weights；
4. 在 supplied coordinates 上以 `t=1` 调 latent module，再调 pLDDT output head；
5. 把 native `[0,1]` pLDDT 乘 100，并关联回原 residue axis。

这种组合可以是一个清晰、可解释的新 Method，当前 [Method descriptor](../modules/folding/package.py) 已使用 “SimpleFold direct existing-structure confidence” 并写明 no coordinate generation，这是正确方向。它不能被描述为上游官方 existing-structure confidence operation；acceptance 要证明的是“项目定义的组合精确使用固定官方组件”。

### gate 必须证明

- 固定 source commit、minimal asset digests、model variants、device 和 feature pipeline；
- 真实 supplied PDB 到 feature/coordinates 的 center、`/16` scale、CA-valid mask 与 residue-axis mapping；
- `t=1 -> latent module -> pLDDT head` 的确切顺序与 `×100`；
- folding sampler/refold、contact-regression 和不用的模型权重没有加载；
- 固定 3GB1 的完整 pLDDT vector digest，而不只均值；增加含 missing CA 的 fixture，证明 mask 与输出 residue semantics；
- 一个 Engine Invocation 的 Method/provenance 完整记录 source/assets/device/no-refold composition。

当前 [SimpleFold confidence acceptance](../tests/acceptance/test_simplefold_confidence_v2.py) 已非常有价值：真实跑 3GB1、锁定 minimal assets，并用 monkeypatch 禁止 folding model/inference、contact regression 和无关资产；它确实证明了“不 refold”。但输出只检查 56 个值、范围和均值，局部 residue permutation、mask 错位或少量输出漂移仍可能通过。应升级为完整 vector digest/fixture，而不是新增 malformed response 测试。

删除：raw result closed-map/type/range 防御，artifact nofollow/TOCTOU/import-escape 等攻击者假设。保留：PDB scientific representability、坐标/mask/axis、source/asset/device identity，以及 no-refold 本身，因为这些共同定义这个 project Method。

## 6. Protein-Sol

### 官方契约与当前实现

[Protein-Sol official software page](https://protein-sol.manchester.ac.uk/software) 提供本地 sequence predictor；其官方下载 endpoint 是 [download_sequence_code.php](https://protein-sol.manchester.ac.uk/cgi-bin/utilities/download_sequence_code.php)。本次调研于 2026-08-03 下载到的 archive SHA-256 是：

```text
4df32c61fca53adcb2394a528babd1ad85cb5c551bf7bd1c56d134097fb2b1b8
```

archive README 标为 October 2017，规定运行：

```text
multiple_prediction_wrapper_export.sh sequence_input_file
```

并从 `seq_prediction.txt` 读取 percent-sol、scaled-sol、population-sol 和 pI。当前 [solubility adapter](../modules/solubility/adapter.py) 固定的八个源文件 digest 与这次官方 archive 中对应文件逐一相同，当前 argv 也与官方 wrapper 一致。官方论文说明该模型使用 35 个 sequence-derived properties，并以 E. coli soluble-expression 数据训练：[Hebditch et al. 2017](https://pubmed.ncbi.nlm.nih.gov/28575391/)。

因此，Protein-Sol 的核心调用和结果字段目前有直接官方证据。当前不足主要在来源 provenance 表述：Method/package 仍把另一个 workspace 的 `vendor/protein-sol` 当 dependency path，而不是用官方 archive URL + archive digest + file digests 作为 canonical source identity。官方 URL 可变，所以 archive digest 必须被正式固定；不能只写下载 URL。

### gate 必须证明

- 官方 archive identity、八个实际执行文件 digest，以及结果相关 bash/perl runtime identity；
- 实际 argv/cwd/input FASTA/order 与官方 wrapper 精确一致；
- `seq_prediction.txt` 的 documented fields 到本项目 Metric Definitions 的一一翻译、单位/尺度、Candidate 顺序与 association；
- 至少两个序列的 batch fixture 和官方 exact golden percent-sol/scaled-sol/pI；
- Method/evidence 记录官方 release/archive，而不是外部 workspace path。

现有 [Protein-Sol acceptance](../tests/acceptance/test_protein_sol_v2.py) 已用两个官方 fixture 做真实 batch，并固定多个 exact metric 值、Candidate association、Method/evidence/readiness，是所有本次检查对象里较完整的正向 gate。修复重点是 canonical source provenance，并在 execution evidence 中显式闭合 archive/argv。

删除：Provider output 是否保持三位小数、population-sol 是否仍恰好 `0.446`、percent 与 scaled 字段是否互相满足 Adapter 推测公式、输出文件是否在两次 stat 间变化、文件大小上限/截断等 trusted-provider 矛盾或本地攻击者分支。解析 documented fields 即可；Metric/Port boundary 拥有类型和尺度。

保留：canonical alphabet/minimum length 等 scientific input；官方 archive/file/runtime identity；argv；进程 start/nonzero/timeout 和 documented output missing；Candidate order/association。

## 7. SoluProt

### 无法闭合的来源身份

[SoluProt official download page](https://loschmidt.chemi.muni.cz/soluprot/?page=download) 当前提供 standalone version 1，下载链接为 `?f=soluprot.zip`；页面列出的环境是 Python 3.7、scikit-learn 0.20.1、BioPython 1.74、pandas、TMHMM 和 USEARCH。官方论文把它定义为预测 E. coli soluble overexpression 概率的 gradient boosting model，并说明 standalone availability：[SoluProt paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC8034534/)。

本次于 2026-08-03 下载的官方 archive SHA-256 是：

```text
b7e716a8e611577a465bd3510702fcd12a5de5a38299946707ca8a0995630e4c
```

它包含 `soluprot-1.0.1.0` legacy `soluprot.py` 和 pickle models；不包含 `soluprot_core`、JSON/NPZ models 或所谓 `1.1.0` wheel。

当前 [solubility adapter](../modules/solubility/adapter.py) 则声明：

- `SOLUPROT_VERSION = "1.1.0"`；
- Python 3.12 wheel 和固定 wheel digest；
- entry point `python -I -m soluprot_core.cli`；
- JSON/NPZ models；
- `--i_fa`、`--o_csv`、`--tmp_dir`、`--model`、`--usearch`、`--pdb`、`--check_unknown`、`--no_proc 1`，再选择 TMHMM 或 `--no_tmhmm`。

该 wheel 的本地内容显示它是一个现代化/repackaged derivative，但当前仓库没有它的源码树、构建 recipe、上游 commit、模型转换脚本，或从官方 `1.0.1.0` release 推导到该 wheel 的可复现证明。官方站点和论文也没有定义 `soluprot_core 1.1.0` 的 CLI contract。

因此当前不能把它称为“官方 SoluProt 1.1.0”。这不是兼容或供应链安全问题，而是科学 provenance 不完整：无法仅凭 wheel 自称版本判断实际算法、features 和 model conversion 是否仍与官方 SoluProt 相同。

### 在修复 provenance 前，gate 能证明和不能证明什么

现有 [SoluProt acceptance](../tests/acceptance/test_soluprot_v2.py) 真实执行 full/no-TM 两个 Method，固定 wheel/tool/model assets，并对官方来源 fixture 验证 exact golden 概率、Method/Metric/evidence/readiness。它能证明：

- 当前锁定的本地 wheel 在当前锁定环境中可执行；
- 两个项目 Method 的 command/config 和 golden 结果当前自洽；
- full 与 no-TM 的差别被调用和证据记录。

它不能单独证明：

- wheel 是官方发布的 `1.1.0`；
- JSON/NPZ models 与官方 pickle models 的转换无语义变化；
- Python 3.12 port 与官方 legacy pipeline 对任意有效输入科学等价；
- 当前 CLI 参数是官方契约，而不是本项目 port 的契约。

### 必须先做的身份决策

二选一，不应继续维持含糊身份：

1. **项目维护的 SoluProt port**：把它明确命名为 project-maintained port；把完整源码树、build recipe、官方 release archive digest、模型/feature conversion 程序和产物 digest 固定在本仓库或固定 repository；用一组覆盖长度、composition、unknown policy、TM/no-TM 的 conformance corpus 比较 legacy official artifact 与 port。Method identity 记录 port commit/build，而不冒充官方 `1.1.0`。
2. **官方 standalone Method**：按官方 `1.0.1.0` artifact 和官方运行时/CLI 直接调用，Method 和 provenance 记录官方 release/digests。

在作出选择后，真实 gate 应证明 exact command/args、tool/model assets、full/no-TM distinction、Candidate association、exact positive goldens 和完整 provenance。如果选择 port，还必须把 conformance corpus 作为 release/acceptance gate；单个 fixture 不足以证明全局等价。

删除：输出文件 byte/race 防御、Provider probability precision/range/field-type malformed 检查、trusted wheel 内路径攻击假设。保留：所选实现的精确源码/model/tool identity、canonical alphabet/minimum length、full/no-TM 科学区别、命令参数以及 process operational failures。

## Gate 状态矩阵

| Selector / Provider | 当前真实 gate 已证明 | 主要缺口 | 目标门禁 |
|---|---|---|---|
| `mkdssp` | 安装产物、readiness、Method、真实 CLI、非空 56-residue output | argv 未被观察；identifier mapping 与 SS/SASA golden 缺失 | command observer + label-ID fixture + SS8/SASA digest |
| `proteinmpnn` | design/score real model、exact score/design goldens、部分 chain-order/missing-backbone | score mask 漂移；score seed evidence；调用参数和更复杂 chain order | wrapped real runtime + upstream mask + full projection/evidence |
| `biohub_esm3` | 6 Bindings、8 calls、两模型、roles/parent links、zero skip | prompt/config/wire translation 和 confidence/axis 翻译几乎未断言 | record-and-delegate SDK observer + rich prompt + output translation |
| `biohub_esmfold2` | real client、exact Binding/Method、role、remote evidence | FoldingConfig/actual request 未观察；输出尺度/axis 仅范围 | record-and-delegate client + exact config + confidence/PAE mapping |
| `local_esmfold2` | real local model、fixed Method、seed、output exists | builder input/args 未观察；无 deterministic full golden | wrapped real builder + exact inputs/args + output digest |
| `simplefold_confidence` | real assets、3GB1、明确禁止 refold/contact/unneeded models | project-defined identity需更明确；输出只范围/均值；mask fixture缺失 | composition observer + full vector digest + missing-CA axis fixture |
| `protein_sol` | real official code、two-sequence batch、exact multi-metric goldens、association | canonical official archive provenance/argv evidence | 正式固定 archive digest + command/evidence closure |
| `soluprot` | real locked wheel、full/no-TM、exact fixture goldens | 无官方 `1.1.0` 来源/构建/派生链 | 先决定 official standalone 或 project port，再建立相应 gate |

## 建议修复顺序

1. **先闭合 SoluProt identity**。这是唯一一个在“不改 Adapter 逻辑”的情况下也无法说清实际 Provider 是谁的问题；在身份决策完成前，不应把该 gate 计为“官方 Provider acceptance 已完成”。
2. **修正 ProteinMPNN score 算法与 provenance**。对齐固定上游 `chain_M_pos`，记录 score seed，然后用现有 exact NLL 防回归。
3. **把 mkdssp mapping 移到官方 identifiers**。这应与 canonical modified-polymer/residue-axis 修复一起做，避免另一条坐标启发式科学路径。
4. **为 Biohub ESM-3/ESMFold2 和 local ESMFold2 增加 record-and-delegate observer**。先证明实际调用，再收紧为唯一输出 shape/scale；不要保留“多个 shape 都接受”的猜测。
5. **升级 SimpleFold confidence gate**。保留当前 no-refold 组合，明确 project-defined Method，增加完整向量 digest 与 missing-CA fixture。
6. **规范 Protein-Sol source provenance**。固定官方下载物 archive digest，移除对另一个 workspace 的 dependency identity。
7. **最后统一删除 malformed-provider/adversarial-local checks 和对应测试**。应在每个正向 gate 闭合之后删除，避免把真正的 translation invariant 一并误删。

## 最终判定

真实 Provider acceptance 的目标不是“Provider 会不会返回坏数据”，而是证明本项目按固定官方规范调用，并把规范结果无歧义地翻译为 canonical scientific values 和可审计 evidence。

- mkdssp、ProteinMPNN、Biohub ESM-3/ESMFold2、local ESMFold2 和 Protein-Sol 都有足以定义正向契约的固定/官方来源；预期的精确调用—翻译—provenance 架构优于当前以 malformed defense 补洞的实现。
- SimpleFold confidence 的当前 project-defined composition 可以比“假装存在一个上游 API”更好，但必须把组合本身当作 Method 的科学身份并进行 deterministic acceptance。
- SoluProt 当前实现不能在 provenance 未闭合时与官方 release 等同；这里不是测试数量问题，而是 Provider identity 问题。
- 本地无攻击者和 trusted Provider 前提不会降低科学门禁强度；它只是把检查从“防御坏 Provider/坏用户”集中到“精确 identity、调用、翻译、随机性、residue mapping 和 evidence”。
