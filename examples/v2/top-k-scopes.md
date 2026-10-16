# 整批与按骨架范围的 Top-k

范围由用户连线决定。下面同一组候选和已有评分可以同时产生整批 Top-2 与每个骨架的 Top-1，不新增固定分组节点。

## 关联与评分

设独立导入的序列分为 A1、A2 和 B1、B2，评价参考分别是骨架 A、B。两组各用 `collection_ops.relate_to_single_reference` 指定评价关系，再用 `concat_candidates` 合并序列与骨架、`concat_relations` 合并关系。导入候选的 `parent_ids` 保持原值；评价关系不是生成谱系。

把序列、参考骨架与明确关系传入兼容的评分操作。评分操作仍保留其实际产生的 Score Collection；Top-k 只消费已有结果。所选 Metric、Method、Context、partition 必须来自该评分操作的公开声明，不以显示名称或当前默认值代替。

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

每个 Top-k 在自己的 `node_parameters` 中保存评价和排序方向，普通连线给分数来源分配节点本地稳定槽：

```json
{
  "selection": {
    "score_input": "evaluations",
    "metric_id": "所选指标的稳定身份",
    "method_id": "实际评价方法的稳定身份",
    "source_partition": "实际评分分区",
    "context": {"kind": "intrinsic"}
  },
  "direction": "descending",
  "k": 2
}
```

对应分数连线使用 `target_port: "scores"`、`target_slot: "evaluations"`。示例中的身份占位值须由节点编辑器按实际观察选择，不能直接作为可运行配置。成对评价采用该来源的 pairwise Context Profile；存在多个参考时连接普通 `relations` 输入，并在 `selection.relation_input` 中选择相应稳定槽，或从已有结果选择精确实际 Context。主体各自可有不同参考对象，不用生成父子关系代替评价关系。

各节点分别设置自己的 `k`。它们只匹配本分支候选的评价，共用评分中的其他观察不影响选择；本范围缺分或仍有歧义时停止。方向直接解释指标原值，不需要评分转换。同分保持本分支输入顺序。Top-k 表示最多 k 个，不足取全部，空集合返回空集合；并列不扩充数量。

该组合使用普通节点及连线决定范围，不新增固定的按骨架模式。输出保留原候选内容、身份、metadata 和生成来源。
