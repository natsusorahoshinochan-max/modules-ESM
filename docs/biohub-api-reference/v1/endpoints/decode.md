# `decode`

> `POST /api/v1/decode`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/decode)
- 抓取时间：`2026-07-16T03:56:50.184Z`
- 页面发布标识：`sha-7062746`
- 鉴权：`Authorization: Bearer <API_KEY>`
- 请求媒体类型：`application/json`
- 来源定义 SHA-256：`b8a68d24c583030be549118d1ae61a4068a0a8720a4ce0139b6b71c26b4fed89`

## 用途

(ESM3, ESMC) Decodes tokens sequence, structure, or function annotations

## 请求头

_来源页未定义端点专用请求头；通用 `Authorization: Bearer <API_KEY>` 仍然适用。_

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

公开的 `model` 枚举只反映抓取时页面列出的模型；来源页明确提示，账户还可能拥有未列出的私有模型。

## 响应

截至本次抓取，来源页没有发布该端点的响应状态码、媒体类型或响应 body schema。因此本地机器定义将响应记录为 `documented: false` 与 `schema: null`，不从 SDK、现有项目代码或运行时样本反推。
