# Prompt Studio 信息结构（一次性原型）

最后更新：2026-09-21

本目录保留内存交互原型，用于比较布局与操作可读性；刷新即重置。原型未连接生产后端，其中的模拟数据、接口和保存流程不定义当前产品协议。生产行为以[Prompt 编辑规格](../../../docs/2026-09-17-prompt-editing-spec.md)及[WebUI 运行说明](../../../webui/README.md)为准。

## 界面方向

方案 B「Residue ledger」：以残基矩阵为主，窄结构导航与联合编辑区同步。方案 A「Tri-pane balance」和 C「Selection lens」用于布局比较。

## 运行

从仓库根目录运行：

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-2-prompt-studio/serve.py
```

打开 <http://127.0.0.1:4180/?variant=B>。使用 `?variant=A/B/C` 切换布局。

## 交互观察

比较有坐标与无坐标样例；观察矩阵选区、结构导航、轨道编辑和局部操作确认的信息层级。

示例蛋白质、结构几何、参数、分数与来源标识只服务于交互演示。原型不能作为科学验收、持久化或生产接口测试的依据。
