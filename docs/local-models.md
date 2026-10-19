# 本地模型路径

模型目录：`/Volumes/Data/Models/protein-workbench/`，可通过仓库根目录的 `.models` 符号链接访问。

以下路径相对工作区根目录：

| 模型 | 路径 |
|---|---|
| ESM3 | `.models/esm3/`；权重在 `data/weights/` |
| ESMC 300M（新版 Hugging Face 格式） | `.models/esmc-300m/` |
| ESMC 6B | `.models/esmc-6b/` |
| ESMFold2 | `.models/esmfold2/` |
| SimpleFold 100M | `.models/simplefold/simplefold_100M.ckpt` |
| SimpleFold 1.6B（pLDDT 所需 latent 模型） | `.models/simplefold/simplefold_1.6B.ckpt` |
| pLDDT head | `.models/simplefold/plddt.ckpt` |
| ESM2 3B | `.models/esm2/esm2_t36_3B_UR50D.pt` |
| ESM2 contact regression | `.models/esm2/esm2_t36_3B_UR50D-contact-regression.pt` |
| ProteinMPNN | `.models/proteinmpnn/`，包含 vanilla、soluble、ca 三组权重目录 |
