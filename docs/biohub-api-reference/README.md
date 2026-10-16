# Biohub API 参考入口

修改 Biohub Adapter 或核对请求字段时，先读[接入说明](product-contract-supplement.md)，再查对应的[官方 API v1 快照](v1/README.md)及[固定 SDK](../../repositories/esm/esm/sdk/)。适用的产品要求见[当前决策](../documentation-governance-decisions.md)。

## 官方快照

[API v1](v1/README.md)抓取于 `2026-07-16`，页面发布标识为 `sha-7062746`。`manifest.json` 保存来源及抓取信息，`api-reference.json` 保存规范化请求字段；`endpoints/` 提供人工阅读视图。

快照是其抓取时官方资料的固定副本。本地材料未发布响应 schema，不能将 `schema: null` 解读为响应为空，也不能由字段表或运行样本猜出缺失的 schema。官方 API 定义 Provider 请求与处理结果；项目参数声明和实现差异不能覆盖官方事实。

## 项目接入与原始数据

- [Biohub / ESM 接入说明](product-contract-supplement.md)：模型路线、输入翻译、结果含义与接入约定；其中参数开放的实现状态见下列参数审查。
- [Provider 配置](../provider-configuration.md)：当前应用内模块运行设置、部署配置及各路线前提。
- [工具参数开放审查](../tool-parameter-exposure-audit.md)：当前可配置参数、路线默认值、限制及核验范围。ESM3 paired 已分别配置序列与结构阶段，`invalid_ids`、坐标条件开关及 ESMFold2 适用推理参数均已接入。
- [原始生成观测数据](research/README.md)：保留的 JSON 与 PDB 数据及其适用范围，不作为当前验收记录。

接口核对依据官方规范，不从原始观测中推导新的能力限制、重试、兼容解析或回退路线。
