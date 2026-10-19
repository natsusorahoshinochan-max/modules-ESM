# `inverse_fold`

> `POST /api/v1/inverse_fold`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/inverse_fold)
- 快照信息及共用约定见[快照入口](../README.md)。

## 用途

(ESM3) Inverse folds proteins. Defaults to esm3-open-2024-03 if no model is given

## JSON 请求体

| 字段 | 类型 | 必填 | 默认值 | 约束 |
| --- | --- | --- | --- | --- |
| `model` | `string \| null` | 否 | — | 枚举: `esm3-open-2024-03`<br>`null` |
| `potential_sequence_of_concern` | `boolean` | 否 | `false` | — |
| `coordinates` | `array[array[array[number \| null]]]` | 否 | — | — |
| `inverse_folding_config` | `InverseFoldingConfig` | 是 | — | — |
| `inverse_folding_config.invalid_ids` | `array[integer]` | 否 | — | — |
| `inverse_folding_config.temperature` | `number` | 否 | `0.1` | 范围: `[0, ∞)` |
| `sequence` | `string \| null` | 否 | — | — |

## 来源语义说明

- 未提供 `model` 时，页面声明默认使用 `esm3-open-2024-03`。
- `coordinates` 的页面形状说明为 `N×37×3`。
- 页面建议通过改变 seed 获得多样性，而不是提高 inverse-fold temperature；当前默认 temperature 为 `0.1`。
