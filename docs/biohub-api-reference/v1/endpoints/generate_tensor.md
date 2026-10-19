# `generate_tensor`

> `POST /api/v1/generate_tensor`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/generate_tensor)
- 快照信息及共用约定见[快照入口](../README.md)。

## 用途

(ESM3) Generates an output track conditioned on inputs. Accepts and returns raw tokens.

## JSON 请求体

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `model` | `string` | 是 | — | 枚举: `esm3-open-2024-03` |
| `potential_sequence_of_concern` | `boolean` | 否 | `false` | — |
| `track` | `string` | 是 | — | — |
| `invalid_ids` | `array[integer]` | 否 | — | — |
| `schedule` | `string` | 否 | `cosine` | 枚举: `cosine`<br>`linear` |
| `strategy` | `string` | 否 | `random` | 枚举: `random`<br>`entropy` |
| `num_steps` | `integer` | 否 | `20` | 范围: `[1, 100]` |
| `temperature` | `number` | 否 | `0.5` | 范围: `[0, ∞)` |
| `temperature_annealing` | `boolean` | 否 | `true` | — |
| `top_p` | `number` | 否 | `1` | 范围: `(0, 1]` |
| `condition_on_coordinates_only` | `boolean` | 否 | `true` | — |
| `inputs` | `Tokens` | 是 | — | — |
| `inputs.sequence` | `array[integer] \| null` | 否 | — | — |
| `inputs.coordinates` | `array[array[array[number \| null]]] \| null` | 否 | — | — |
| `inputs.structure` | `array[integer] \| null` | 否 | — | — |
| `inputs.secondary_structure` | `array[integer] \| null` | 否 | — | — |
| `inputs.sasa` | `array[integer \| null] \| null` | 否 | — | — |
| `inputs.function` | `array[array[integer]] \| null` | 否 | — | — |
| `inputs.residue_annotation` | `array[array[integer]] \| null` | 否 | — | — |

## 来源语义说明

- 该端点与 `generate` 的生成控制相近，但输入与输出使用 raw token。
- `track` 的页面候选为 `sequence`、`structure`、`secondary_structure`、`sasa`、`function`；来源数据未将它编码成机器枚举。
