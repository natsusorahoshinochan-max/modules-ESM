# `generate_tensor`

> `POST /api/v1/generate_tensor`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/generate_tensor)
- 抓取时间：`2026-07-16T03:56:50.184Z`
- 页面发布标识：`sha-7062746`
- 鉴权：`Authorization: Bearer <API_KEY>`
- 请求媒体类型：`application/json`
- 来源定义 SHA-256：`6be7397d84b760be1c1aff281a4d6341dd03f24e4d21140ab2382168687708fc`

## 用途

(ESM3) Generates an output track conditioned on inputs. Accepts and returns raw tokens.

## 请求头

_来源页未定义端点专用请求头；通用 `Authorization: Bearer <API_KEY>` 仍然适用。_

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
- `strategy`、`num_steps`、`temperature`、`temperature_annealing` 的当前默认值由页面标注为 2025-02-14 更新后的值。

公开的 `model` 枚举只反映抓取时页面列出的模型；来源页明确提示，账户还可能拥有未列出的私有模型。

## 响应

截至本次抓取，来源页没有发布该端点的响应状态码、媒体类型或响应 body schema。因此本地机器定义将响应记录为 `documented: false` 与 `schema: null`，不从 SDK、现有项目代码或运行时样本反推。
