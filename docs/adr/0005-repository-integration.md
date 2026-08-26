---
status: accepted
---

# Provider source integration uses locked packages and configured roots

The ESM SDK and SimpleFold are normal installed Python packages resolved by the
current environment and the `providers` optional dependency.
Runtime behavior does not import either Provider from a repository-relative
checkout or infer their source from `repositories/`.

ProteinMPNN remains an external configured source root because its upstream
source is not an installable package. `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT`
selects that root explicitly. The Adapter loads `protein_mpnn_utils.py` and the
configured model checkpoint from it at Provider entry; Readiness checks the
declared root and required paths rather than loading the model or proving Git
revision or installation identity.

SoluProt-next is project-owned Provider source under
`repositories/soluprot-next/`. It is built as its own wheel from source on the
target machine and is not bundled into the Protein Workbench wheel.

Module Packages own Methods, Execution Bindings, canonical scientific operations,
and concrete Provider Adapters. Installation commands and Environment
Configuration are maintained in
`docs/provider-install-contract.md` rather than duplicated in this decision.
