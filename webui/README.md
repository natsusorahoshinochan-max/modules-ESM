# Protein Workbench WebUI

The application has one entry at `/`. This guide describes how to start the
current implementation. Product requirements and
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
Open **模块管理 → 运行设置** to save module-declared credentials, service addresses,
and absolute paths on the backend machine. Settings persist across application
restarts and are used for subsequent Runs. Saving settings requires an idle
runtime; incomplete settings can be saved, but the corresponding operation
reports missing configuration before entering its Provider. See
[Provider configuration](../docs/provider-configuration.md#当前配置入口) for each route.
Credentials remain outside Git and Workflow parameters. Model downloads and
automatic environment installation are not provided.

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
inventory is managed by the **模块管理** dialog, available in both the empty carrier and open projects. Users select a wheel file, toggle installed packages, uninstall packages, or restore bundled packages. Changes require an idle runtime and preserve Project Inputs, Workspaces and Runs. Unsaved edits are handled before activation; the current project reloads against the replacement Catalog. The [example resource guide](../examples/v2/README.md#protected-webui-result-resource)
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
removed.

Complete module settings/viewer integration, historical/cross-project input
adoption and source-independent availability remain incomplete. Failed batches
can publish completed results without making the Node successful or sending
those outputs downstream. Node-level continuation remains distinct from the
required continuation of unfinished requests within a batch. See
[execution](../docs/execution.md) and the [governance issue list](../docs/2026-10-15-documentation-governance-issues.md).

The previous test framework and gates are retired. See [AGENTS.md](../AGENTS.md#测试)
for the current decision.

模块专用 React 编辑器的声明、共享依赖和资产构建见[模块 UI 契约](../docs/module-ui.md)。Selection 已迁移到该入口；`npm run build:module-ui` 构建源码资产，wheel 构建自动生成包内资源。

### External module package

A wheel declares one `protein_workbench.modules` entry point whose name is its
package ID and whose value is `your_package.package:MODULE_PACKAGE`. The exported
value is a `ModulePackageRegistration`; official and external packages use the
same registration, Catalog and module UI resource loader. Include declared UI
resources in the wheel. The application installs the distribution under its data
root, using the current Python environment and `pip --no-index --no-deps`; package
dependencies must already be provided by that environment. Installation does not
download scientific models or execute them. Uninstall before replacing a package;
reinstallation imports the new distribution files.

模块资产在浏览器中按声明的绝对 URL 导入，不接受开发服务器额外添加的协议查询参数。
