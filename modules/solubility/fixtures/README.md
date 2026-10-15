# Solubility 固定测试数据

这些 FASTA 与 CSV 是验证输入及预期值，不是当前 Provider 已通过验收的证明，也不随生产包分发。

SoluProt 输入及 full 预期值来自项目维护移植包 `soluprot 1.1.0` 所带 `data/test.fa` / `data/test.csv` 的首例。no-TM 预期值使用同一输入、由该包独立的无 TMHMM 特征模型产生，单独保存。该包不是上游官方 SoluProt 1.1.0 发布版，不承诺与官方上游版本逐字节或逐行为相同。实现与输入规则见[移植包说明](../../../repositories/soluprot-next/README.md)。

Protein-Sol 输入和预期行保留其 October 2017 官方下载归档中的两个结果。来源为 `https://protein-sol.manchester.ac.uk/cgi-bin/utilities/download_sequence_code.php`，固定归档身份为 `sha256:4df32c61fca53adcb2394a528babd1ad85cb5c551bf7bd1c56d134097fb2b1b8`。这里记录固定数据来源，不声称重新获取或复验了当前线上版本。

真实 Provider 验证遵守[后端验证规范](../../../docs/backend-verification.md)，模拟输入或本目录的预期值不能代替所需真实调用。
