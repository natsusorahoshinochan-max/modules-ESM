"""Public process-environment loading for the installed backend CLI."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from protein_workbench_public.bootstrap import create_application
from protein_workbench_public.provider_environment import (
    ProviderEnvironmentError,
    provider_environment_configuration,
)


def test_process_environment_configures_both_solubility_providers(
    tmp_path: Path,
) -> None:
    soluprot_root = tmp_path / "soluprot"
    protein_sol_root = tmp_path / "protein-sol"
    configuration = provider_environment_configuration(
        {
            "PATH": os.environ["PATH"],
            "PROTEIN_WORKBENCH_SOLUPROT_ROOT": str(soluprot_root),
            "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT": str(protein_sol_root),
        }
    )

    runtime_root = soluprot_root / "var/environments/soluprot"
    common_soluprot = {
        "python_executable": runtime_root / "bin/python",
        "site_packages_root": (
            runtime_root / "lib/python3.12/site-packages"
        ),
        "usearch_executable": soluprot_root / "var/tools/soluprot/usearch",
    }
    assert configuration[
        ("solubility.soluprot_no_tm.local", "5.0.0")
    ] == {"values": common_soluprot}
    assert configuration[
        ("solubility.soluprot_full.local", "5.0.0")
    ] == {
        "values": {
            **common_soluprot,
            "perl_executable": Path(
                str(shutil.which("perl", path=os.environ["PATH"]))
            ),
        }
    }
    assert configuration[
        ("solubility.protein_sol.local", "5.0.0")
    ]["values"]["source_root"] == protein_sol_root
    assert set(
        configuration[("solubility.protein_sol.local", "5.0.0")][
            "values"
        ]
    ) == {"source_root", "bash_executable", "perl_executable"}
    assert all(
        "wheel_path" not in entry["values"]
        for entry in configuration.values()
    )


def test_process_environment_configures_every_selected_real_provider(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "biohub-token"
    token_file.write_text("test-token\n", encoding="utf-8")
    token_file.chmod(0o600)
    run_root = tmp_path / "runs"
    environment = {
        "PATH": os.environ["PATH"],
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE": str(token_file),
        "HF_HUB_CACHE": str(tmp_path / "huggingface"),
        "PROTEIN_WORKBENCH_RUN_ROOT": str(run_root),
        "PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT": str(tmp_path / "esmfold2"),
        "PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT": str(tmp_path / "esmc"),
        "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT": str(tmp_path / "simplefold"),
        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_ROOT": str(tmp_path / "esm2-source"),
        "PROTEIN_WORKBENCH_SIMPLEFOLD_ESM2_MODEL_ROOT": str(
            tmp_path / "esm2-model"
        ),
        "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT": str(tmp_path / "proteinmpnn"),
        "PROTEIN_WORKBENCH_MKDSSP_BINARY": str(tmp_path / "bin/mkdssp"),
    }

    configuration = provider_environment_configuration(environment)

    biohub_bindings = {
        ("esm3.represent_sequence.biohub_esmc_600m_2024_12", "5.0.0"),
        ("folding.fold.esmfold2_remote", "9.0.0"),
        *{
            (f"esm3.{operation}.biohub_{scale}", "8.0.0")
            for operation in (
                "generate_sequence",
                "generate_structure",
                "generate_paired",
            )
            for scale in ("medium", "open")
        },
    }
    assert all(
        configuration[identity]
        == {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": "test-token",
            }
        }
        for identity in biohub_bindings
    )

    local_esm3 = configuration[
        ("esm3.generate_sequence.local_open", "8.0.0")
    ]["values"]
    assert local_esm3 == {
        "model_snapshot_revision": (
            "47f0545b2b6daf26a93439a3cd610f4f7f3d5478"
        ),
        "model_snapshot_path": (
            tmp_path
            / "huggingface/models--biohub--esm3-sm-open-v1/snapshots"
            / "47f0545b2b6daf26a93439a3cd610f4f7f3d5478"
        ),
        "runtime_directory": run_root / "provider-runtime/esm3",
        "device": "cpu",
        "performance_settings": {},
    }
    assert local_esm3["runtime_directory"].is_dir()
    assert configuration[("folding.fold.esmfold2_local", "10.0.0")][
        "values"
    ]["model_snapshot_path"] == tmp_path / "esmfold2"
    assert configuration[("folding.fold.simplefold_local", "10.0.0")][
        "values"
    ]["esm2_source_root"] == tmp_path / "esm2-source"
    assert configuration[("proteinmpnn.design.local", "11.0.0")][
        "values"
    ] == {"provider_root": tmp_path / "proteinmpnn", "device": "cpu"}
    assert configuration[
        ("structure_annotation.dssp_compute.mkdssp_local", "7.0.0")
    ] == {"values": {"dssp_binary": tmp_path / "bin/mkdssp"}}


def test_default_application_loads_process_provider_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "PROJECT",
        "CACHE",
        "OUTPUT",
        "RUN",
    ):
        monkeypatch.setenv(
            f"PROTEIN_WORKBENCH_{name}_ROOT",
            str(tmp_path / name.lower()),
        )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_ESMFOLD2_MODEL_ROOT",
        str(tmp_path / "esmfold2"),
    )
    monkeypatch.delenv(
        "PROTEIN_WORKBENCH_ESMFOLD2_ESMC_MODEL_ROOT",
        raising=False,
    )

    with pytest.raises(
        ProviderEnvironmentError,
        match="requires both configured model roots",
    ):
        create_application()


def test_process_provider_roots_must_be_absolute() -> None:
    with pytest.raises(
        ProviderEnvironmentError,
        match="must be absolute",
    ):
        provider_environment_configuration(
            {
                "PATH": os.environ["PATH"],
                "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT": "relative/provider",
            }
        )
