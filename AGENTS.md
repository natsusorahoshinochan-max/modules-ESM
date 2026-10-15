# Repository Guidelines

## 文档

文档和代码注释只保留当前有效内容，明确区分已确认要求、实际实现状态和未解决差异。代码用于证明实现情况，不用于推翻已确认要求；已确认要求也不代表实现已经完成。

更新时直接替换失效内容，不保留 AI 对话记录、开发流水账、失效开发阶段叙事、旧方案或旧验收档案。可以记录当前问题、证据位置和核验范围；问题解决后更新当前结论，不保留演变流水。未经确认的实现偏差不得写成新需求。

## 当前工作：文档治理

现行说明按架构、执行、工作区、结果、Prompt、模块与配置组织，入口见[文档索引](docs/README.md)。当前文档治理维护尚未解决的实现差异与待核实事实。开始审查或修改项目文档前，阅读以下依据：

- [当前有效决策](docs/documentation-governance-decisions.md)：用户已确认的产品要求、开发约束和范围边界，是判断目标行为的依据。
- [文档治理问题清单](docs/2026-10-15-documentation-governance-issues.md)：已发现问题、证据及处理状态，是排查入口；其中疑点和未核实事项不是已确认需求或已证明缺陷。

按当前决策核对并修正文档，同步更新问题状态；问题清单仅保留当前未解决项。其他文档的“已确认”“已完成”等自述不能覆盖上述决策；代码只读用于核实实现。除非用户另行授权，文档治理不修改应用代码或启动功能重构。移除失效文档前提取其中仍有效的要求，不另存历史档案，不删除用户项目、运行结果或原始研究数据。

## Priorities

本项目对科学性的定义是：正确传参数。按照用户要求和工具官方接口正确传递输入与参数。使用 [CONTEXT.md](CONTEXT.md) 中与当前有效要求一致的术语；发现冲突时明确指出并修正文档，不以旧定义限制已确认功能。

There is no historical compatibility obligation. Do not add shims, aliases, legacy parsers, dual paths, deprecation layers, or speculative abstractions. When changing code, change all current producers, consumers, tests, examples, and documentation together; delete superseded code. Superseded development artifacts may be invalidated without compatibility support. This does not permit silent loss of saved user work or invalidating an adopted input when its source project is deleted.

## Architecture

载体负责模块管理、流程编排、运行、保存和数据传递等通用能力。功能模块提供具体操作及专用界面；模型、算法和外部服务由模块内部调用。一个模块可以提供多个节点，同一工具可以服务多个模块。官方与外部模块遵守同一套接入规范，官方功能不绕过公共接口。

`core/` owns runtime and necessary execution records, not tool-specific scientific behavior or a mandate to expand evidence systems. `datatypes/` defines shared provider-independent values; modules may declare their own data types through the extension contract. Repository-owned module sources live in `modules/<package>/`; provider translation belongs in Adapters. This source layout does not require external plugins to become repository source. `protein_workbench_public/` owns the public protocol, not hard-coded scientific-module reading or interaction paths. Treat `repositories/` as pinned upstream, except for the project-owned SoluProt-next Provider source.

## Trust Model

This is a trusted, single-user, loopback-only application. Components trust values after validation by their contract-owning boundary. Validate once; do not add repeated checks, authentication, authorization, multi-tenancy, adversarial handling, sandboxing, or hosted-service hardening.

Biohub and its official API specification are authoritative. Assume conforming requests receive conforming responses. Adapters must translate inputs and parameters according to the official API specification. Do not guess schemas, repair or reject responses, cross-check providers, add fallback endpoints, or handle hypothetical malformed responses. Follow documented operational outcomes exactly.

Fail fast on local invariant violations. Avoid broad catches, silent coercion, guessed defaults, catch-and-continue behavior, and undocumented retries or fallbacks. Retain checks only for correct parameter passing, explicit contracts, durable writes, accidental data loss, and credential hygiene.

Distinguish local invariant violations from defined operational failures. Apply the current execution requirements for failure handling, result retention, and user-initiated continuation; never record a failure as success.

## Verification

For read-only audits and changes limited to explanatory text, links, or formatting, check content and references without running executable verification. For changes affecting executable examples, configuration, or code behavior, read and follow the complete execution policy and verification gates in [backend verification](docs/backend-verification.md#execution-policy); this scope distinction does not reduce required gates. For WebUI changes, also use the verification entry points in [webui/README.md](webui/README.md).

Run tests, type checks, builds, browser checks, and Providers only on the remote verification host. Use Python 3.12, typed code, and pytest. Test correct parameter passing and current package contracts. Mocks cannot replace required real-provider acceptance. The backend verification gate is independent of the WebUI. Keep execution commands and the verification matrix in the linked verification documents rather than duplicating a partial gate here.

Never commit `.local/`, `keys/`, environments, or client build output.
