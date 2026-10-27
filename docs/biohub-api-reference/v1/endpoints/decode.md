# `decode`

> `POST /api/v1/decode`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/decode)
- 快照信息及共用约定见[快照入口](../README.md)。

## 用途

(ESM3, ESMC) Decodes tokens sequence, structure, or function annotations

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

## 来源语义说明

- 输入对象为 `Tokens`，覆盖 sequence、coordinates、structure、secondary_structure、SASA、function 与 residue annotation token。
- `inputs.coordinates` 的页面形状说明为 `N×37×3`。
