---
status: accepted
---

# Repository integration: install SDKs, wrap ProteinMPNN

The ESM SDK (esm) and SimpleFold (ml-simplefold) are installed as normal Python
packages via pip directly from their repository directories. They are not declared
as editable path dependencies in the project's pyproject.toml.

ProteinMPNN has no package structure; it is a standalone script. A thin wrapper
in `modules/proteinmpnn/` imports the ProteinMPNN class from
repositories/ProteinMPNN/protein_mpnn_utils.py and exposes a WorkflowModule-compliant
interface. The upstream code is never modified.

Source and installed runtimes select the locked checkout explicitly with
`PROTEIN_WORKBENCH_PROTEINMPNN_ROOT`; runtime behavior does not infer the checkout
from the Protein Workbench source tree. This keeps the wrapper thin and the pinned
upstream repository read-only.
