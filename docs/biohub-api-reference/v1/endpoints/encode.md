# `encode`

> `POST /api/v1/encode`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/encode)
- 快照信息及共用约定见[快照入口](../README.md)。

## 用途

(ESM3, ESMC) Tokenize sequence, structure, or function annotations

## JSON 请求体

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `model` | `string` | 是 | — | 枚举: `esmc-300m-2024-12`<br>`esmc-600m-2024-12`<br>`esmc-6b-2024-12`<br>`esm3-open-2024-03` |
| `potential_sequence_of_concern` | `boolean` | 否 | `false` | — |
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

## 来源语义说明

- `inputs.sequence` 可用 `_` 遮罩部分位置。
- `inputs.coordinates` 的页面形状说明为 `N×37×3`。
- `inputs.function` 使用 `(InterPro tag, start, end)` 三元组；起止位置为 1-based 且包含端点，页面标明支持 InterPro 95.0。
- 来源约定的 SASA 编码中，`inf` 映射为 `1000`。
