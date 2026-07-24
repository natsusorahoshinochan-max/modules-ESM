# Biohub Platform Reference

## 产品补充

- [Biohub / ESM 产品合同补充](product-contract-supplement.md) — 规范性记录本仓库已接受的模型身份、产品能力与 catalog 边界

## 带日期运行与研究证据

- [Biohub / ESM 真实运行观测](observed-runtime-overlay.md) — 带日期的非规范性实测证据，用于判断当前模型事实上支持什么
- [ESM3 generation output study](research/README.md) — 按提交冻结的专项研究包；历史实现描述不自动等于当前实现

## 可用快照

- [API v1](v1/README.md) — 抓取于 `2026-07-16`，页面发布标识 `sha-7062746`

版本目录中的 `manifest.json` 记录来源 URL、重定向结果与定义哈希；`api-reference.json` 是请求
wire 事实对照优先使用的机器可读文件。版本快照保持不可变，只证明其明确发布的请求 path、
字段、枚举、范围与默认值，不证明当前模型已经实现某个请求字段，也不定义响应字段或 shape。

三层材料的职责是：dated live observation 裁决当前 Biohub 事实支持，目标合同与产品补充定义
本项目产品，`v1/` 快照证明 endpoint / request wire。发现冲突时，不修改固定快照；应先记录
新的真实运行证据，再同步修改目标合同、实现与测试。
