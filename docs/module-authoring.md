# 模块接入与文件交付

行为范围见 [需求](requirements.md)，职责与文件交接见 [架构](architecture.md)。Python 作者入口为 `protein_workbench_public.module_api`，该入口只依赖标准库。

## Python 声明

模块提供一个无参数工厂，返回 `Module`。用户安装 Python 包后，通过应用登记 `包名.模块名:工厂名`。工厂声明节点、配置字段和可选的浏览器入口；配置保存在应用数据目录中，与节点计算参数分开。

```python
from shutil import copyfileobj

from protein_workbench_public.module_api import (
    Delivery, InputPort, Module, Node, Outcome, OutputPort,
)


def execute(call, runtime):
    source = call.inputs["source"][0]
    output = runtime.workdir / "output.bin"
    with source.open(source.entry) as reader, output.open("wb") as writer:
        copyfileobj(reader, writer, length=1024 * 1024)
    return Outcome(outputs={
        "result": [Delivery(
            format="my_lab.binary",
            entry="data",
            files={"data": "output.bin"},
        )],
    })


def module():
    return Module(
        id="my_lab.copy",
        name="Binary copy",
        nodes=(Node(
            id="my_lab.copy_file",
            name="Copy file",
            execute=execute,
            inputs={"source": InputPort(accepts=("my_lab.binary",))},
            outputs={"result": OutputPort(format="my_lab.binary")},
        ),),
    )
```

`Call.inputs` 按端口提供有序数据包，`parameters` 提供节点参数，`settings` 提供模块部署配置。输入包通过 `format`、`entry`、`files` 描述内容，用 `open(文件键)` 获取只读二进制流。模块在自己的公开格式文档中说明文件内容、对应关系与样例，独立消费者据此读取。

## 交付文件

将输出写入 `runtime.workdir`，完成写入并关闭后返回 `Outcome`。`Delivery.files` 的键供包内读取使用，值为该工作目录内的相对来源路径；`entry` 选择其中一个键，可以指向二进制文件。返回后由载体接收文件，模块放弃写权。

大文件使用流读取和写入。浏览器上传实际文件后提交交付描述，下载通过文件入口；文件内容不嵌入计算请求或结果 JSON。

操作不能完成时，返回 `failed` 和具体 `diagnostics`，或者抛出包含具体原因的异常。已接收的数据包通过应用的包入口重新读取，接收者只使用包内键。
