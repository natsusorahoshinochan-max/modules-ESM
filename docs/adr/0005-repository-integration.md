# Repository integration: install SDKs, wrap ProteinMPNN

The ESM SDK (esm) and SimpleFold (ml-simplefold) are installed as normal Python
packages via pip directly from their repository directories. They are not declared
as editable path dependencies in the project's pyproject.toml.

ProteinMPNN has no package structure; it is a standalone script. Rather than
forking or modifying the upstream repository, a thin wrapper module is placed in
modules/proteinmpnn/ that imports the ProteinMPNN class from
repositories/ProteinMPNN/protein_mpnn_utils.py and exposes a WorkflowModule-compliant
interface. The upstream code is never modified.

This avoids forking maintenance burden and keeps the repositories/ directory as a
read-only vendor area.

## Ticket 17 installable-backend amendment

The wrapper remains thin and the upstream checkout remains read-only, but the
checkout location is no longer inferred from the Protein Workbench source tree.
Source and installed runtimes both select the locked external checkout explicitly
with `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT`. This amendment supersedes only the
source-relative path in the original decision; the no-fork and read-only vendor
decisions remain in force.
