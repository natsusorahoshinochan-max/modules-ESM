# `fold`

> `POST /api/v1/fold`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/fold)
- 快照信息及共用约定见[快照入口](../README.md)。

## 用途

(ESM3, ESMFold2) Folds proteins. Defaults to esmfold2-fast-2026-05 if no model is given

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
- `lm_mask_pct` 的表格默认值为 `0`，说明文字则写明 FAST 模型缺省为 `0.1`、非 FAST ESMFold2 为 `0.0`。来源页两处说明不一致。
- `include_distogram`、`include_pae`、`include_pair_chains_iptm` 与 `include_embeddings` 控制相应内容是否返回。
