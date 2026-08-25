"""Translate installed CLI process variables into Binding configuration."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import shutil
from typing import Any

from core.local_torch_device import expected_local_torch_device
from core.provider_support import read_private_credential_file
from modules.esm3.local_adapter import (
    LOCAL_ESM3_PERFORMANCE_SETTINGS,
    LOCAL_ESM3_SNAPSHOT_REVISION,
)
from modules.folding.esmfold2_contract import (
    LOCAL_ESMC_REVISION,
    LOCAL_ESMFOLD2_REVISION,
)
from protein_workbench_public.application_environment import (
    application_storage_roots,
)


ProviderEnvironmentConfiguration = dict[
    tuple[str, str],
    dict[str, dict[str, Any]],
]


class ProviderEnvironmentError(RuntimeError):
    """A selected Provider is missing one required process executable."""


def _configured_path(
    environment: Mapping[str, str],
    variable: str,
) -> Path | None:
    configured = environment.get(variable)
    if configured is None:
        return None
    path = Path(configured).expanduser()
    if not path.is_absolute():
        raise ProviderEnvironmentError(f"{variable} must be absolute")
    return path


def _executable(
    environment: Mapping[str, str],
    name: str,
) -> Path:
    resolved = shutil.which(name, path=environment.get("PATH"))
    if resolved is None:
        raise ProviderEnvironmentError(
            f"configured Provider requires executable {name!r} on PATH"
        )
    return Path(resolved)


def provider_environment_configuration(
    environment: Mapping[str, str] | None = None,
) -> ProviderEnvironmentConfiguration:
    """Load current Provider roots and credentials from process variables."""
    values = os.environ if environment is None else environment
    configuration: ProviderEnvironmentConfiguration = {}
    local_torch_device = expected_local_torch_device()

    token_file = _configured_path(
        values,
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",
    )
    if token_file is not None:
        biohub_values = {
            "endpoint_id": "biohub",
            "credential_handle": read_private_credential_file(token_file),
        }
        biohub_bindings = (
            ("esm3.represent_sequence.biohub_esmc_600m_2024_12", "5.0.0"),
            ("folding.fold.esmfold2_remote", "9.0.0"),
            *(
                (f"esm3.{operation}.biohub_{scale}", "8.0.0")
                for operation in (
                    "generate_sequence",
                    "generate_structure",
                    "generate_paired",
                )
                for scale in ("medium", "open")
            ),
        )
        for identity in biohub_bindings:
            configuration[identity] = {"values": dict(biohub_values)}

    esm3_model_root = _configured_path(
        values,
        "PROTEIN_WORKBENCH_ESM3_MODEL_ROOT",
    )
    if esm3_model_root is not None:
        storage = application_storage_roots(values)
        runtime_directory = storage.data / "provider-runtime/esm3"
        runtime_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        local_esm3_values = {
            "model_snapshot_revision": LOCAL_ESM3_SNAPSHOT_REVISION,
            "model_snapshot_path": esm3_model_root,
            "runtime_directory": runtime_directory,
            "device": local_torch_device,
            "performance_settings": dict(LOCAL_ESM3_PERFORMANCE_SETTINGS),
        }
        for operation in (
            "generate_sequence",
            "generate_structure",
            "generate_paired",
        ):
            configuration[(f"esm3.{operation}.local_open", "9.0.0")] = {
                "values": dict(local_esm3_values),
            }

    esmfold2_root = _configured_path(
        values,
        "PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT",
    )
    esmfold2_esmc_root = _configured_path(
        values,
        "PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT",
    )
    if (esmfold2_root is None) != (esmfold2_esmc_root is None):
        raise ProviderEnvironmentError(
            "local ESMFold2 requires both configured model roots"
        )
    if esmfold2_root is not None and esmfold2_esmc_root is not None:
        configuration[("folding.fold.esmfold2_local", "11.0.0")] = {
            "values": {
                "model_snapshot_revision": LOCAL_ESMFOLD2_REVISION,
                "language_model_snapshot_revision": LOCAL_ESMC_REVISION,
                "model_snapshot_path": esmfold2_root,
                "language_model_snapshot_path": esmfold2_esmc_root,
                "device": local_torch_device,
            },
        }

    simplefold_roots = {
        "model_root": _configured_path(
            values,
            "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",
        ),
        "esm2_source_root": _configured_path(
            values,
            "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT",
        ),
        "esm2_model_root": _configured_path(
            values,
            "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT",
        ),
    }
    configured_simplefold_roots = {
        name for name, path in simplefold_roots.items() if path is not None
    }
    if configured_simplefold_roots and len(configured_simplefold_roots) != 3:
        raise ProviderEnvironmentError(
            "SimpleFold requires all three configured roots"
        )
    if len(configured_simplefold_roots) == 3:
        for identity in (
            ("folding.fold.simplefold_local", "11.0.0"),
            (
                "folding.simplefold_confidence.simplefold_local",
                "7.0.0",
            ),
        ):
            configuration[identity] = {
                "values": {
                    **simplefold_roots,
                    "device": local_torch_device,
                },
            }

    proteinmpnn_root = _configured_path(
        values,
        "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
    )
    if proteinmpnn_root is not None:
        for identity in (
            ("proteinmpnn.design.local", "12.0.0"),
            ("proteinmpnn.score.local", "9.0.0"),
        ):
            configuration[identity] = {
                "values": {
                    "provider_root": proteinmpnn_root,
                    "device": local_torch_device,
                },
            }

    mkdssp_binary = _configured_path(
        values,
        "PROTEIN_WORKBENCH_MKDSSP_BINARY",
    )
    if mkdssp_binary is not None:
        configuration[
            ("structure_annotation.dssp_compute.mkdssp_local", "7.0.0")
        ] = {"values": {"dssp_binary": mkdssp_binary}}

    soluprot_root = _configured_path(
        values,
        "PROTEIN_WORKBENCH_SOLUPROT_ROOT",
    )
    if soluprot_root is not None:
        runtime_root = soluprot_root / "var/environments/soluprot"
        common_soluprot = {
            "python_executable": runtime_root / "bin/python",
            "site_packages_root": (
                runtime_root / "lib/python3.12/site-packages"
            ),
            "usearch_executable": (
                soluprot_root / "var/tools/soluprot/usearch"
            ),
        }
        configuration[("solubility.soluprot_no_tm.local", "5.0.0")] = {
            "values": dict(common_soluprot),
        }
        configuration[("solubility.soluprot_full.local", "5.0.0")] = {
            "values": {
                **common_soluprot,
                "perl_executable": _executable(values, "perl"),
            },
        }

    protein_sol_root = _configured_path(
        values,
        "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT",
    )
    if protein_sol_root is not None:
        configuration[("solubility.protein_sol.local", "5.0.0")] = {
            "values": {
                "source_root": protein_sol_root,
                "bash_executable": _executable(values, "bash"),
                "perl_executable": _executable(values, "perl"),
            },
        }

    return configuration
