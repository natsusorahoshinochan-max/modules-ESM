"""Public process-environment loading for the installed backend CLI."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from protein_workbench_public.application_environment import (
    application_storage_roots,
)
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


def test_fresh_2emo_uses_the_process_selected_protein_sol_runtimes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_fresh_source_bound_acceptance_v2 import _environment

    executable_root = tmp_path / "provider executables"
    executable_root.mkdir()
    bash = executable_root / "bash"
    perl = executable_root / "perl"
    for executable in (bash, perl):
        executable.write_text("", encoding="utf-8")
        executable.chmod(0o755)
    token_file = tmp_path / "biohub-token"
    token_file.write_text("test-token\n", encoding="utf-8")
    token_file.chmod(0o600)
    monkeypatch.setenv("PATH", str(executable_root))
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",
        str(token_file),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROTEINMPNN_ROOT",
        str(tmp_path / "ProteinMPNN"),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT",
        str(tmp_path / "Protein-Sol"),
    )

    environment = _environment("fresh-2emo")
    protein_sol = environment[("solubility.protein_sol.local", "5.0.0")]

    assert protein_sol["values"]["bash_executable"] == bash
    assert protein_sol["values"]["perl_executable"] == perl


def test_process_environment_configures_every_selected_real_provider(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "biohub-token"
    token_file.write_text("test-token\n", encoding="utf-8")
    token_file.chmod(0o600)
    environment = {
        "PATH": os.environ["PATH"],
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE": str(token_file),
        "PROTEIN_WORKBENCH_DATA_ROOT": str(tmp_path / "workbench-data"),
        "PROTEIN_WORKBENCH_ESM3_MODEL_ROOT": str(
            tmp_path / "esm3-snapshot"
        ),
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
        "model_snapshot_path": tmp_path / "esm3-snapshot",
        "runtime_directory": (
            tmp_path / "workbench-data/provider-runtime/esm3"
        ),
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
    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path / "data"))
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


def test_default_application_requires_one_absolute_data_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROTEIN_WORKBENCH_DATA_ROOT", raising=False)

    with pytest.raises(RuntimeError, match="PROTEIN_WORKBENCH_DATA_ROOT"):
        create_application(v2_environment_configuration={})

    for configured in ("", "relative/data"):
        monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", configured)
        with pytest.raises(RuntimeError, match="must be absolute"):
            create_application(v2_environment_configuration={})


def test_application_data_root_expands_literal_tilde_before_deriving_stores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "operator-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    storage = application_storage_roots({
        "PROTEIN_WORKBENCH_DATA_ROOT": "~/protein-workbench-data",
    })

    assert storage.data == home / "protein-workbench-data"
    assert storage.projects == home / "protein-workbench-data/projects"
    assert storage.cache == home / "protein-workbench-data/cache"
    assert storage.outputs == home / "protein-workbench-data/outputs"
    assert storage.runs == home / "protein-workbench-data/runs"


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


@pytest.mark.parametrize("configured", ("", "relative/model"))
def test_local_esm3_model_root_must_be_absolute(configured: str) -> None:
    with pytest.raises(ProviderEnvironmentError, match="must be absolute"):
        provider_environment_configuration({
            "PROTEIN_WORKBENCH_DATA_ROOT": "/absolute/application-data",
            "PROTEIN_WORKBENCH_ESM3_MODEL_ROOT": configured,
        })


def test_local_esm3_model_root_expands_literal_tilde(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "operator-home"
    home.mkdir()
    data_root = tmp_path / "application-data"
    monkeypatch.setenv("HOME", str(home))

    configuration = provider_environment_configuration({
        "PROTEIN_WORKBENCH_DATA_ROOT": str(data_root),
        "PROTEIN_WORKBENCH_ESM3_MODEL_ROOT": "~/esm3-snapshot",
    })

    values = configuration[
        ("esm3.generate_sequence.local_open", "8.0.0")
    ]["values"]
    assert values["model_snapshot_path"] == home / "esm3-snapshot"
    assert values["runtime_directory"] == data_root / "provider-runtime/esm3"
