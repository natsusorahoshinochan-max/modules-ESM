# 01 — Repair all independently reviewed Protein Workbench v2 defects

**What to build:** 按已批准的全局纠正规格，使用最小且直接的修改修复独立审查确认的实现缺陷、合同偏差、科学输入保真问题、运行一致性问题和有功能伤害的过度防御。修复后的 backend 必须保留合法科学语义，拒绝不闭合输入，并产生可重复验证的 Run、Candidate、Observation、provider 与安装态证据。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] 为全局规格中的每个已确认问题保留一个能在旧实现失败、在修复后通过的最小回归测试。
- [ ] Candidate、canonical identity、Contract Lock 与公共 schema validation 对合法值稳定，对内容篡改和不闭合引用可靠失败。
- [ ] FASTA、Residue Layout、ProteinPrompt、Folding、ProteinMPNN、DSSP 与 ESM-3 不再静默拼接、重编号、丢失链/坐标/约束或拒绝 provider 合法值。
- [ ] Structure Alignment、TM-score、Selection Objective 与 Observation Context 绑定精确 Candidate、PDB、Method 和 normalization 语义，并在执行前拒绝非法配置。
- [ ] cancellation、Attempt、Ledger、Cache、Derived Run 与 event replay 在失败、取消、重启和重放下保持一致且可恢复。
- [ ] Readiness 与 provider identity 只证明实际 Binding、Adapter 和消费资产；删除值形状脱敏、参数名黑名单、任意 JSON 禁词扫描及 sibling 资产耦合等有害防御。
- [ ] 保留 filesystem 原子发布、symlink resistance、owner/mode/nlink、fsync、Ledger no-replace、因果验证和 schema-scoped secret redaction。
- [ ] 必要的合同升版和 Workflow relock 明确完成，不为错误旧行为增加兼容层。
- [ ] focused tests、routine、deterministic acceptance、scientific reproducibility、provider isolation、security failure 与 installed-package gates 全部通过。
- [ ] 从干净安装产物完成公共 zero-Core、canonical 3GB1 和 required provider journeys；最终 retained evidence 可独立验证。
