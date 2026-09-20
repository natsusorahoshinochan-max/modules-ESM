# 残基选区的刚体编辑（一次性原型）

最后更新：2026-09-21

本目录保留内存交互原型，用于比较布局与操作可读性；刷新即重置。原型未连接生产后端，其中的模拟数据、接口和保存流程不定义当前产品协议。生产行为以[Prompt 编辑规格](../../../docs/2026-09-17-prompt-editing-spec.md)及[WebUI 运行说明](../../../webui/README.md)为准。

## 界面方向

单一交互原型：结构视口、明确残基选区与变换状态面板相邻，支持连续和不连续选择。

## 运行

从仓库根目录运行：

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-5-residue-structure-editing/serve.py
```

打开 <http://127.0.0.1:4183/>。

## 交互观察

用左键、Shift 和 Ctrl/Cmd 选择位置；用 G / R 进入变换预览、X / Y / Z 约束示意轴，Enter 确认、Esc 取消、Ctrl/Cmd+Z 撤销。相机操作与选区操作分开观察。

示例蛋白质、结构几何、参数、分数与来源标识只服务于交互演示。原型不能作为科学验收、持久化或生产接口测试的依据。
