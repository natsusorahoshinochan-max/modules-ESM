# `encode`

> `POST /api/v1/encode`

- 来源：[Biohub API Reference](https://biohub.ai/api-reference/encode)
- 抓取时间：`2026-07-16T03:56:50.184Z`
- 页面发布标识：`sha-7062746`
- 鉴权：`Authorization: Bearer <API_KEY>`
- 请求媒体类型：`application/json`
- 来源定义 SHA-256：`a37046ffe4bb88f6618c024d898a380cb90c204b455dea608a6300842a031793`

## 用途

(ESM3, ESMC) Tokenize sequence, structure, or function annotations

## 请求头

_来源页未定义端点专用请求头；通用 `Authorization: Bearer <API_KEY>` 仍然适用。_

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
- 页面记录 SASA 编码在 2025-03-18 修复：此前 `inf` 会编码为 `-1`，之后改为 `1000`。

公开的 `model` 枚举只反映抓取时页面列出的模型；来源页明确提示，账户还可能拥有未列出的私有模型。

## 响应

截至本次抓取，来源页没有发布该端点的响应状态码、媒体类型或响应 body schema。因此本地机器定义将响应记录为 `documented: false` 与 `schema: null`，不从 SDK、现有项目代码或运行时样本反推。
