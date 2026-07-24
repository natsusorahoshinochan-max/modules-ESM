# Biohub Platform API v1 Reference

这是对 Biohub 官方 API Reference 的结构化快照，用于后续项目修改时核对供应商 wire contract。抓取时间为 `2026-07-16T03:56:50.184Z`，页面发布标识为 `sha-7062746`。

## 快照边界

- 保留：HTTP method/path、Bearer 鉴权、请求头、字段层级、类型、必填性、默认值、枚举与范围。
- 归一化：页面中的空默认值不解释为空字符串；nullable 枚举中的 `null` 转为 JSON null；方法名转为大写。
- 不保留：站点导航、样式、脚本、分析代码与法律页脚。
- 不推断：来源页未发布的 base URL、响应状态码、响应媒体类型与响应 schema。

## 文件布局

```text
docs/reference/biohub/v1/
├── README.md
├── manifest.json
├── api-reference.json
└── endpoints/
    ├── logits.md
    ├── encode.md
    ├── decode.md
    ├── generate.md
    ├── generate_tensor.md
    ├── forward_and_sample.md
    ├── fold.md
    ├── fold_all_atom.md
    └── inverse_fold.md
```

- `api-reference.json`：机器可读的规范化请求合同，适合测试、映射与差异检查。
- `manifest.json`：来源、抓取元数据、规范化规则、限制与每页定义哈希。
- `endpoints/*.md`：供人工审查的逐端点视图。

## 端点索引

| 端点 | 方法 | 路径 | 来源 |
| --- | --- | --- | --- |
| [`logits`](endpoints/logits.md) | `POST` | `/api/v1/logits` | [官方页面](https://biohub.ai/api-reference/logits) |
| [`encode`](endpoints/encode.md) | `POST` | `/api/v1/encode` | [官方页面](https://biohub.ai/api-reference/encode) |
| [`decode`](endpoints/decode.md) | `POST` | `/api/v1/decode` | [官方页面](https://biohub.ai/api-reference/decode) |
| [`generate`](endpoints/generate.md) | `POST` | `/api/v1/generate` | [官方页面](https://biohub.ai/api-reference/generate) |
| [`generate_tensor`](endpoints/generate_tensor.md) | `POST` | `/api/v1/generate_tensor` | [官方页面](https://biohub.ai/api-reference/generate_tensor) |
| [`forward_and_sample`](endpoints/forward_and_sample.md) | `POST` | `/api/v1/forward_and_sample` | [官方页面](https://biohub.ai/api-reference/forward_and_sample) |
| [`fold`](endpoints/fold.md) | `POST` | `/api/v1/fold` | [官方页面](https://biohub.ai/api-reference/fold) |
| [`fold_all_atom`](endpoints/fold_all_atom.md) | `POST` | `/api/v1/fold_all_atom` | [官方页面](https://biohub.ai/api-reference/fold_all_atom) |
| [`inverse_fold`](endpoints/inverse_fold.md) | `POST` | `/api/v1/inverse_fold` | [官方页面](https://biohub.ai/api-reference/inverse_fold) |

## 使用规则

1. 修改 provider adapter、请求模型或验证逻辑时，先以 `api-reference.json` 核对字段事实，再阅读对应端点文档中的来源语义说明。
2. 本快照是 Biohub wire contract 的外部证据，不自动成为产品或科学合同；与 `docs/target-contract-index.md` 指向的目标合同冲突时，必须显式裁决。
3. 不得把 `response.schema: null` 解释为“响应为空”；它只表示来源页未公开 schema。
4. 不得把公开模型枚举当作账户能力全集；来源页说明私有模型可能另行出现。
5. 更新快照时应一次刷新全部 9 个端点，并比较 `manifest.json` 的 definition SHA-256，避免只更新共享类型的一部分使用者。

## 已观察到的来源差异

- 用户给出的 `fold_all_atom` URL 使用 HTTP，抓取后规范重定向到 HTTPS；manifest 同时保存 requested/resolved URL。
- `fold` 的 `lm_mask_pct` 显示默认值与说明中的按模型缺省值并不完全等价，端点文档保留了该差异。
- `logits` 的 `ith_hidden_layer` 说明表使用的部分模型标识与顶层公开模型枚举不完全一致；不得静默改写。
