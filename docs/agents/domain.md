# Domain Docs

## 阅读规则

探索代码前，阅读根目录 `GLOSSARY.md`。
审查或修改业务代码前，按根目录 `AGENTS.md` 的要求阅读当前有效决策、
文档治理问题清单及文档索引；同时阅读与本次工作相关的 ADR。

## 布局

采用 single-context：

- `GLOSSARY.md`：仓库根目录的共享领域词汇。
- `docs/adr/`：按需创建的领域与架构决策文档。

ADR 目录或相关文档不存在时，继续工作，无需预先创建占位文档。
实际明确术语或决策时，再由 domain-modeling 技能维护相应文档。

## 使用规则

输出中的领域概念采用与当前有效要求一致的 glossary 术语。
发现术语缺口时，明确指出，供 domain-modeling 处理。

当前有效产品要求以 `docs/documentation-governance-decisions.md` 为准。
发现 glossary、ADR 或实现与其冲突时，明确指出并修正相应文档；
实现情况和未解决差异分别记录，不将实现偏差写成新需求。

文档只保留当前有效内容，遵守根目录 `AGENTS.md` 的文档治理规则。
