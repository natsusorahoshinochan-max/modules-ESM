# ESMFold2 与 ESMC-6B 的验证规划

本文记录测试配置、现有调用入口与接口依据。资源受限机器的验证分工统一维护在 [本地模型验证范围](../local-models.md#资源受限机器的验证范围)，产品行为以 [需求](../requirements.md) 为准，职责与交接按 [目标架构](../architecture.md)。本次调整对象是当前机器的真实模型测试选择；本地实现、工具声明、部署配置与依赖继续服务于有资源的部署。其他尺寸 ESMC 的调用范围按实际任务处理。

## 来源边界

请求契约使用 [Biohub v1 官方快照](../biohub-api-reference/v1/README.md)，机器字段见 [api-reference.json](../biohub-api-reference/v1/api-reference.json)，抓取时间为 2026-07-16、页面发布标识为 `sha-7062746`，见 [manifest.json](../biohub-api-reference/v1/manifest.json)。快照未公开响应 schema、完整服务限制与服务 base URL；响应解析以下述固定 SDK 为依据，尚需在获授权的接口验收中核实服务器实际响应。

SDK 来源为 [Biohub/esm 固定提交 `43b4548`](https://github.com/Biohub/esm/tree/43b4548b86762edfa747b07d5f440aad3c33acee)，与项目 [pyproject.toml](../../pyproject.toml) 固定依赖一致。下文 `repositories/esm` 链接均指该只读上游源码。SDK [客户端工厂](../../repositories/esm/esm/sdk/__init__.py)默认服务地址为 `https://biohub.ai`，使用 [Bearer 鉴权](../../repositories/esm/esm/sdk/base_forge_client.py)。现有折叠模块从部署配置显式传入凭据，见 [create_remote](../../modules/folding/adapters.py)。

## 三种调用边界

| 场景 | 接口与后果 |
| --- | --- |
| 直接 ESMC-6B 表征、logits | 请求模型 ID 为 `esmc-6b-2024-12`；调用 `ESMCForgeInferenceClient.encode()`、`logits()`。Hugging Face 的 `biohub/ESMC-6B` 是本地 checkpoint 名称，不能作为 wire model ID。依据：[encode](../biohub-api-reference/v1/endpoints/encode.md)、[logits](../biohub-api-reference/v1/endpoints/logits.md)、[本地配置](../../repositories/esm/esm/models/esmc/config.py)。 |
| ESMFold2 预测 | 本机真实模型测试复用远端 `SequenceStructureForgeInferenceClient.fold()`；模型明确选择 `esmfold2-fast-2026-05` 或 `esmfold2-2026-05`。本地 ESMFold2 的 PLM 是其模型内部组成，见 [model.py 的 `self.esmc`、`load_esmc` 与 LM forward](../../repositories/esm/esm/models/esmfold2/model.py)；不能把规划改写为本地折叠模型中替换一个远程 ESMC 函数。 |
| SimpleFold | 上游推理加载 `esm_registry["esm2_3B"]()`，是另一工具的 ESM2 依赖；其本地测试仍按自身资源条件开展。依据：[SimpleFold inference](../../repositories/ml-simplefold/src/simplefold/inference.py)、[esm_registry](../../repositories/ml-simplefold/src/simplefold/utils/esm_utils.py)。 |

## ESMC-6B 请求与结果

### 单次前向可请求的内容

`POST /api/v1/logits` 的 `inputs.sequence` 接受整数 token 列表。`logits_config.sequence=true` 请求真实逐位置 logits，`return_embeddings=true` 请求最终隐藏状态的逐位置 embedding，`return_mean_embedding=true` 请求服务端整序列 mean embedding；三者可由同一次 logits 请求选择。布尔开关默认均为 false。SDK 输出分别为 `LogitsOutput.logits.sequence`、`embeddings`、`mean_embedding`。依据：[官方 logits](https://biohub.ai/api-reference/logits)、[快照](../biohub-api-reference/v1/endpoints/logits.md)、[SDK 请求及响应处理](../../repositories/esm/esm/sdk/forge.py)、[LogitsConfig / LogitsOutput](../../repositories/esm/esm/sdk/api.py)。

`/forward_and_sample` 中的 `embedding_config.sequence` 也描述 mean-pooled embedding，但该端点公开 model 列表仅有 ESM3；ESMC-6B 的整序列 embedding 应使用 `/logits.return_mean_embedding`。`/encode` 负责 token 化，输出 token 不是模型 embedding。依据：[forward_and_sample](../biohub-api-reference/v1/endpoints/forward_and_sample.md)、[encode](../biohub-api-reference/v1/endpoints/encode.md)。

需要区分三种数据：服务返回的完整 token 位置 embedding；通过明确 token/残基对应抽取的逐残基 embedding；服务端返回的 mean embedding。SDK只说明 mean 沿序列长度池化，未公开特殊 token、padding、链分隔符的排除方式；远端 mean 不能标成与本地实际残基平均数值相等。若任务需要“实际残基均值”，可另从逐位置 embedding 按残基映射计算并明确该方法，不能把它伪装成服务端 mean。依据：[LogitsOutput 语义](../../repositories/esm/esm/sdk/api.py)、[需求中的 ESMC 数值约定](../requirements.md)。

### 位置与输出列

固定 SDK 的 [EsmcTokenizer](../../repositories/esm/esm/models/esmc/tokenizer.py) 为字符级 tokenizer，首尾加入 `<cls>` / `<eos>`；已命名 ID 为 0–32，其中 `<cls>=0`、`<pad>=1`、`<eos>=2`、`<unk>=3`、`|=31`、`<mask>=32`。普通单链的 N 个残基通常对应 N+2 个 token，残基 i（0-based）对应 token i+1；多链、mask 与非标准输入必须依据实际编码结果建立对应，不能靠统一切掉首尾就宣称全部中间 token 都是残基。`/encode` 文档还允许 `_` 表达 mask，远端处理后的 token 应保留。依据：[tokenizer 源码](../../repositories/esm/esm/models/esmc/tokenizer.py)、[encode 快照](../biohub-api-reference/v1/endpoints/encode.md)、[SDK encode](../../repositories/esm/esm/sdk/forge.py)。

token 词表名称与 logits 输出宽度分开处理：上游 [EsmcConfig](../../repositories/esm/esm/models/esmc/config.py)默认 `vocab_size=64`，而 tokenizer 只有 33 个命名条目，[LM head](../../repositories/esm/esm/models/esmc/model.py)按 `config.vocab_size` 投影。远端实际列数须从返回张量取得；保存完整实际数值与列索引，已知列带 token 名称，其余列保持未命名。用张量形状校验位置对应，但不能以形状摘要代替所请求数值，或将 logits 转写为概率。远端确切宽度与 batch/position 轴仍需响应验收确认。

### 编码、dtype 与可选隐藏层

SDK `logits()` 默认 `return_bytes=true`，发送 `return-bytes: true` 并协商 ES pickle / JSON 响应。JSON 中 `logits`、`embeddings`、`hidden_states` 若为 base64 字符串，解析路径为 base64 → Zstandard 解压 → `torch.load(..., map_location="cpu", weights_only=False)`，不是把 base64 当作裸 float 数组。外层响应也可能由 `assemble_message()` 直接按 pickle 解码。ESMC 响应处理随后对浮点 tensor 升为 float32；`mean_embedding` 直接取响应字段并做 tensor 情况下的升精度，未独立执行上述字符串解码。因此实施前需用固定 SDK 的已解码结果确认 mean 的实际类型，遇到错误类型明确失败。依据：[forge.py 的 `_maybe_b64_decode` 与 ESMC `_process_logits_response`](../../repositories/esm/esm/sdk/forge.py)、[deserialize_tensors / to_float32](../../repositories/esm/esm/utils/misc.py)、[assemble_message](../../repositories/esm/esm/utils/decoding.py)。结果文件可按需求采用 float16；记录实际保存 dtype 与形状，数值文件由模块交付，避免在通用 JSON 或 WebSocket 内展开大型矩阵。

当前表征任务未要求新增 hidden states 验证。作为能力边界，6B 的 `ith_hidden_layer` 为 0–80，0 为 embedding 层，`-1` 的全层输出不受支持。若未来任务请求 hidden states，再检查该层选择。单层 hidden-state 文档形状为 `[1, B, L, D]`，均值 hidden-state 的单层实际返回形状在本次任务外。依据：[logits 快照](../biohub-api-reference/v1/endpoints/logits.md)、[LogitsConfig](../../repositories/esm/esm/sdk/api.py)。

## ESMFold2 请求与结果

[fold](../biohub-api-reference/v1/endpoints/fold.md)接受蛋白序列与可选 MSA；[fold_all_atom](../biohub-api-reference/v1/endpoints/fold_all_atom.md)接受蛋白、RNA、DNA、配体和复合物条件。后者一旦提供 `all_atom_input`，顶层 `sequence` / `msa` 被忽略。现有预测工具插槽仅接收一条规范蛋白链，当前验证继续使用 `fold`；all-atom、配体与复合物接口属于能力背景，不列为本次测试调整的前置条件。其真实对象字段由 [SDK `serialize_structure_prediction_input`](../../repositories/esm/esm/utils/structure/input_builder.py)生成，快照展示的 `ProteinInput` 等联合类型标签尚未确认为 wire 字段。

公开计算参数为 `num_loops` 0–20（默认 20）、`num_sampling_steps` 1–100（100）、`lm_dropout` 0–1（0.3）、`lm_mask_pct` 0–1、`msa_max_depth` null 或 1–16384（1024）、`msa_column_mask_rate` 0–1（0.1）。额外结果开关为 `include_distogram`、`include_pae`、`include_pair_chains_iptm`、`include_embeddings`，默认 false。来源：[fold](https://biohub.ai/api-reference/fold)、[fold_all_atom](https://biohub.ai/api-reference/fold_all_atom)、对应快照。

seed 未列入两个端点，SDK `FoldingConfig` 也没有 seed。现有远端 Adapter 已拒绝 seed；测试配置选择远端时移除 seed。本地路径继续保留 seed 与本地执行配置，各自按真实接口验证。`lm_mask_pct` 的快照字段表默认 0，而说明与 [SDK `_resolve_lm_mask_pct`](../../repositories/esm/esm/sdk/forge.py)选择 fast=0.1、full=0.0。规划中明确模型并按 SDK 解析、记录实际参数，避免无意依赖服务默认模型。

FAST 模型在 SDK 中明确警告会忽略 MSA；full 模型才适合需要使用 MSA 的请求。SDK拒绝超过 16384 行的 MSA；不应在任务要求使用 MSA 时提交 FAST 并忽略警告。来源：[SDK `_process_fold_request` / `_process_fold_all_atom_request`](../../repositories/esm/esm/sdk/forge.py)、[MSA 限制常量](../../repositories/esm/esm/utils/constants/models.py)。

响应边界按 SDK分开：`fold()` 解析坐标、plddt、ptm、pae、interface_ptm、pair_chains_iptm、residue_index、entity_id 与可选 embedding；`fold_all_atom()` 解析 `complex` 为 `MolecularComplex`，另取置信度、位置/实体与 embedding 等结果。复合物接口不在当前单链插槽的验证范围内。折叠 `output_embedding_sequence` / `output_embedding_pair_pooled` 是折叠服务输出，不能命名为直接 ESMC-6B 表征结果。依据：[SDK 两种 response processor](../../repositories/esm/esm/sdk/forge.py)、[MolecularComplexResult](../../repositories/esm/esm/utils/structure/molecular_complex.py)。

## SDK 选择、尝试上限与未决项

真实远端验证复用已固定 SDK 与现有模块 Adapter，测试配置明确选择远端模型、凭据与 URL；远端失败按所选路径记录失败。单次推理类默认最大 5 次尝试，针对 `ESMProteinError` 429/500/502/503/504 重试，采用 full-jitter exponential 等待（multiplier 1、最大 10 秒）；HTTP 包装中确定性编码/解析错误转 400，其余异常转 500。依据：[retry.py](../../repositories/esm/esm/sdk/retry.py)、[base_forge_client.py](../../repositories/esm/esm/sdk/base_forge_client.py)。

选择构造入口时记录实际 timeout：ESMC 类默认 60 秒、折叠类默认 120 秒；`esmc_client()` / `esmfold2_client()` 工厂默认传 `None`，即无限等待。`ForgeParallelExecutor` 另有默认 10 次尝试、64 workers，并通过 context 跳过底层 retry；该执行器不是本次单请求 SDK 默认值，不应无意引入第二层批次策略。依据：[类构造器](../../repositories/esm/esm/sdk/forge.py)、[工厂](../../repositories/esm/esm/sdk/__init__.py)、[parallel executor](../../repositories/esm/esm/utils/forge_context_manager.py)。

当前测试涉及的接口核对重点是 ESMC-6B 返回 token 与残基位置、logits 实际轴和全部列、mean 的实际类型，以及所请求数值文件的独立读取。mean 的服务端池化定义仍未公开，记录结果时保留这一语义边界。账户权限、长度与速率限制按服务实际错误处理；快照未给出可当作项目固定限制的数字。依据：[快照入口](../biohub-api-reference/v1/README.md)、[logits](../biohub-api-reference/v1/endpoints/logits.md)、[固定 SDK](../../repositories/esm/esm/sdk/forge.py)。

补充能力差异：固定 SDK 两种折叠请求均拒绝 `include_distogram=true`，现有 [折叠 Adapter](../../modules/folding/adapters.py)已拒绝该参数；all-atom SDK 未传 `include_pair_chains_iptm`，其响应 processor 也未交付 pair-chain 字段。这些差异记录为接口边界，当前资源条件无需新增直接 HTTP 或重试层。依据：[fold_all_atom 快照](../biohub-api-reference/v1/endpoints/fold_all_atom.md)、[SDK 请求与响应处理](../../repositories/esm/esm/sdk/forge.py)。

## 当前入口与待办验证工作

| 对象 | 已有代码与当前任务 |
| --- | --- |
| ESMFold2 远端实跑 | [adapters.py](../../modules/folding/adapters.py)已有 `create_remote`，使用 `esmfold2_client` 与 `FoldingConfig`，工具 ID 为 `workbench.esmfold2.remote`；[verify.py](../../modules/folding/verify.py)已经覆盖公开工具选择、上传、推理、交付、存储及独立结构解析。当前测试配置在此入口选择远端，复用 [#146 的有效远端验证记录](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/146#issuecomment-6273735354)，不再将本地模型实跑列为该任务在本机完成的门槛。命令与配置字段维护在 [TOOL.md](../../modules/folding/TOOL.md)。 |
| ESMFold2 本地契约 | 同一 [adapters.py](../../modules/folding/adapters.py)的 `create_local`、`LOCAL_DEFAULTS` 与 `workbench.esmfold2.local` 继续存在，[local_worker.py](../../modules/folding/local_worker.py)负责实际加载。本机隔离加载边界，验证本地参数、seed=0、worker 生命周期与结果交付；有资源机器再进行联合模型实跑。 |
| ESMC 表征 [#164](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/164) | 现有 [esmc_adapter.py](../../modules/esm3/esmc_adapter.py)的远端实现由 [package.py](../../modules/esm3/package.py)登记为600M，含 `mean_embedding[0, 0]` 与 `sequence_logits[1:-1]` 的固定形状假设，尚不能直接视为6B接口验收。该任务按现行模块边界完成本地与 Biohub 两条路径、所有调用方及结果文件交付；本机6B实跑配置选择 `esmc-6b-2024-12`，本地加载替身用于契约检查，其他尺寸按其实际配置运行。 |

表征任务的本地与 Biohub 契约验证共同覆盖真实 token/残基和输出列对应、可选 embedding / logits、实际数值保存、Provider 错误与资源释放；两条路径分别验证各自均值方法，不做跨后端数值等同断言。真实远端记录包括所选工具、模型、请求参数与可读取输出；本地实跑状态和后续补充范围按 [统一验证分工](../local-models.md#资源受限机器的验证范围)记录。这里列出的是待办技术检查，现有代码仅用于确定改动入口，不作为需求来源。

## 规划落点与执行顺序

1. [#144 共同执行约定](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/144)引用统一资源范围；[#143 Testing Decisions](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/143)沿用该入口。
2. 折叠验收在现有验证配置中显式选择 `workbench.esmfold2.remote`，按 [工具说明](../../modules/folding/TOOL.md)提供服务配置与适用参数；[#154](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/154)继续覆盖本地与远端的批次契约。既有远端记录可用于未变动接口的验收。
3. [#164](https://github.com/natsusorahoshinochan-max/modules-ESM/issues/164)在新模块接入与文件交付边界实现表征功能，测试配置选择明确的6B远端模型，核对 encode/logits 请求与解码结果，再验证保存、读取与导出。本地测试隔离权重加载，保留实际输入、tokenizer、数值编码和文件交接。
4. 验证记录分别列出本地契约结果、Biohub 实跑结果、本机资源限制及待有资源机器补充的本地实跑。后续部署的本地验证使用本地模型配置和统一资源锁。

模块生命周期和全项目清理任务继续依据产品需求维护本地支持；本次规划更新集中在测试约定、配置选择和验证记录，运行实现沿现有边界维护。
