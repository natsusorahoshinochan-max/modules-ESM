# Biohub Platform Reference

## 当前产品合同

- [Biohub / ESM 当前产品合同](product-contract-supplement.md) — 解释官方 Provider
  specification、active Method/Binding、Adapter translation 和 Acceptance Evidence 的
  单一职责

## 带日期运行与研究证据

- [Biohub / ESM 真实运行观测](observed-runtime-overlay.md) — 绑定日期、revision、SDK、model
  和环境的非规范性历史 Evidence，不定义当前产品能力
- [ESM3 generation output study](research/README.md) — 按提交冻结的专项研究包；历史实现描述不自动等于当前实现

## 可用快照

- [API v1](v1/README.md) — 抓取于 `2026-07-16`，页面发布标识 `sha-7062746`

版本目录中的 `manifest.json` 记录来源 URL、重定向结果与定义哈希；`api-reference.json` 是请求
wire 事实对照优先使用的机器可读文件。版本快照保持不可变，只证明其明确发布的请求 path、
字段、枚举、范围与默认值，不证明当前模型已经实现某个请求字段，也不定义响应字段或 shape。

Biohub 官方 specification 与仓库固定的官方 SDK revision 定义 Provider wire facts；active
Catalog 的 Method/Execution Binding 定义本项目当前公开的 model、operation、固定配置和科学
解释；concrete Adapter 实现唯一翻译；dated live observation 只证明一次 acceptance 或集成
调查。历史运行结果不能覆盖官方合同、扩大或缩小 active Catalog，也不能生成兼容解析、
expected-failure 产品分支或 fallback route。
