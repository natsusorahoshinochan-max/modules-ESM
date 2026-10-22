# 原型：两种载体交付同一个变长设计请求

一次性设计实验。问题：用户编辑后的完整 mmCIF 与相同条件参数，能否替代原结构文件加外部位置映射，构造相同的 ESM 输入？

## 用户操作与两种交付

从真实 1PGA 的 A 链出发，在原 A11 后插入三位未知残基，删除原 A25，固定前五位序列，选取剩余来源位置的 N/CA/C 坐标作为条件。脚本通过相邻交互原型的 `export.cjs` 重放真实编辑动作，未修改用户操作的输出。

| 交付 | 内容 | 接收方读取方式 |
| --- | --- | --- |
| A | 原始 `1PGA.pdb`、`target_to_source`、序列条件、坐标条件 | 已真实执行生成的上一原型适配器 |
| B | 完整 `edited.cif`、相同序列条件、相同坐标条件 | Gemmi 读取标准类别后构造 ESMProtein |

B 的 `chain` 指 `_struct_asym.id` / `_atom_site.label_asym_id`；两边条件的 `target_index` 均从零起算，B 中等于 `label_seq_id - 1`。B 接收函数只读取 B 文件包，无需 A 的映射或源 PDB。

## 文件语义

- `_entity_poly_seq` 记录完整 58 位模板序列；新增位置使用标准化学组分 `UNK`，一字母序列用 `X`。
- `_atom_site.label_seq_id` 指向完整模板的顺序位置。新增三位没有原子行，55 个保留位置的坐标从原文件复制，未预测或松弛。
- `_pdbx_poly_seq_scheme` 同时列出所有目标位置。观测残基保留作者编号，新增位置的作者编号为 `?`。
- `_atom_site.auth_seq_id` 保留当前模板采用的作者命名。接收方编译本次生成条件时使用 label 位置，不依赖 auth 编号推断历史。跨对象比较若需要明确对应，应由那个操作的输入表达。
- 模板中存在的氨基酸及坐标，与本次固定条件分别表达；只有参数明确选中的前五位成为序列条件。

字段依据：[顺序位置定义](https://mmcif.wwpdb.org/dictionaries/mmcif_pdbx_v50.dic/Items/_entity_poly_seq.num.html)、[原子位置指向完整序列](https://mmcif.wwpdb.org/dictionaries/mmcif_pdbx_v50.dic/Items/_atom_site.label_seq_id.html)、[作者编号允许沿用完整或相关结构的编号](https://mmcif.wwpdb.org/dictionaries/mmcif_pdbx_v50.dic/Items/_atom_site.auth_seq_id.html)、[聚合物命名对应表](https://mmcif.wwpdb.org/dictionaries/mmcif_pdbx_v50.dic/Categories/pdbx_poly_seq_scheme.html)、[UNK 标准组分](https://www.ebi.ac.uk/pdbe-srv/pdbechem/chemicalCompound/show/UNK)。

## 执行与查看

在本工作树根目录执行：

```sh
/Users/sorachan/Documents/modules-ESM/.venv/bin/python modules/sequence_edit/prototype_cif_handoff/run.py --source-root /Users/sorachan/Documents/modules-ESM
```

使用已有 Python 环境、固定上游 ESM 源码和 Node。默认覆盖本目录的 `evidence/`；可用 `--output /private/tmp/prototype-cif-result` 指定独立输出目录。

- `evidence/user-actions.json`：实际重放的两步编辑。
- `evidence/route-a/`、`evidence/route-b/`：两种完整交付包。
- `evidence/comparison.json`：同一流程的比较结果和原生输入摘要。
- `evidence/native-inputs.npz`：两路线的实际坐标数组和原生序列 token。

## 本场景结论

Gemmi 与 Bio.PDB 均能读取 B：完整模板 58 位，55 位有原子。两路线生成的全部原生 ESMProtein 字段相等，包括未知位置、坐标数值和 NaN 分布；序列 token 也相等。B 的坐标与上一轮真实生成所用的输入数组相等，用户请求也一致，因此本次没有重复加载模型推理。

格式核对采用官方字段定义及两个实际解析器回读；未运行完整 PDBx/mmCIF 词典校验或结构归档提交校验。

本场景可以删除生成交接中的外部 `target_to_source`，将完整位置关系保存在标准 mmCIF 内。仍需把模型专属格式转换封装到适配器。实验范围止于这一个可达的生成输入交接；未执行折叠、评价或迭代筛选。
