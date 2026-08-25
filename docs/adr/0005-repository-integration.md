---
status: accepted
---

# Provider source integration uses locked packages and configured roots

The ESM SDK and SimpleFold are normal installed Python packages resolved from the
exact Git revisions locked by `uv.lock` and the `providers` optional dependency.
Runtime behavior does not import either Provider from a repository-relative
checkout or infer their source from `repositories/`.

ProteinMPNN remains an external pinned checkout because its upstream source is not
an installable package. `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT` selects that checkout
explicitly. The ProteinMPNN Adapter loads the upstream `protein_mpnn_utils.py` and
the Method-fixed checkpoint from the admitted root; the upstream code is never
modified.

SoluProt-next is project-owned Provider source under
`repositories/soluprot-next/`. It is built as its own wheel from source on the
target machine and is not bundled into the Protein Workbench wheel.

Module Packages own Methods, Execution Bindings, canonical scientific operations,
and concrete Provider Adapters. Source revisions, asset identities, installation
commands, and Environment Configuration are maintained in
`docs/provider-install-contract.md` rather than duplicated in this decision.
