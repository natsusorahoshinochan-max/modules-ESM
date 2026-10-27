# Getting started and tool configuration

[中文](getting-started.md) · **English** · [Back to README](../README.en.md)

Start the application using the README instructions. On first launch, the app installs the official modules and opens a structure-prediction tutorial with a sequence input. Use it for your first folding run. The README screenshots show a separately assembled, multistage workflow.

## Run your first prediction

### 1. Install computation dependencies

From the repository root, run:

```bash
uv sync --locked --extra providers
```

Restart the backend afterward. This dependency group includes model SDKs and computation libraries such as PyTorch. Prepare model weights separately for local inference.

### 2. Configure Biohub

1. Click the project name in the upper-left corner and open **Modules**.
2. Expand **Structure prediction**. Enter your **Biohub credential** under **Deployment settings**, then click **Save settings**. The default service URL is `https://biohub.ai`.
3. Return to the canvas and select **ESMFold2 · Biohub** in the **Predict structure** node's tool dropdown.

Configure credentials for other Biohub tools in their respective modules:

| Tool | Settings module | Purpose |
|---|---|---|
| ESMFold2 · Biohub | Structure prediction | Predict a 3D structure from a complete sequence |
| ESM3 · Biohub | ESM3 tools | Complete or generate a protein from supplied track values and gaps |
| ESMC · Biohub | Sequence representations | Compute sequence representations |

Module settings configure service connections and model deployment. Set computation parameters, such as sample count and sampling steps, inside the node.

### 3. Save, run, and inspect

Click **Save** in the top bar to save the tutorial as your own project, then click **Run**. Open **Results**, choose the run and node, and inspect the resulting 3D structure and output files.

## Use local tools

Select a local implementation in the node's tool dropdown. In the corresponding module's deployment settings, enter absolute paths to your existing resources.

| Tool | Required configuration |
|---|---|
| ESMFold2 | Python path, ESMFold2 model directory, ESMC 6B language model directory, and device |
| ESM3 | Python path, ESM3 model directory, and device |
| ESMC | ESMC model directory and device; uses the backend's Python environment |
| ProteinMPNN | `source` code directory, `weights` root directory, `python` executable, and `device` |

For example, the Python path can point to this project's `.venv/bin/python` using its absolute path. Set model directories to your own weight locations. Choose a supported device (`cpu`, `cuda`, or `mps`) based on model size and available hardware.

See the resource requirements for [ESMFold2](../modules/folding/TOOL.md), [ESM3](../modules/esm3/TOOL.md), [ESMC](../modules/esmc/TOOL.md), [ProteinMPNN](../modules/proteinmpnn/TOOL.md), and [SimpleFold](../modules/simplefold/TOOL.md).

## Build your own workflow

- **Projects:** click the project name and use **New / Open** to manage projects. Project files and computation results live in the data directory configured at startup. Start with the same directory to continue your work.
- **Canvas:** choose tasks through **Add node**, drag port dots to connect them, and select tools or expand parameters inside each node.
- **Studio:** open Protein Studio from an **Edit protein** node. Edit the five tracks independently, with linked selection between tracks and the 3D view. Click **Done and return to canvas**, then save the project. See [Protein Studio](../modules/sequence_edit/FORMAT.md) for editing details.
- **Results:** select a run and node in the results panel. Inspect outputs, download a ZIP, or use the results in a node or another project.

## Features and data formats

| Feature | Reference |
|---|---|
| Sequence import | [FASTA, sequence batches, and gaps](../modules/sequence_io/FORMAT.md) |
| 3D structure import | [PDB, mmCIF, chains, and residue selection](../modules/structure_io/FORMAT.md) |
| Protein editing | [Protein Studio and its five tracks](../modules/sequence_edit/FORMAT.md) |
| Generation and backbone design | [ESM3 and ProteinMPNN inputs, outputs, and sequence extraction](../modules/generation/FORMAT.md) |
| Structure prediction | [Predictions and confidence](../modules/folding/FORMAT.md) |
| Structure comparison | [Superposition, TM-score, and RMSD](../modules/structure_comparison/FORMAT.md) |
| Evaluation | [Structure confidence](../modules/structure_confidence/FORMAT.md), [solubility](../modules/solubility/FORMAT.md), and [sequence–backbone compatibility](../modules/sequence_backbone_evaluation/FORMAT.md) |
| Representations | [ESMC output](../modules/esmc/FORMAT.md) |
| Filtering and organization | [Metric analysis](../modules/metric_analysis/FORMAT.md), [candidate collections](../modules/collection/FORMAT.md), and [filtering](../modules/filtering/FORMAT.md) |
| Format conversion | [3D structure conversion](../modules/structure_conversion/FORMAT.md) |
