## Parent

> **Status: superseded historical v1; do not implement.** The v1 runtime was removed. This file is retained only as historical planning evidence and creates no current compatibility requirement.

3GB1 条件生成 → ESMFold → TM-score → ProteinMPNN 完整设计管线

## What to build

新增 `structure.batch_tm_score` 模块：接受一个 reference 结构和一批 candidate 结构（通过 `candidate.collection` 端口），对每个 candidate 依次做结构对齐 + TM-score 计算，输出一个 `ScoreCollection`，其中每个 candidate 对应一条 `tm_score` entry。subjects 指向对应 candidate 的 ID，确保下游 `selection.weighted_rank` 可直接通过 subject ID 匹配。

该模块合并了「对齐 + TM-score」两步，避免了 workflow DAG 中为每个 candidate 单独创建 `structure.align` + `structure.tm_score` 节点的需求。内部复用现有 `structure.align` 模块的 SVD 对齐逻辑。

## Acceptance criteria

- [ ] 输入 1 个 reference 结构 + 包含 3 个结构的 candidate collection，输出 ScoreCollection 有 3 条 `tm_score` entry
- [ ] 每条 entry 的 score_id 为 `tm_score`，subjects 指向对应 candidate 的 candidate_id
- [ ] reference 与自身对齐时 TM-score ≈ 1.0
- [ ] 空 candidate collection 时抛出明确错误
- [ ] reference 或 candidates 为 None 时抛出明确错误

## Blocked by

None — can start immediately.
