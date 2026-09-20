# Import、correspondence 与 merge（一次性原型）

最后更新：2026-09-21

本目录保留内存交互原型，用于比较布局与操作可读性；刷新即重置。原型未连接生产后端，其中的模拟数据、接口和保存流程不定义当前产品协议。生产行为以[Prompt 编辑规格](../../../docs/2026-09-17-prompt-editing-spec.md)及[WebUI 运行说明](../../../webui/README.md)为准。

## 界面方向

方案 B「证据分屏」：左栏展示 source / target 的 chain 与 residue locator，中栏展示对应关系，右栏展示轨道选择和操作结果。方案 A「对应账本」和 C「关卡式确认」用于布局比较。

## 运行

从仓库根目录运行：

```bash
.venv/bin/python .scratch/webui-product-definition/prototype-4-import-merge-alignment/serve.py
```

打开 <http://127.0.0.1:4182/?variant=B>。使用 `?variant=A/B/C` 切换布局。

## 交互观察

观察来源与目标的对应表、轨道选择、定位提示和确认操作能否放在同一视野中阅读。

示例蛋白质、结构几何、参数、分数与来源标识只服务于交互演示。原型不能作为科学验收、持久化或生产接口测试的依据。
