# `logits`

> `POST /api/v1/logits`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/logits)
- 抓取时间：`2026-07-16T03:56:50.184Z`
- 页面发布标识：`sha-7062746`
- 鉴权：`Authorization: Bearer <API_KEY>`
- 请求媒体类型：`application/json`
- 来源定义 SHA-256：`6da5dc2e1778fe43dd77543bbcf168d1fbc08a8a71839dd1a0f047250dd678cc`

## 用途

(ESM3, ESMC) Performs one inference step and returns logits, embeddings, and SAE features (ESMC only).

## 请求头

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `return-bytes` | `string` | 否 | `false` | — |
| `accept` | `string \| null` | 否 | — | — |

## JSON 请求体

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `model` | `string` | 是 | — | 枚举: `esmc-300m-2024-12`<br>`esmc-600m-2024-12`<br>`esmc-6b-2024-12`<br>`esm3-open-2024-03` |
| `potential_sequence_of_concern` | `boolean` | 否 | `false` | — |
| `inputs` | `Tokens` | 是 | — | — |
| `inputs.sequence` | `array[integer] \| null` | 否 | — | — |
| `inputs.coordinates` | `array[array[array[number \| null]]] \| null` | 否 | — | — |
| `inputs.structure` | `array[integer] \| null` | 否 | — | — |
| `inputs.secondary_structure` | `array[integer] \| null` | 否 | — | — |
| `inputs.sasa` | `array[integer \| null] \| null` | 否 | — | — |
| `inputs.function` | `array[array[integer]] \| null` | 否 | — | — |
| `inputs.residue_annotation` | `array[array[integer]] \| null` | 否 | — | — |
| `logits_config` | `LogitsConfig` | 是 | — | — |
| `logits_config.sequence` | `boolean` | 否 | `false` | — |
| `logits_config.structure` | `boolean` | 否 | `false` | — |
| `logits_config.secondary_structure` | `boolean` | 否 | `false` | — |
| `logits_config.sasa` | `boolean` | 否 | `false` | — |
| `logits_config.function` | `boolean` | 否 | `false` | — |
| `logits_config.residue_annotations` | `boolean` | 否 | `false` | — |
| `logits_config.return_embeddings` | `boolean` | 否 | `false` | — |
| `logits_config.return_mean_embedding` | `boolean` | 否 | `false` | — |
| `logits_config.return_hidden_states` | `boolean` | 否 | `false` | — |
| `logits_config.return_mean_hidden_states` | `boolean` | 否 | `false` | — |
| `logits_config.ith_hidden_layer` | `integer` | 否 | `-1` | — |
| `logits_config.sae_config` | `SAEConfig \| null` | 否 | — | — |
| `logits_config.sae_config.models` | `array[string]` | 否 | — | 枚举: `esmc-300m-2024-12-sae-layer23-k64-codebook65536`<br>`esmc-600m-2024-12-sae-layer27-k64-codebook16384`<br>`esmc-600m-2024-12-sae-layer27-k64-codebook65536`<br>`esmc-6b-2024-12-sae-layer60-k64-codebook16384`<br>`esmc-6b-2024-12-sae-layer60-k64-codebook65536` |
| `logits_config.sae_config.normalize_features` | `boolean` | 否 | `true` | — |

## 来源语义说明

- `structure`、`secondary_structure`、`sasa` 与 `function` logits 在页面中标为 Biohub Platform 不支持；`sequence` logits 支持 ESM3/ESMC，`residue_annotations` 仅标为 ESM3。
- `return_hidden_states=true` 时，全部层与单层的张量形状分别记录为 `[n_layers + 1, B, L, D]` 与 `[1, B, L, D]`；ESM3 要求指定 `ith_hidden_layer`。
- `ith_hidden_layer=-1` 表示全部层，但页面说明 ESMC 6B 与所有 ESM3 模型不支持该值。页面内层数表使用的部分模型名与公开 `model` 枚举并不完全一致，使用时应保留这一来源差异。
- `sae_config` 仅用于 ESMC 的稀疏自编码器特征。

公开的 `model` 枚举只反映抓取时页面列出的模型；来源页明确提示，账户还可能拥有未列出的私有模型。

## 响应

截至本次抓取，来源页没有发布该端点的响应状态码、媒体类型或响应 body schema。因此本地机器定义将响应记录为 `documented: false` 与 `schema: null`，不从 SDK、现有项目代码或运行时样本反推。
