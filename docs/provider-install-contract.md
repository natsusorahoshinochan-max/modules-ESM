# Provider installation contract

Status: current operational contract.

Provider repositories, packages, models, and checkpoints remain external to the
Protein Workbench wheel. Environment Configuration supplies their operator-owned
absolute locations and credential handles. Module Packages own the stable
scientific Method and Binding IDs, Provider translation, and the operational
resource roles used by each route.

Provider source bytes, checkpoint bytes, Git metadata, PEP 610 metadata,
installation form, and local file hashes are not scientific identity. Runtime
Readiness does not prove them, and Run Evidence does not claim that it did.

## Provider installation forms

| Provider | Supported installation form |
| --- | --- |
| ESM / Biohub | Installed Python package from the `providers` optional dependency |
| SimpleFold | Installed Python package from the `providers` optional dependency |
| ProteinMPNN | Operator-owned source root selected by `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT` |
| SoluProt-next | Wheel built from [`repositories/soluprot-next`](../repositories/soluprot-next) on the target machine |
| Protein-Sol | Operator-owned source root selected by `PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT` |

Equivalent wheels, containers, copied source trees, and editable installations
are accepted when the configured route imports, loads, and executes correctly.
Readiness does not require `direct_url.json`, a Git checkout, a particular HEAD,
or a clean working tree.

## Remote Provider routes

Remote Provider weights are service-managed. Current route labels are:

| Route | Model label | Contract owner |
| --- | --- | --- |
| Biohub ESMC | `esmc-600m-2024-12` | `esm3` Method/Binding |
| Biohub ESM-3 medium | `esm3-medium-2024-08` | `esm3` Method/Binding |
| Biohub ESM-3 open | `esm3-open-2024-03` | `esm3` Method/Binding |
| Biohub ESMFold2 | `esmfold2-fast-2026-05` | `folding` Method/Binding |

These labels select the intended Provider route. They are not local asset
digests. The credential handle makes the selected route operable; the Adapter
owns the fixed Biohub endpoint and does not choose a fallback endpoint.

## Local Provider configuration

Environment Configuration uses the following external fields:

| Binding family | Environment Configuration | Operational content |
| --- | --- | --- |
| Biohub remote routes | `PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE` | Credential handle read by the composition root |
| Local ESM-3 | `PROTEIN_WORKBENCH_ESM3_MODEL_ROOT` | Complete local ESM-3 snapshot used by the installed SDK |
| Local ESMFold2 | `PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT` | Folding model files |
| Local ESMFold2 | `PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT` | ESMC language-model files |
| SimpleFold | `PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT` | `simplefold_100M.ckpt`, `simplefold_1.6B.ckpt`, `plddt.ckpt`, and `ccd.pkl` as required by the selected route |
| SimpleFold ESM2 source | `PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT` | Importable Facebook ESM source layout used for isolated staging |
| SimpleFold ESM2 models | `PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT` | `esm2_t36_3B_UR50D.pt` and, for folding, its contact-regression object |
| ProteinMPNN | `PROTEIN_WORKBENCH_PROTEINMPNN_ROOT` | Importable `protein_mpnn_utils.py` and `vanilla_model_weights/v_48_020.pt` |
| SoluProt-next | `PROTEIN_WORKBENCH_SOLUPROT_ROOT` | Installed or built SoluProt runtime and required external tools |
| Protein-Sol | `PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT` | Importable source-bound Protein-Sol runtime |
| DSSP | `PROTEIN_WORKBENCH_MKDSSP_BINARY` | Absolute executable path for the supported `mkdssp` route |

The composition root validates these external fields and types once. Adapter
model labels, fixed filenames, device policy, precision, and performance policy
remain Adapter-owned facts and do not round-trip through the Environment
Configuration mapping.

## Readiness contract

On the first Cache miss or bypass for one Adapter Binding in a Run, Readiness
uses the external fields already admitted by the composition root and checks
only what is needed to enter the actual Provider route:

- required files are readable;
- the configured package or source can be imported;
- the selected model, checkpoint, binary, or service route can be minimally
  loaded or reached as required by that Provider;
- route-specific operational prerequisites are satisfied.

Readiness does not:

- hash source trees, models, checkpoints, wheels, or installed package files;
- require PEP 610, Git revision, checkout-root, or dirty-tree evidence;
- build a replacement manifest, stat fingerprint, immutable-installation object,
  or content-proof cache;
- search another workspace, repository-relative checkout, downloader cache, or
  network location as a fallback;
- turn startup Availability into an execution gate.

Nodes using the same Binding in one Run share the Readiness conclusion.
Availability remains a separate startup diagnostic and cannot suppress a fresh
Readiness check.

## SimpleFold staging

The folding package's shared module owns the route-specific resource roles and
isolated staging used by SimpleFold folding and existing-structure confidence.
It stages only the configured resources needed by the selected route. Folding
uses both ESM2 representation and contact-regression objects; confidence uses
the representation object only. Unrelated files are ignored.

Staging preserves the source layout required for namespace isolation and does
not download, hash, inspect Git state, or choose an alternate resource. The two
Bindings retain distinct Readiness conclusions and scientific Methods.

## Device policy

Local Torch Bindings use CUDA on Linux and Windows and CPU on macOS. The selected
device is passed through model loading, tensors, and RNG paths; there is no
silent CPU fallback on a CUDA route.

CPU/GPU execution may produce tiny numerical differences. The project accepts
those differences within the same scientific contract. Device does not split
Method, Result Identity, or Cache identity, and no cross-device numerical
equivalence or tolerance validation is added. An already-known actual device may
be recorded as non-gating provenance.

## Acceptance

Real-Provider acceptance, not installation metadata, proves the supported
routes. Acceptance validates scientific input translation, output shape and
units, residue scope and mapping, lineage, Method evidence, and route-specific
scientific thresholds. The canonical campaign retains all 19 tiers, including:

- `fresh-local-1pga`;
- `fresh-local-2emo`;
- `fresh-local-canonical-3gb1`;
- `fresh-local-5g53`.

Mocks, Availability-only checks, hash manifests, Git metadata, and Cache replay
do not replace these real-Provider routes.
