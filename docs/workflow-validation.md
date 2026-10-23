# 长流程验收

使用一条可编辑流程检查模块交接、逐项执行和多轮反馈。流程文件通过公开 HTTP 接口保存，随后可在画布中打开、修改和运行。脚本默认只创建项目；运行时使用应用中明确配置的 ESM3 工具与凭据。

## 准备与执行

先按 [README](../README.md#启动) 启动应用，在 ESM3 模块设置中配置 Biohub 凭据或已有本地资源。固定输入位于 [真实比较样本](../tests/fixtures/real_comparisons/README.md)：两个 58 位蛋白结构与独立的 56 位 1PGA 参考。

在仓库根目录执行，`--output` 指定保存计划与验收记录的目录：

```bash
.venv/bin/python tests/manual_design_workflow.py \
  --base-url http://127.0.0.1:8000 --build-only --output /private/tmp/design-workflow-check
```

脚本输出新项目的 `project_id`。在画布打开该项目检查接线后，可点击 Run，或执行：

```bash
.venv/bin/python tests/manual_design_workflow.py \
  --base-url http://127.0.0.1:8000 --run-project PROJECT_ID --output /private/tmp/design-workflow-check
```

运行由服务器管理；关闭检查脚本后可在应用中查看或取消。若使用界面启动，完成后单独核验该运行：

```bash
.venv/bin/python tests/manual_design_workflow.py \
  --base-url http://127.0.0.1:8000 --verify-run RUN_ID --output /private/tmp/design-workflow-check
```

## 流程与检查

流程合并并拆分两个模板，用 Repeat 执行两轮。每轮的 Map 对每个模板插入两个位置、删除一个位置，固定前五位 `MTYKL`，选择 11 位 N/CA/C 坐标作为条件；联合生成两个候选，与明确输入的参考做 TM-align。按 TM-reference 阈值及降序上限筛选，每个模板至多保留一个，再合并、拆分并反馈。

默认阈值为 0.1，序列生成 2 步、结构生成 4 步，温度 0.5；这些是验收参数，可在创建时调整，见脚本 `--help`。若两模板均保留，将发生 8 次序列生成、8 次结构生成和 8 次比较。阈值产生空集合时按实际结果执行，脚本记录模板数量变化。

`flow.json` 保存配置，`run.json` 保存实际调用记录，`verification.json` 保存核验结果。检查器读取实际交付文件，核对 59/60 位目标、固定序列、坐标条件、序列和结构阶段输出、固定参考及反馈包。筛选预期由原始比较分数独立计算，再与各轮交付名单比较。

改变筛选位置、参考输入或条件时，另存项目并按新配置定义预期。上述检查器对应这里列出的两轮配置；通用控制流的空集合、失败、取消、原调用续算与未来轮次模块缺失检查位于 `tests/test_host_scopes.py`。
