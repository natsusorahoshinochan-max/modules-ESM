"""Provider-free contracts for installed-gate configuration and resources."""

from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_external_acceptance_tree_uses_canonical_pytest_configuration(
    tmp_path: Path,
) -> None:
    from tests.providers.installed_harness import (
        _copy_external_acceptance_tree,
    )

    external_root = tmp_path / "external"
    _copy_external_acceptance_tree(external_root)

    assert (external_root / "pyproject.toml").read_bytes() == (
        PROJECT_ROOT / "pyproject.toml"
    ).read_bytes()


def test_distribution_declares_an_existing_root_readme() -> None:
    project = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["readme"] == "README.md"
    assert (PROJECT_ROOT / project["readme"]).is_file()


def test_installed_soluprot_gate_exercises_a_provider_root_with_spaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tests.support.installed_provider as installed_backend

    provider_root = tmp_path / "configured-soluprot"
    provider_root.mkdir()
    monkeypatch.setenv("PROTEIN_WORKBENCH_SOLUPROT_ROOT", str(provider_root))
    observed: dict[str, str] = {}

    def run_external_acceptance(
        _installed: object,
        _tmp_path: Path,
        *,
        selectors: tuple[str, ...],
        environment: dict[str, str],
        timeout_seconds: int,
    ) -> None:
        assert selectors
        assert timeout_seconds == 30 * 60
        observed.update(environment)

    monkeypatch.setattr(
        installed_backend,
        "run_external_acceptance",
        run_external_acceptance,
    )

    installed_backend.run_installed_provider_case(
        object(),
        tmp_path,
        "soluprot",
    )

    selected = Path(observed["PROTEIN_WORKBENCH_SOLUPROT_ROOT"])
    assert " " in selected.name
    assert selected.is_symlink()
    assert selected.resolve() == provider_root.resolve()


def test_solubility_gates_require_explicit_trusted_runtime_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tests.support.provider_paths import (
        trusted_protein_sol_root, trusted_soluprot_root,
    )

    monkeypatch.delenv("PROTEIN_WORKBENCH_SOLUPROT_ROOT", raising=False)
    monkeypatch.delenv("PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT", raising=False)
    with pytest.raises(AssertionError, match="SOLUPROT_ROOT"):
        trusted_soluprot_root()
    with pytest.raises(AssertionError, match="PROTEIN_SOL_ROOT"):
        trusted_protein_sol_root()

    monkeypatch.setenv("PROTEIN_WORKBENCH_SOLUPROT_ROOT", "relative")
    monkeypatch.setenv("PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT", "relative")
    with pytest.raises(AssertionError):
        trusted_soluprot_root()
    with pytest.raises(AssertionError):
        trusted_protein_sol_root()

    soluprot_root = tmp_path / "soluprot"
    protein_sol_root = tmp_path / "protein-sol"
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_SOLUPROT_ROOT",
        str(soluprot_root),
    )
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_PROTEIN_SOL_ROOT",
        str(protein_sol_root),
    )
    assert trusted_soluprot_root() == soluprot_root.resolve()
    assert trusted_protein_sol_root() == protein_sol_root.resolve()


def test_installed_gate_paths_are_explicit_and_token_checks_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tests.support.provider_paths import (
        required_absolute_path,
    )

    variable = "PROTEIN_WORKBENCH_TEST_PROVIDER_ROOT"
    monkeypatch.delenv(variable, raising=False)
    with pytest.raises(AssertionError, match="must be configured"):
        required_absolute_path(variable)
    monkeypatch.setenv(variable, "relative")
    with pytest.raises(AssertionError, match="absolute path"):
        required_absolute_path(variable)
    configured = tmp_path / "provider"
    monkeypatch.setenv(variable, str(configured))
    assert required_absolute_path(variable) == configured.resolve()

    sources = "\n".join(
        path.read_text()
        for path in (
            PROJECT_ROOT / "tests/providers/test_installed_provider_gates_v2.py",
            PROJECT_ROOT / "tests/installed/test_installed_backend_v2.py",
            PROJECT_ROOT / "tests/providers/test_soluprot_v2.py",
            PROJECT_ROOT / "tests/providers/test_protein_sol_v2.py",
        )
    )
    assert "/Users/" not in sources
    assert "assert credential_handle" not in sources


def test_mkdssp_gate_catalog_closure_is_buildable() -> None:
    from core.catalog.builder import (
        build_frozen_catalog,
    )
    from modules.protein_io.package import MODULE_PACKAGE as PROTEIN_IO_PACKAGE
    from modules.prompt_authoring.package import (
        MODULE_PACKAGE as PROMPT_AUTHORING_PACKAGE,
    )
    from modules.residue_data.package import (
        MODULE_PACKAGE as RESIDUE_DATA_PACKAGE,
    )
    from modules.structure_annotation.package import (
        MODULE_PACKAGE as STRUCTURE_ANNOTATION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    catalog = build_frozen_catalog(
        (
            PROTEIN_IO_PACKAGE,
            PROMPT_AUTHORING_PACKAGE, RESIDUE_DATA_PACKAGE,
            STRUCTURE_ANNOTATION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    binding = catalog.require_contract(
        "binding",
        "structure_annotation.dssp_compute.mkdssp_local",
    )
    method = binding.descriptor["method"]
    assert catalog.require_contract(
        "method",
        method["contract_id"],
    ).contract_id == method["contract_id"]
