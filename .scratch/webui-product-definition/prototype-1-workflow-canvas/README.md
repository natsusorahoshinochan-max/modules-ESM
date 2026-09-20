# Workflow 画布（一次性原型）

最后更新：2026-09-21

本目录保留内存交互原型，用于比较布局与操作可读性；刷新即重置。原型未连接生产后端，其中的模拟数据、接口和保存流程不定义当前产品协议。生产行为以[WebUI 集成计划](../../../docs/2026-09-17-webui-full-integration-plan.md)及[WebUI 运行说明](../../../webui/README.md)为准。

## 界面方向

方案 A「Graph cards」：自由空间画布、左侧 Authoring Palette、卡片边缘 Ports，以及卡片内部的参数与专用编辑入口。方案 B「Signal spine」和 C「Lab bench」用于布局比较。

## 运行

从仓库根目录运行：

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-1-workflow-canvas/serve.py
```

打开 <http://127.0.0.1:4179/?variant=A>。使用 `?variant=A/B/C` 切换布局。

## 交互观察

观察节点收起与展开、Palette 搜索、连接可读性和专用编辑入口。

示例蛋白质、结构几何、参数、分数与来源标识只服务于交互演示。原型不能作为科学验收、持久化或生产接口测试的依据。
