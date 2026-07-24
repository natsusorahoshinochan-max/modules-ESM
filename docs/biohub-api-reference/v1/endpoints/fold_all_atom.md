# `fold_all_atom`

> `POST /api/v1/fold_all_atom`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/fold_all_atom)
- 抓取时间：`2026-07-16T03:56:50.184Z`
- 页面发布标识：`sha-7062746`
- 鉴权：`Authorization: Bearer <API_KEY>`
- 请求媒体类型：`application/json`
- 来源定义 SHA-256：`98fc1b846d2b2d8dcf8ddce2694afb11582a92fdc95281f1f788be7d7e9a8559`

## 用途

(ESMFold2) Folds molecular complexes containing proteins, dna, rna, and ligands. Defaults to esmfold2-fast-2026-05 if no model is given

## 请求头

_来源页未定义端点专用请求头；通用 `Authorization: Bearer <API_KEY>` 仍然适用。_

## JSON 请求体

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `model` | `string \| null` | 否 | — | 枚举: `esmfold2-fast-2026-05`<br>`esmfold2-2026-05`<br>`null` |
| `potential_sequence_of_concern` | `boolean` | 否 | `false` | — |
| `sequence` | `string \| null` | 否 | — | — |
| `msa` | `MSA \| null` | 否 | — | — |
| `msa.sequences` | `array[string]` | 是 | — | — |
| `msa.deletions` | `array[array[number]] \| null` | 否 | — | — |
| `num_loops` | `integer` | 否 | `20` | 范围: `[0, 20]` |
| `num_sampling_steps` | `integer` | 否 | `100` | 范围: `[1, 100]` |
| `lm_dropout` | `number` | 否 | `0.3` | 范围: `[0, 1]` |
| `lm_mask_pct` | `number` | 否 | `0` | 范围: `[0, 1]` |
| `msa_max_depth` | `integer \| null` | 否 | `1024` | 范围: `[1, 16384]` |
| `msa_column_mask_rate` | `number` | 否 | `0.1` | 范围: `[0, 1]` |
| `include_distogram` | `boolean` | 否 | `false` | — |
| `include_pae` | `boolean` | 否 | `false` | — |
| `include_pair_chains_iptm` | `boolean` | 否 | `false` | — |
| `all_atom_input` | `FoldAllAtomInput \| null` | 否 | — | — |
| `all_atom_input.sequences` | `array[ProteinInput \| RNAInput \| DNAInput \| LigandInput]` | 是 | — | — |
| `all_atom_input.sequences[].ProteinInput` | `object` | 否 | — | — |
| `all_atom_input.sequences[].ProteinInput.id` | `string \| array[string] \| null` | 否 | — | — |
| `all_atom_input.sequences[].ProteinInput.sequence` | `string` | 是 | — | — |
| `all_atom_input.sequences[].ProteinInput.msa` | `MSA \| null` | 否 | — | — |
| `all_atom_input.sequences[].ProteinInput.msa.sequences` | `array[string]` | 是 | — | — |
| `all_atom_input.sequences[].ProteinInput.msa.deletions` | `array[array[number]] \| null` | 否 | — | — |
| `all_atom_input.sequences[].ProteinInput.modifications` | `array[Modification] \| null` | 否 | — | — |
| `all_atom_input.sequences[].ProteinInput.modifications[].position` | `integer` | 是 | — | — |
| `all_atom_input.sequences[].ProteinInput.modifications[].ccd` | `string` | 是 | — | — |
| `all_atom_input.sequences[].ProteinInput.type` | `string` | 是 | — | — |
| `all_atom_input.sequences[].RNAInput` | `object` | 否 | — | — |
| `all_atom_input.sequences[].RNAInput.id` | `string \| array[string] \| null` | 否 | — | — |
| `all_atom_input.sequences[].RNAInput.sequence` | `string` | 是 | — | — |
| `all_atom_input.sequences[].RNAInput.modifications` | `array[Modification] \| null` | 否 | — | — |
| `all_atom_input.sequences[].RNAInput.modifications[].position` | `integer` | 是 | — | — |
| `all_atom_input.sequences[].RNAInput.modifications[].ccd` | `string` | 是 | — | — |
| `all_atom_input.sequences[].RNAInput.type` | `string` | 是 | — | — |
| `all_atom_input.sequences[].DNAInput` | `object` | 否 | — | — |
| `all_atom_input.sequences[].DNAInput.id` | `string \| array[string] \| null` | 否 | — | — |
| `all_atom_input.sequences[].DNAInput.sequence` | `string` | 是 | — | — |
| `all_atom_input.sequences[].DNAInput.modifications` | `array[Modification] \| null` | 否 | — | — |
| `all_atom_input.sequences[].DNAInput.modifications[].position` | `integer` | 是 | — | — |
| `all_atom_input.sequences[].DNAInput.modifications[].ccd` | `string` | 是 | — | — |
| `all_atom_input.sequences[].DNAInput.type` | `string` | 是 | — | — |
| `all_atom_input.sequences[].LigandInput` | `object` | 否 | — | — |
| `all_atom_input.sequences[].LigandInput.id` | `string \| array[string] \| null` | 否 | — | — |
| `all_atom_input.sequences[].LigandInput.smiles` | `string \| null` | 否 | — | — |
| `all_atom_input.sequences[].LigandInput.ccd` | `array[string] \| null` | 否 | — | — |
| `all_atom_input.sequences[].LigandInput.type` | `string` | 是 | — | — |
| `all_atom_input.covalent_bonds` | `array[CovalentBond] \| null` | 否 | — | — |
| `all_atom_input.covalent_bonds[].chain_id1` | `string` | 是 | — | — |
| `all_atom_input.covalent_bonds[].res_idx1` | `integer` | 是 | — | — |
| `all_atom_input.covalent_bonds[].atom_idx1` | `integer` | 是 | — | — |
| `all_atom_input.covalent_bonds[].chain_id2` | `string` | 是 | — | — |
| `all_atom_input.covalent_bonds[].res_idx2` | `integer` | 是 | — | — |
| `all_atom_input.covalent_bonds[].atom_idx2` | `integer` | 是 | — | — |
| `all_atom_input.pocket` | `PocketConditioning \| null` | 否 | — | — |
| `all_atom_input.pocket.binder_chain_id` | `string` | 是 | — | — |
| `all_atom_input.pocket.contacts` | `array[array[tuple]]` | 是 | — | — |
| `all_atom_input.distogram_conditioning` | `array[DistogramConditioning] \| null` | 否 | — | — |
| `all_atom_input.distogram_conditioning[].chain_id` | `string` | 是 | — | — |
| `include_embeddings` | `boolean` | 否 | `false` | — |

## 来源语义说明

- 未提供 `model` 时，页面声明默认使用 `esmfold2-fast-2026-05`。
- `all_atom_input` 支持 protein、RNA、DNA 与 ligand；一旦提供，页面说明会忽略顶层 `sequence` 与 `msa`。
- Protein/RNA/DNA modification 的 `position` 明确为 0-based；`ccd` 是 Chemical Component Dictionary code。
- 复合物还可提供跨链共价键、binder pocket contacts 与按 chain 指定的 distogram conditioning。
- `include_distogram`、`include_pae`、`include_pair_chains_iptm` 与 `include_embeddings` 是响应内容开关，不等于完整响应 schema。

公开的 `model` 枚举只反映抓取时页面列出的模型；来源页明确提示，账户还可能拥有未列出的私有模型。

## 响应

截至本次抓取，来源页没有发布该端点的响应状态码、媒体类型或响应 body schema。因此本地机器定义将响应记录为 `documented: false` 与 `schema: null`，不从 SDK、现有项目代码或运行时样本反推。
