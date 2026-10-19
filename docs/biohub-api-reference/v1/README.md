# Biohub 官方接口快照

核对 Biohub 请求字段时，查 [api-reference.json](api-reference.json)。[manifest.json](manifest.json) 保存来源链接、抓取信息和字段定义摘要；`endpoints/` 是各端点的固定接口资料。

快照抓取于 `2026-07-16T03:56:50.184Z`，页面发布标识为 `sha-7062746`。其中的 HTTP 路径、请求字段、类型、默认值与约束只说明该次官方资料，不表示当前账户支持全部模型。

来源未公布的响应 schema 与服务 base URL 不能从空字段推断。`response.schema: null` 表示未公开 schema。部分默认值说明与字段表有差异，须回到所列官方来源核对。`fold_all_atom` 联合类型中的展示标签是否为请求字段尚未确认，不能直接当作 JSON 键使用。
