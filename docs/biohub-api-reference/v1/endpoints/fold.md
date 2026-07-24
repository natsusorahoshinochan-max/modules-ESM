# `fold`

> `POST /api/v1/fold`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/fold)
- 抓取时间：`2026-07-16T03:56:50.184Z`
- 页面发布标识：`sha-7062746`
- 鉴权：`Authorization: Bearer <API_KEY>`
- 请求媒体类型：`application/json`
- 来源定义 SHA-256：`3db2562edf1ae9ab0ab4722bbf58b16fbae50f5632faada757e39bb1428f540e`

## 用途

(ESM3, ESMFold2) Folds proteins. Defaults to esmfold2-fast-2026-05 if no model is given

## 请求头

_来源页未定义端点专用请求头；通用 `Authorization: Bearer <API_KEY>` 仍然适用。_

## JSON 请求体

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `model` | `string \| null` | 否 | — | 枚举: `esm3-open-2024-03`<br>`esmfold2-fast-2026-05`<br>`esmfold2-2026-05`<br>`null` |
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
| `include_embeddings` | `boolean` | 否 | `false` | — |

## 来源语义说明

- 未提供 `model` 时，页面声明默认使用 `esmfold2-fast-2026-05`。
- MSA、循环次数、扩散采样步数、LM dropout/masking 与额外输出开关均标为 ESMFold2 相关。
- `lm_mask_pct` 的表格默认值显示为 `0`，但说明文字同时写明 FAST 模型缺省为 `0.1`、非 FAST ESMFold2 为 `0.0`；这是来源页自身需要在实现中显式处理的差异。
- `include_distogram`、`include_pae`、`include_pair_chains_iptm` 与 `include_embeddings` 是响应内容开关，不等于完整响应 schema。

公开的 `model` 枚举只反映抓取时页面列出的模型；来源页明确提示，账户还可能拥有未列出的私有模型。

## 响应

截至本次抓取，来源页没有发布该端点的响应状态码、媒体类型或响应 body schema。因此本地机器定义将响应记录为 `documented: false` 与 `schema: null`，不从 SDK、现有项目代码或运行时样本反推。
