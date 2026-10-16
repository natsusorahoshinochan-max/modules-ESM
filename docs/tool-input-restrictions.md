# 工具输入字符与长度边界

已确认要求是按用户指定输入和工具官方接口正确传参，不静默删字符或猜测替换。共用 `ProteinSequence` 的 `ACDEFGHIKLMNPQRSTVWYBXZJUO` 非空大写值范围，不等于每个工具支持全部符号；工具接纳限制也不反向缩小共用值。实现入口见[模块能力](module-capabilities.md#当前序列输入边界)。

## 有依据的约束与对齐

| 路线 | 一手证据 | 结论 |
|---|---|---|
| ESM-3 SDK 条件序列 | 固定 `esm` 提交 `917af90b624535eed1e072d343c717e3ec11fef4` 的 [SEQUENCE_VOCAB](../repositories/esm/esm/utils/constants/esm3.py)包含标准20种及 `X/B/U/Z/O`，不包含 `J`；[tokenizer](../repositories/esm/esm/tokenization/sequence_tokenizer.py)使用该词表。 | [Adapter](../modules/esm3/adapter.py)保持这25种符号，未知条件位置用 `_` 编码；不能将 `J` 猜换为其他残基。词表可表示性不等于所有模型/操作接受该符号，远程具体语义仍以官方端点为准。 |
| Protein-Sol 本地序列评价 | [官方软件下载入口](https://www.protein-sol.manchester.ac.uk/software)的 [ZIP](https://www.protein-sol.manchester.ac.uk/cgi-bin/utilities/download_sequence_code.php)，`fasta_seq_reformat_export.pl` 的两个记录出口均只在过滤后 `$naa >= 21` 时输出；字符过滤仅保留标准20种。 | 最短21有直接入口依据，不是由滑动窗口大小推测。Workbench 在调用前拒绝短序列和非标准字符，防止上游过滤造成评价对象改变，保持现有约束。 |
| SoluProt-next 本地 full/no-TM | 项目维护的 [Provider 输入入口](../repositories/soluprot-next/soluprot_core/features.py)中 `AA`、`MIN_SEQ_LENGTH=20`、`_load_sequences` 与 `_filter_sequence`；[CLI](../repositories/soluprot-next/soluprot_core/cli.py)的 `--check_unknown`。 | 此实际 Provider 只按标准20种计算，最短20；Workbench 显式开启未知字符检查，不能启用独立 CLI 默认的删字符路径。这是项目维护的 Provider 契约，不能冒充所有 SoluProt 版本的官方限制。 |
| ProteinMPNN 独立序列评分 | 固定上游提交 `8907e6671bfbfc92303b5f79c4b5e6ce47cdef57` 的 [protein_mpnn_run.py](../repositories/ProteinMPNN/protein_mpnn_run.py)，`alphabet` 为标准20种加 `X`；`score_only` 使用同一 `alphabet_dict` 编码 FASTA 序列。 | `X` 有明确评分入口支持，拒绝它属于额外限制。当前评分准入已对齐并原样传入 `X`，不替换为具体氨基酸，也不扩大到 `B/Z/J/U/O`。设计约束及设计输出范围不由评分入口推定。 |

Protein-Sol 官方包读取核对日期为 2026-10-16，ZIP SHA-256 为 `4df32c61fca53adcb2394a528babd1ad85cb5c551bf7bd1c56d134097fb2b1b8`；其中上述 parser SHA-256 为 `ee671b4121e343e0dd660377a8204c2e5058fcf9185e8ea629b2c3c64562a8e9`，与已配置本地 Provider 同文件逐字节一致。该包 README 自述版本 October 2017；上述摘要只固定本次约束依据，不是运行验收结果。没有执行下载脚本或修改固定上游。

## 仍需核实的范围

| 路线 | 当前证据与待核实点 |
|---|---|
| Biohub ESMFold2 | [官方 fold 接口](https://docs.biohub.ai/api/protein/models/fold)及[固定快照](biohub-api-reference/v1/endpoints/fold.md)将 sequence 声明为 string/null，未给出特殊残基字符表或长度范围。不能从缺少 pattern 推导任意字符串均受支持，也不能据此证明本地标准20种检查是官方要求。 |
| 本地 ESMFold2 | 共用[折叠输入](../modules/folding/_output_construction.py)目前限定标准20种及单链；还缺该模型输入、输出残基表示的完整官方依据。远程接口的约束不能代替本地路线依据。 |
| SimpleFold | 固定提交 `c7a5570a6be9f5c695126e27c804e77567209934` 的 [encode_sequence](../repositories/ml-simplefold/src/simplefold/utils/esm_utils.py)将未识别字符编码为 `X`；[residue_constants](../repositories/ml-simplefold/src/simplefold/utils/residue_constants.py)包含标准20种加未知类型。该内部编码事实不证明任意特殊残基可原样通过实际折叠、输出与残基轴构建；不能据此放开所有符号或添加 Workbench 猜测转换。当前共用标准20种限制的完整路线依据仍未解决。 |
| Biohub ESMC | [encode 固定接口](biohub-api-reference/v1/endpoints/encode.md)没有给出完整特殊残基准入表。当前入口直接传递共用序列，不应将其接纳 `J` 的实现事实宣称为官方可表示保证；仍需核对实际路线的 tokenizer/服务契约。 |

这些未决点保留在 [DOC-010](2026-10-15-documentation-governance-issues.md#doc-010部分输入字符与长度限制的官方依据仍需核对)，不把缺少证据改写为禁止或允许的新需求。不得通过加载本次排除的本地 ESM-3、SimpleFold、ESMFold2 模型来填补证据；不加载模型的静态与契约检查不等于真实模型通过。

## 导入与验证边界

单条 FASTA 的拒绝多记录与 PDB/mmCIF 输入检查已由当前源码支持，见[输入说明](results.md)。这是解析现状的纠正，不改变已确认的导入要求。字符与长度的资料核对不等于真实 Provider 验收；评分行为调整须经过[当前验证门槛](backend-verification.md)，包括获准的真实 ProteinMPNN 路线。不会用受控 Provider 代替真实验收。
