# `forward_and_sample`

> `POST /api/v1/forward_and_sample`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/forward_and_sample)
- 快照信息及共用约定见[快照入口](../README.md)。

## 用途

(ESM3) Performs one inference step and samples output tokens

## 请求头

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `accept` | `string \| null` | 否 | — | — |

## JSON 请求体

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `model` | `string` | 是 | — | 枚举: `esm3-open-2024-03` |
| `potential_sequence_of_concern` | `boolean` | 否 | `false` | — |
| `inputs` | `Tokens` | 是 | — | — |
| `inputs.sequence` | `array[integer] \| null` | 否 | — | — |
| `inputs.coordinates` | `array[array[array[number \| null]]] \| null` | 否 | — | — |
| `inputs.structure` | `array[integer] \| null` | 否 | — | — |
| `inputs.secondary_structure` | `array[integer] \| null` | 否 | — | — |
| `inputs.sasa` | `array[integer \| null] \| null` | 否 | — | — |
| `inputs.function` | `array[array[integer]] \| null` | 否 | — | — |
| `inputs.residue_annotation` | `array[array[integer]] \| null` | 否 | — | — |
| `sampling_config` | `SamplingConfig` | 是 | — | — |
| `sampling_config.sequence` | `PerTrackSamplingConfig \| null` | 否 | — | — |
| `sampling_config.sequence.temperature` | `number` | 否 | `1` | 范围: `[0, ∞)` |
| `sampling_config.sequence.top_p` | `number` | 否 | `1` | 范围: `(0, 1]` |
| `sampling_config.sequence.only_sample_masked_tokens` | `boolean` | 否 | `true` | — |
| `sampling_config.sequence.invalid_ids` | `array[integer]` | 否 | — | — |
| `sampling_config.sequence.topk_logprobs` | `integer` | 否 | `0` | — |
| `sampling_config.structure` | `PerTrackSamplingConfig \| null` | 否 | — | — |
| `sampling_config.structure.temperature` | `number` | 否 | `1` | 范围: `[0, ∞)` |
| `sampling_config.structure.top_p` | `number` | 否 | `1` | 范围: `(0, 1]` |
| `sampling_config.structure.only_sample_masked_tokens` | `boolean` | 否 | `true` | — |
| `sampling_config.structure.invalid_ids` | `array[integer]` | 否 | — | — |
| `sampling_config.structure.topk_logprobs` | `integer` | 否 | `0` | — |
| `sampling_config.secondary_structure` | `PerTrackSamplingConfig \| null` | 否 | — | — |
| `sampling_config.secondary_structure.temperature` | `number` | 否 | `1` | 范围: `[0, ∞)` |
| `sampling_config.secondary_structure.top_p` | `number` | 否 | `1` | 范围: `(0, 1]` |
| `sampling_config.secondary_structure.only_sample_masked_tokens` | `boolean` | 否 | `true` | — |
| `sampling_config.secondary_structure.invalid_ids` | `array[integer]` | 否 | — | — |
| `sampling_config.secondary_structure.topk_logprobs` | `integer` | 否 | `0` | — |
| `sampling_config.sasa` | `PerTrackSamplingConfig \| null` | 否 | — | — |
| `sampling_config.sasa.temperature` | `number` | 否 | `1` | 范围: `[0, ∞)` |
| `sampling_config.sasa.top_p` | `number` | 否 | `1` | 范围: `(0, 1]` |
| `sampling_config.sasa.only_sample_masked_tokens` | `boolean` | 否 | `true` | — |
| `sampling_config.sasa.invalid_ids` | `array[integer]` | 否 | — | — |
| `sampling_config.sasa.topk_logprobs` | `integer` | 否 | `0` | — |
| `sampling_config.function` | `PerTrackSamplingConfig \| null` | 否 | — | — |
| `sampling_config.function.temperature` | `number` | 否 | `1` | 范围: `[0, ∞)` |
| `sampling_config.function.top_p` | `number` | 否 | `1` | 范围: `(0, 1]` |
| `sampling_config.function.only_sample_masked_tokens` | `boolean` | 否 | `true` | — |
| `sampling_config.function.invalid_ids` | `array[integer]` | 否 | — | — |
| `sampling_config.function.topk_logprobs` | `integer` | 否 | `0` | — |
| `embedding_config` | `EmbeddingConfig \| null` | 否 | — | — |
| `embedding_config.sequence` | `boolean` | 否 | `false` | — |
| `embedding_config.per_residue` | `boolean` | 否 | `false` | — |

## 来源语义说明

- 该端点执行一次推理并直接采样 output token。
- `sampling_config` 分别配置 sequence、structure、secondary_structure、SASA 与 function 轨道；每个轨道共享 temperature、top-p、masked-only、invalid IDs 与 top-k logprob 一组控制。
- `embedding_config` 可分别请求 sequence mean-pooled embedding 与逐残基 embedding。
