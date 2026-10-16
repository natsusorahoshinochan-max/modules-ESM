# Issue tracker: GitHub

本仓库的任务和规格使用 GitHub Issues，仓库为
`natsusorahoshinochan-max/modules-ESM`，通过 `gh` CLI 操作。

## 操作约定

- 技能要求发布任务时，创建 GitHub issue。
- 技能要求读取 ticket 时，读取对应 issue 的正文、标签和评论。
- 创建、评论和更新多行正文时，先写入临时文件，再使用 `--body-file`。
- 使用 GitHub 原生 sub-issues 表达父子任务，使用 issue dependencies 表达阻塞关系。
- 按需查询当前 `gh` 帮助，使用其支持的命令或 GitHub API。
- 标签角色见 `triage-labels.md`。

## 需求与问题的关系

Issue 中区分已确认要求、实现状态和未解决疑点。
产品要求以 `../documentation-governance-decisions.md` 为准；
问题与证据入口为 `../2026-10-15-documentation-governance-issues.md`。
创建 issue 不代表其中的提议已获确认。

## Pull requests as a triage surface

**PRs as a request surface: no.**
