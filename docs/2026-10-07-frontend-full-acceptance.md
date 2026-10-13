# 前端原型集成：完整回归与真实运行验收

结论：最终冻结快照通过全部基础检查、19 项真实 Provider 验收和 6 项真实浏览器流程。
最终验收结束时间为 2026-10-07 00:06:10（Asia/Taipei）。本记录证明下列快照及产物，
不把历史通过结果用于证明后续源码，也不代表已经替换用户正在浏览的开发服务。

## 修复了什么

这次验证覆盖原型集成后的画布、结果跳转、Prompt 编辑与保存、G/R 本地预览、
运行确认对话框，以及从实际页面发起的完整模型流程。

| 问题 | 原因 | 修复与验证 |
| --- | --- | --- |
| 旧浏览器测试找不到节点或按钮 | 默认示例改为分组导航，Prompt 保存改为单次提交，部分测试仍使用旧入口 | 按当前交互更新定位，保留精确文档、修订号和运行语义断言 |
| 新建 Prompt 保存后缺少节点布局 | 新节点有渲染兜底坐标，但写回画布时未持久化 | 保存图时补齐缺失节点坐标，保留已有位置；新增 Prompt 场景验证所有节点的位置 |
| Prompt 保存的 UI 状态对比偶发失败 | 测试在进入编辑器及布局保存结束前读取基线 | 等待实际页面和保存状态后读取基线，不放宽深度相等检查 |
| 5 项真实浏览器流程等待不存在的阶段导航 | API 复制的个人项目保留平铺布局，不应用默认示例专用分组预设 | 适合视图后按确切作者节点打开；新增普通 API 副本编辑与保存回归 |
| 新增回归找不到目标残基 | AG Grid 横向虚拟化尚未渲染视口外的残基列 | 复用已有滚动定位方法，在普通及真实流程中先呈现目标列，再真实点击 |
| 真实 5G53 在 PAE 验收处失败 | 测试将 ESM-3 可选 PAE 当成必需；失败 Run 本身已成功 | 按现行接口保留缺失值；存在时检查完整 L×L，并独立要求 ESMFold2 PAE |

PAE 调查读取的是失败运行的持久化输出：12 条 ESM-3 confidence fact 的 PAE 为
`None`，6 条 ESMFold2 fact 的矩阵尺寸正确。当前 ESM-3 Node Type 已声明
`optional PAE`，Method 已声明 `L_by_L_or_none`；此次未改 Adapter、模型请求、
Provider 返回值、随机性、科学阈值或残基映射。修复的是验收与现行合同的不一致。
配对 Adapter 回归现在同时覆盖 PAE 存在和缺失，仍检查结构、pTM/pLDDT 尺度及调用因果。
5G53 中候选配对、prediction key、lineage、loop evidence 和 artifact 断言保留。

## 最终结果

所有执行均在远端 Python 3.12 环境完成。各轮固定源码，独立检查全部收集后集中修复。
基础检查未全通过时不启动真实 Provider；正式 Campaign 保持既有遇失败停止的语义，
独立浏览器验收仍执行并收集全部用例。运行期间按 30 分钟间隔检查状态。

| 基础检查 | 结果 |
| --- | --- |
| 聚焦后端回归 | 383 passed |
| routine | 1806 passed |
| examples-v2 / workflow-stress | 11 / 11 passed |
| deterministic-acceptance / scientific-repro | 6 / 1 passed |
| local-esmfold2-v2-contract / installed-package | 9 / 4 passed |
| 前端、普通测试、真实测试 TypeScript 检查 | 全部通过 |
| lint / build | 全部通过 |
| 普通浏览器端到端测试 | 200/200 passed |
| 科学基线 | 9 个值、28 个 Port、219 个科学描述符一致 |

真实 Provider Campaign 为 **19/19 passed**：11 项安装产物 Provider gate，加上
1PGA、2EMO、canonical 3GB1、5G53 的远端和本地两条路线。

构建后的 WebUI 使用隔离数据与安装后的 wheel，真实浏览器流程 **6/6 passed**：

1. FASTA → 溶解度筛选 → 折叠 → 置信度排序、保存 Selection 与导出。
2. 自行编辑 Prompt → ESM-3 → refold、精确阶段分数与筛选保存。
3. ProteinMPNN 后代、父级关系、对齐证据和混合数据导出。
4. 运行中取消，保留已发布证据。
5. 取消后删除，验证生命周期及证据。
6. 等待完成后删除，验证生命周期及证据。

FASTA 独立证据报告通过；安装后浏览器冒烟检查 **3/3 passed**。两位复用的审阅代理
分别完成代码/科学断言审阅及 TypeScript/交互测试审阅，无未解决发现。

## 可追溯证据

远端证据根目录：`/root/autodl-tmp/frontend-full-20261006/`。

- 冻结源码：`round-06/source/`。
- 源码 manifest SHA-256：`8853caac64406c7bfceab495db91acd2043864df35e1f1da573d2eb9b60706f3`。
- wheel SHA-256：`4108bfe233bb8434b8fbc3c11f1f29c105b0866581ca8cadafcf3d749a1967c5`。
- 基础检查结果与各自日志：`round-06/summary-all.json`、`round-06/logs/`。
- 最终结果：`final-round-06/summary.json`，`passed: true`、`source_changes: []`。
- 正式验收：`final-round-06/campaign/campaign.json` 及其 `results/`。
- 真实浏览器：`final-round-06/ui/ui-evidence/`，含 JUnit、trace、截图及运行证据。
- 先前失败的冻结快照及日志保留于 `round-01` 至 `round-05` 和 `final-round-04`。

本地忽略目录 `.local/full-frontend-20261006/` 保存检查摘要与源码 manifest 副本，
不提交运行产物或私密配置。记录生成前核对本地文件与最终测试 manifest 一致；
其后仅添加本验收记录及 README 文档入口。


## 2026-10-13 提交整理

提交前重新比对最终验收 manifest：运行代码与测试内容保持一致，另去除矩阵定位
测试辅助文件末尾的一个多余空行。其余后续改动仅涉及 Git 忽略规则、取消跟踪本机
`.scratch/` 实验、部署文档及原型链接纠正。取消跟踪保留本机文件，未改写历史提交。
通用部署说明不依赖验收服务器；上文远端路径仅标识历史证据位置。本次整理未重新
运行模型，也未将该轮验收扩大为所有操作系统或所有 Provider 平台的兼容性证明。
