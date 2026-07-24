# `inverse_fold`

> `POST /api/v1/inverse_fold`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/inverse_fold)
- 抓取时间：`2026-07-16T03:56:50.184Z`
- 页面发布标识：`sha-7062746`
- 鉴权：`Authorization: Bearer <API_KEY>`
- 请求媒体类型：`application/json`
- 来源定义 SHA-256：`fa7495ba86abac45c2e6366e030904709b3543ff0741d36835ec2f527f1b384f`

## 用途

(ESM3) Inverse folds proteins. Defaults to esm3-open-2024-03 if no model is given

## 请求头

_来源页未定义端点专用请求头；通用 `Authorization: Bearer <API_KEY>` 仍然适用。_

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

公开的 `model` 枚举只反映抓取时页面列出的模型；来源页明确提示，账户还可能拥有未列出的私有模型。

## 响应

截至本次抓取，来源页没有发布该端点的响应状态码、媒体类型或响应 body schema。因此本地机器定义将响应记录为 `documented: false` 与 `schema: null`，不从 SDK、现有项目代码或运行时样本反推。
