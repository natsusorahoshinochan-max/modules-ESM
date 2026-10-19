# 本地模型路径

模型目录：`/Volumes/Data/Models/protein-workbench/`，可通过仓库根目录的 `.models` 符号链接访问。

以下路径相对工作区根目录：

| 模型 | 路径 |
|---|---|
| ESM3 | `.models/esm3/`；权重在 `data/weights/` |
| ESMC 300M（Hugging Face 格式） | `.models/esmc-300m/` |
| ESMC 6B | `.models/esmc-6b/` |
| ESMFold2 | `.models/esmfold2/` |
| SimpleFold 100M | `.models/simplefold/simplefold_100M.ckpt` |
| SimpleFold 1.6B（pLDDT 所需 latent 模型） | `.models/simplefold/simplefold_1.6B.ckpt` |
| pLDDT head | `.models/simplefold/plddt.ckpt` |
| ESM2 3B | `.models/esm2/esm2_t36_3B_UR50D.pt` |
| ESM2 contact regression | `.models/esm2/esm2_t36_3B_UR50D-contact-regression.pt` |
| ProteinMPNN | `.models/proteinmpnn/`，包含 vanilla、soluble、ca 三组权重目录 |

## 真实模型验证

本机 ESM 系列、SimpleFold 及其他真实模型检查统一通过以下入口运行，所有 worktree 在同一个机器锁上等待：

```bash
.venv/bin/python -m protein_workbench_public.model_validation -- .venv/bin/python path/to/check.py
```

在命令中完成模型加载、推理及验证。入口保持当前工作目录，原样传递命令和参数；标准输出、标准错误直接显示，正常结束返回检查命令的退出码。锁文件固定为 `/tmp/protein-workbench-model-validation.lock`，运行或等待期间不要删除它。等待锁时尚未启动检查命令，可以在其他终端继续开发。

验证所需的模型服务也须由该命令启动，并留在它的进程组内。检查脚本可启动服务、执行客户端请求后退出；入口会结束残留服务，等待模型进程全部退出后交还资源。服务不得 daemonize、调用 `setsid` 脱离进程组，或使用此入口之外已经驻留的模型服务。

按 Ctrl+C 或向入口发送 SIGINT、SIGTERM、SIGHUP 可取消等待或运行。运行取消、命令失败或正常结束都会清理整个进程组；进程收到 SIGTERM 一秒后仍未退出时发送 SIGKILL，确认进程退出后才释放锁。取消返回 `128 + 信号编号`，命令无法启动返回 126 并报告原因。请保留入口进程至清理结束，避免用 SIGKILL 强制终止入口。该入口使用 POSIX 文件锁与 `ps`，适用于 macOS、Linux；验证机制本身的测试无需加载模型。

预测节点的应用内配置、独立本地与远端默认值及可执行验证命令见 [预测工具插槽](../modules/folding/TOOL.md)。ESMFold2 与 [SimpleFold](../modules/simplefold/TOOL.md) 的本地预测 Adapter 自行持有上述资源锁，其 `modules.folding.verify` 命令直接运行，避免嵌套获取同一把锁。
