# `generate`

> `POST /api/v1/generate`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/generate)
- 快照信息及共用约定见[快照入口](../README.md)。

## 用途

(ESM3) Generates an output track conditioned on inputs

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
| `inputs` | `Tracks` | 是 | — | — |
| `inputs.sequence` | `string \| null` | 否 | — | — |
| `inputs.secondary_structure` | `string \| null` | 否 | — | — |
| `inputs.sasa` | `array[integer \| number \| null] \| null` | 否 | — | — |
| `inputs.function` | `array[array[tuple]] \| null` | 否 | — | — |
| `inputs.coordinates` | `array[array[array[number \| null]]] \| null` | 否 | — | — |
| `inputs.plddt` | `array[number] \| null` | 否 | — | — |
| `inputs.ptm` | `number \| null` | 否 | — | — |
| `inputs.crmsd` | `number \| null` | 否 | — | — |
| `inputs.globularity` | `number \| null` | 否 | — | — |
| `inputs.interface` | `array[string] \| null` | 否 | — | — |
| `inputs.interface_ptm` | `number \| null` | 否 | — | — |
| `inputs.pae` | `array[array[number]] \| null` | 否 | — | — |
| `only_compute_backbone_rmsd` | `boolean` | 否 | `false` | — |

## 来源语义说明

- `track` 的页面候选为 `sequence`、`structure`、`secondary_structure`、`sasa`、`function`；该限制只出现在说明文字中，来源数据未提供机器枚举。
- `num_steps` 除页面范围 `[1, 100]` 外，还要求不大于序列长度；页面提示超过 20 步通常收益递减。
- `condition_on_coordinates_only=true` 表示用坐标而非 structure token 作为生成条件；`only_compute_backbone_rmsd` 只影响返回的 cRMSD 计算范围。
