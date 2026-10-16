# Biohub 原始生成观测数据

本目录保留一次 ESM-3 生成研究的原始 JSON 与 PDB，不保存旧设计或验收报告。

## 数据位置

- [observations.json](2026-07-21-esm3-generation-outputs/observations.json)：记录请求配置、调用拓扑、输入输出字段、张量摘要、坐标摘要及数据来源元信息。
- [input-1pga.pdb](2026-07-21-esm3-generation-outputs/input-1pga.pdb)：输入结构。
- 同目录另外四份 PDB：两个模型的坐标条件 sequence 生成结果与双轨 denoise 结果；对应关系见 JSON 中的 observation ID 与文件名。

这些数据仅支持其中明确记载的模型、输入、SDK 与调用组合，不证明当前模型能力、当前实现状态或新源码的验收通过。JSON 内的来源元信息按原始数据保留；精确执行源码身份尚未核实，不能仅据该自述认定已恢复当时的完整执行身份。见[治理问题清单](../../2026-10-15-documentation-governance-issues.md)。

当前接口规则见[Biohub 接入说明](../product-contract-supplement.md)。
