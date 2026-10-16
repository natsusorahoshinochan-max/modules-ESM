# 整批与按骨架范围的 Top-k

范围由用户连线决定。下面同一组候选和已有评分可以同时产生整批 Top-2 与每个骨架的 Top-1，不新增固定分组节点。

## 关联与评分

设独立导入的序列分为 A1、A2 和 B1、B2，评价参考分别是骨架 A、B。两组各用 `collection_ops.relate_to_single_reference` 指定评价关系，再用 `concat_candidates` 合并序列与骨架、`concat_relations` 合并关系。导入候选的 `parent_ids` 保持原值；评价关系不是生成谱系。

把序列、参考骨架与明确关系传入兼容的评分操作。评分操作仍保留其实际产生的 Score Collection；Top-k 只消费已有结果。所选 Metric、Method、Context、partition 和 Utility Transform 必须来自该评分操作的公开声明，不以显示名称或当前默认值代替。

## 画布连线

| 节点 | 输入与参数 | 输出用途 |
|---|---|---|
| `all_candidates`：`concat_candidates` | 两组序列集合 | 整批候选及两条范围选择的 `subjects` |
| `all_relations`：`concat_relations` | 序列→骨架 A、序列→骨架 B | 两条范围选择的 `relation` |
| `scope_a`：`select_related_subjects` | `subjects=all_candidates`、`selected_references=骨架 A`、`relation=all_relations` | 骨架 A 对应候选及其关系 |
| `scope_b`：`select_related_subjects` | 同上，参考改为骨架 B | 骨架 B 对应候选及其关系 |
| `global`：`selection.top_k` | `candidates=all_candidates`、已有 `scores`、`k=2` | 整批前两名 |
| `per_a`：`selection.top_k` | `candidates=scope_a.candidates`、同一 `scores`、`k=1` | 骨架 A 前一名 |
| `per_b`：`selection.top_k` | `candidates=scope_b.candidates`、同一 `scores`、`k=1` | 骨架 B 前一名 |

每个 Top-k 使用独立 Selection Objective，`candidate_input` 指向本分支候选输出，`score_collection_input` 指向评分输出。其余评价身份与转换相同。候选范围可以不同于评分操作最初的主体输入端点，匹配仍使用完整 Candidate Data Reference。

各分支设置 `out_of_scope_policy: ignore`，明确忽略同一 Score Collection 中其他范围的观察；这不忽略本范围内缺失或多义的必需观察。`match_cardinality: exactly_one` 和 `missing_policy: error` 保持严格含义。现有实现限制 `k` 不能超过本分支候选数，这与已确认的“最多取 k 个”要求冲突，须在重构中修正。

## 重构边界

以上为现有实现的组合方式，不是重构后的接口契约。目标要求为节点本地规则、按原值排序、最多取 k 个；候选不足时返回全部。重构测试须依据[当前有效决策](../../docs/documentation-governance-decisions.md#筛选规则与排序)从零编写。
