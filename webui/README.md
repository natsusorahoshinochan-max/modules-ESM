# Protein Workbench WebUI

The application has one entry at `/`. This guide describes how to start the
current implementation and verify frontend changes. Product requirements and
implementation gaps are maintained in the [workspace](../docs/workspace.md),
[results](../docs/results.md), and [Prompt editing](../docs/prompt-editing.md)
specifications, under the [current governance decisions](../docs/documentation-governance-decisions.md).

## Install and start on your machine

Use Python 3.12 for the backend and Node.js 22.12 or later with npm for the
frontend toolchain. The commands below use a POSIX shell and run from a source
checkout. On other systems, use the corresponding virtual-environment executable
paths and environment-variable syntax; availability of each native dependency
and local Provider must be checked for that platform.

From the repository root, create the backend environment and install the package:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
export PROTEIN_WORKBENCH_DATA_ROOT="$HOME/protein-workbench-data"
.venv/bin/protein-workbench-server --host 127.0.0.1 --port 8000
```

Choose one persistent absolute data directory for this installation. Personal
Projects, Drafts, results and runtime state are stored there; do not use a
throwaway temporary directory for work you intend to retain.

In a second terminal, start the frontend:

```bash
cd webui
npm ci
npm run dev -- --host 127.0.0.1
```

Vite forwards `/api` HTTP and WebSocket traffic to `http://127.0.0.1:8000`.
If the backend uses another port, configure the target when starting Vite:

```bash
PROTEIN_WORKBENCH_BACKEND_URL=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1
```

The backend must also be started with the matching `--port`. No fixed SSH
server, account, port forwarding or machine-specific filesystem path is required.

## Provider configuration

Install Provider Python dependencies when you need model execution:

```bash
.venv/bin/python -m pip install -e '.[providers]'
```

This installs Python dependencies, not model weights or all external executables.
The current implementation reads configuration from environment variables before
backend startup. Follow [Provider configuration](../docs/provider-configuration.md#当前配置入口)
for each selected route's credentials, absolute paths on the backend machine,
native tools and required platform/device. Setting a directory variable does not
install the Provider. Missing model configuration prevents the corresponding
operations from running, not browsing already published example results.
Credentials must remain outside Git.

An application settings interface is a confirmed requirement: modules declare
their settings, and the carrier displays, saves and supplies them. It is not yet
provided by the environment-variable path above. See [Provider configuration](../docs/provider-configuration.md)
for the current setup and its gap from that requirement. Model downloads and
automatic environment installation are outside this decision; per-calculation
parameters remain in Node/Binding controls.

## Deploy built frontend assets

Build the frontend with `npm ci` and `npm run build` from `webui/` on a suitable
build machine. Deploy the resulting `webui/dist/` alongside a backend installation;
the Python wheel does not contain these frontend assets. Node.js is not needed
merely to serve the built files.

Configure a loopback HTTP server to serve `dist/` and reverse-proxy `/api` to the
loopback backend, preserving the path and supporting WebSocket upgrades for Run
events. Both must appear under the same browser origin. Vite's
`PROTEIN_WORKBENCH_BACKEND_URL` setting configures the development proxy only;
it does not configure the server that hosts `dist/`. Keep the application within
its trusted single-user, loopback deployment model.

The repository's remote-only build and test policy applies to contributor
verification, not to where users may install or run the application.

## Application behavior

Open `http://127.0.0.1:5173`. The current app discovers the protected 3GB1 teaching
example, its Workflow Draft and bundled completed Run through the public protocol.
No Provider is needed to inspect these results; new Runs use configured real
Providers.
When no teaching Project is installed, the app opens an existing personal Project
or offers creation and opening. An empty installed package inventory still exposes
the canvas and manual Project persistence. The production inventory is
`modules.json` under the application data root, with a `packages` array of
`package_id`, `package_module`, boolean `enabled`, and nullable `source_root` entries. A missing inventory uses the
bundled enabled packages; `{"packages": []}` selects an empty carrier. This
composition contract is not yet an in-application package manager. The [example resource guide](../examples/v2/README.md#protected-webui-result-resource)
describes what ships in the backend package.

The canvas exposes operations, Node/Binding parameters, connections, nested
groups, independent group copies and undo/redo. Default stage cards map to real
nodes and parameters; groups preserve the actual workflow dependencies.
[Workspace behavior](../docs/workspace.md) defines these interactions and the
confirmed manual-save, project-copy and tutorial rules.

Prompt Studio combines a residue matrix and structure view. G/R moving and
rotation update temporary coordinates locally; Enter or left-click confirms the
final backend preview, and Escape or right-click restores the starting state.
The viewer uses 3Dmol.js. Confirmation of an edit and persistent project saving
have separate requirements; see [Prompt editing](../docs/prompt-editing.md).

Results browse published intermediate outputs, exact Scores, parents and available
alignment results. Focus, export selection and same-Run comparison are independent.
The current ZIP exporter writes FASTA, Scores, metadata and structure files in the selected PDB or mmCIF format. Same-format export preserves source text; conversion leaves stored results unchanged. [Results](../docs/results.md) defines the required history,
reuse, structure formats, viewers and parameter export behavior.

Edits now remain in memory until an explicit save. Navigation offers save,
discard or cancel for unsaved work; Run offers save-and-run. A teaching example
becomes a personal Project only on first explicit save. Running Projects reject
modification while remaining readable. Result-to-workflow actions have been
removed. These changes passed the frozen snapshot’s non-Provider regressions;
see the current [verification scope](../docs/testing.md).

The app still mainly opens the latest Run and lacks complete module settings/viewer integration. The new structure format
selection and conversion paths await full verification. Full
historical/cross-project input adoption and source-independent availability
remain to be verified. Failed batches can publish completed results for reading
without making the Node successful or sending those outputs downstream; this
passed controlled failure regressions. The permitted real Provider success
checks passed; they do not constitute live failure-injection coverage. All six real browser journeys and the FASTA report check also passed.
This completes the authorized test-governance scope, not the full 19-tier
Campaign or the missing product interfaces listed below.
Node-level continuation remains distinct from the
required continuation of unfinished requests within a batch. See
[execution](../docs/execution.md) and the [governance issue list](../docs/2026-10-15-documentation-governance-issues.md).

## Verification

For read-only review and explanatory text/link changes, inspect content and
references without running executable verification. For behavior changes, use
the complete [backend execution policy and gates](../docs/backend-verification.md#execution-policy)
and these frontend entry points. This document records commands, not a claim
that the current working tree has passed them.

Run all verification on the local machine, using its Python 3.12 `.venv`,
installed frontend dependencies and an explicitly specified private Execution
Profile. Remote-service Providers continue to call their configured official
APIs. Local ESM-3, SimpleFold and ESMFold2 execution is excluded; retain
model-free browser contracts and report real journeys requiring those routes as
excluded, never passed. Other local models and Biohub routes remain required.
The [backend scope](../docs/backend-verification.md#current-model-verification-scope)
also applies to real browser journeys. From the verification snapshot's `webui/` directory:

```bash
npm run typecheck
npm run typecheck:tests
npm run lint
npm run test:logic
npm run test:components
npm run test:e2e
npm run test:empty-carrier
npm run build
```

Collect each command's exit status independently; one failure must not suppress
other independent checks. `typecheck:tests` includes every test, controlled host,
and Playwright configuration, including `real-tests/`.

| Entry | Responsibility | Resources |
| --- | --- | --- |
| `test:logic` | State owners and data transformations in `tests/logic` | Node only; no browser, Vite or backend |
| `test:components` | Component interactions in `tests/components` | Controlled hosts in `tests/support`, Vite on 5181; no backend |
| `test:e2e` | Application and protocol journeys in `tests/journeys` | Production application, isolated backend on 8180 and Vite on 5179 |
| `test:empty-carrier` | Empty production startup, project creation, manual save and reopen | Empty persisted module inventory; backend on 8182 and Vite on 5182 |
| Real configuration | Actual Provider browser journeys in `real-tests` | Supervised built service and configured Providers |

Support files provide mounting, navigation and interaction helpers; no collected
spec is a shared library. Controlled hosts prove component behavior, not project
persistence or complete application journeys. Existing published teaching results
prove offline reading only, not a fresh Provider invocation.

The edit contracts assert that edits remain in memory and teaching edits do not
create personal projects. Explicit manual-save, exit choices and save-before-run
passed frozen-snapshot application regressions, including save failures
and teaching first-save/reopen. Browser close uses the native unsaved-change
prompt; the three-way choice applies to in-application navigation. Tests must exercise the real interface, not
synthesize it in a host or substitute an API write for a user save. Random
inserted residues must remain editable and deletable; built-in result
save-as-workflow actions must be absent. Correct expectations must not be
skipped or weakened.

User module installation/enable/disable/uninstall, missing
module recovery, historical/cross-project adoption surviving source deletion,
batch continuation, external UI/multiple viewers and application settings still
need complete application interfaces and journeys. Existing component/protocol
coverage does not certify these user chains. Current product differences remain
in the [governance issue list](../docs/2026-10-15-documentation-governance-issues.md).

Real Provider journeys have a separate
`playwright.real.config.ts`; they require an explicitly supervised built WebUI
service and the prepared FASTA Project. See the
[real FASTA journey procedure](../docs/backend-verification.md#real-fasta-webui-journey)
for preparation, report collection and its required original full Run identity.
Set `PROTEIN_WORKBENCH_REAL_UI_URL` and `PROTEIN_WORKBENCH_REAL_FASTA_PROJECT_ID`
for the prepared service and Project, then run
`npx playwright test --config playwright.real.config.ts` on the verification host.

模块专用 React 编辑器的声明、共享依赖和资产构建见[模块 UI 契约](../docs/module-ui.md)。Selection 已迁移到该入口；外部编辑器旅程通过 `npm run test:module-ui` 在独立公共应用上验证。后端源码资产读取检查前执行 `npm run build:module-ui`，wheel 构建自动生成包内资源。

所有 Playwright 入口使用 `tsconfig.test.json` 将 React 运行时解析到 WebUI 工具链依赖，使位于 `modules/*/ui` 的源码也使用同一安装包；应用类型检查仍使用 `tsconfig.app.json`。模块资产在浏览器中按声明的绝对 URL 导入，不接受开发服务器额外添加的协议查询参数。
