## Parent

3GB1 条件生成 → ESMFold → TM-score → ProteinMPNN 完整设计管线

## What to build

构建一个可执行的 3GB1 四步设计管线，将 #12-#16 的新模块与现有模块串联为完整的端到端流程：

1. **ESM-3 条件生成**：从 3GB1 PDB 出发，随机掩码 20 个序列残基（#12）、随机插入 15 个 masked 残基（#13）、随机掩码 10 个结构位置（#12）、设置 SS track（E/H/None），组装 ProteinPrompt，通过统一 `esm3.generate`（#15）同时产出 10 个 (sequence, structure) pair
2. **ESMFold2 折叠 + 加权评分**：将 10 条序列送入 ESMFold2 折叠，用 `structure.batch_tm_score`（#16）分别计算 vs 3GB1（权重 0.7）和 vs 对应 ESM-3 结构（权重 0.3）的 TM-score，加权排序后取 top 3
3. **ProteinMPNN 50% 重设计**：对 3 个 top ESMFold 结构，用 #14 随机固定 50% 位置，各生成 5 条新序列（共 15 条）
4. **最终 ESMFold2 折叠**：将 15 条 ProteinMPNN 序列折叠为 PDB，产出 15 个最终文件

交付形式可以是 workflow JSON（纯 DAG 节点 + 边）或 Python 编排脚本（调用 adapter 层串联各模块），选择更简洁可靠的方式。

## Acceptance criteria

- [ ] 管线可从头执行至完成，无未处理异常
- [ ] 最终产出恰好 15 个 PDB 文件
- [ ] 步骤 1 的 ESM-3 prompt 满足：sequence track 中 20 个位置 masked + 15 个插入的 masked 位置，structure track 中 10 个位置坐标被移除，SS track [1,19]=E、[23,30]=H、[35,56]=E
- [ ] 步骤 2 的加权排名使用 0.7 × TM-score(vs 3GB1) + 0.3 × TM-score(vs ESM-3 structure)，top 3 被正确选出
- [ ] 步骤 3 的每个 top 结构恰好生成 5 条 ProteinMPNN 序列，共计 15 条且每条序列长度与结构一致
- [ ] 步骤 4 的 15 条序列均成功折叠并输出有效 PDB

## Blocked by

- #12 prompt.random_mask
- #13 prompt.random_insert_masked
- #14 prompt.random_fixed_positions
- #15 unified esm3.generate
- #16 structure.batch_tm_score
