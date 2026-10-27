# 仓库规则

当前项目正在重做前端和UI。

## 文档规范

按文档用途保留内容：需求说明行为，架构说明职责与交接，
操作说明提供必要步骤和资源位置。工作经过放在提交说明中，不进入文档。

新增文字中同一规则集中维护；避免换句话重复。

"不代表"、"不意味" 的免责声明是被禁止的恶心的废话。

## 阅读入口

- 设计、实现或审查行为前，读 [需求](docs/requirements.md)。未确认的提议或实现偏差不算需求。
- 探索代码前，读 [术语](GLOSSARY.md)；改动模块接入、执行、数据交接、工具替换或保存时，读 [目标架构](docs/architecture.md)。
- 核对 Biohub 请求时，查 [官方接口快照](docs/biohub-api-reference/v1/README.md)；核对其他工具时，直接查其官方说明、SDK、CLI 或固定上游源码。

## 修改与验证

修改时更新所有调用方和相关文档，删除被替代实现。不加旧解析器、别名、兼容层、双轨实现或尚无用途的抽象。

旧数据清理范围按需求文档执行，保留原始研究文件。

`repositories/` 固定的是上游源码，需要保持不变。

## GitHub 任务

使用 `natsusorahoshinochan-max/modules-ESM` 的 GitHub Issues 跟踪任务。读 ticket 时读正文、标签和评论；多行正文先写临时文件，再用 `gh --body-file`。父子任务使用原生 sub-issues，阻塞关系使用 issue dependencies。创建 issue 不表示提议已确认；PR 不作为任务受理入口。

分类时使用五个标签：`needs-triage` 待评估、`needs-info` 待补充、`ready-for-agent` 可由 agent 执行、`ready-for-human` 需人工实施、`wontfix` 不处理。
