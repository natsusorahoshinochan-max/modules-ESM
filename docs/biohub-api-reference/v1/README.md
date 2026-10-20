# Biohub 官方接口快照

- 请求字段、类型、默认值及约束：[api-reference.json](api-reference.json)。
- 来源链接、抓取时间、页面发布标识：[manifest.json](manifest.json)。
- 各端点说明：`endpoints/`。

## 共用约定

- 鉴权：`Authorization: Bearer <API_KEY>`。
- 请求媒体类型：`application/json`。
- 模型访问权限按账户授权配置。
- 来源未公开响应状态码、响应媒体类型、响应 body schema 和服务 base URL。
- `response.schema: null` 表示来源未公开响应 schema。

部分默认值的说明文字与字段表有差异，使用相关参数时核对所列来源。
`fold_all_atom` 联合类型的展示标签尚未确认为请求字段。
