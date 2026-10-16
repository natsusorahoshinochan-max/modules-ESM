"""Shared SimpleFold Provider Asset Closure module contracts."""

from __future__ import annotations

from core.catalog.builder import build_frozen_catalog

from protein_workbench_public.bootstrap import module_registrations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.operation import ReadinessResult

from modules.folding.simplefold_asset_closure import (
    SimpleFoldClosureFile,
    SimpleFoldClosureSource,
    SimpleFoldProviderAssetClosure,
)


def _fixture_closure(tmp_path: Path) -> tuple[
    SimpleFoldProviderAssetClosure,
    dict[str, Path],
]:
    model_root = tmp_path / "models"
    esm2_model_root = tmp_path / "esm2-models"
    source_root = tmp_path / "esm2-source"
    model_root.mkdir(parents=True)
    esm2_model_root.mkdir()
    (source_root / "esm").mkdir(parents=True)
    (model_root / "model.ckpt").write_bytes(b"model\n")
    (model_root / "unrelated.ckpt").write_bytes(b"unrelated\n")
    (esm2_model_root / "esm2.pt").write_bytes(b"esm2\n")
    (esm2_model_root / "contact.pt").write_bytes(b"unrelated\n")
    (source_root / "hubconf.py").write_bytes(b"hub\n")
    (source_root / "esm" / "__init__.py").write_bytes(b"init\n")
    (source_root / "esm" / "pretrained.py").write_bytes(b"pretrained\n")
    (source_root / "esm" / "unrelated.py").write_bytes(b"unrelated\n")
    closure = SimpleFoldProviderAssetClosure(
        binding_id="fixture.simplefold",
        files=(
            SimpleFoldClosureFile(
                role="model",
                environment_key="model_root",
                runtime_group="simplefold_models",
                runtime_filename="model.ckpt",
            ),
            SimpleFoldClosureFile(
                role="language_model",
                environment_key="esm2_model_root",
                runtime_group="esm2_models",
                runtime_filename="esm2.pt",
            ),
        ),
        sources=(
            SimpleFoldClosureSource(
                role="language_model_runtime_source",
                environment_key="esm2_source_root",
                runtime_group="esm2_source",
            ),
        ),
    )
    return closure, {
        "model_root": model_root,
        "esm2_model_root": esm2_model_root,
        "esm2_source_root": source_root,
    }


def test_binding_declarations_select_distinct_route_files() -> None:
    from modules.folding.simplefold_asset_closure import (
        SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
        SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
    )

    folding_files = {
        entry.runtime_filename for entry in SIMPLEFOLD_FOLDING_ASSET_CLOSURE.files
    }
    confidence_files = {
        entry.runtime_filename
        for entry in SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE.files
    }

    assert folding_files == {
        "ccd.pkl",
        "esm2_t36_3B_UR50D-contact-regression.pt",
        "esm2_t36_3B_UR50D.pt",
        "plddt.ckpt",
        "simplefold_1.6B.ckpt",
        "simplefold_100M.ckpt",
    }
    assert confidence_files == {
        "ccd.pkl",
        "esm2_t36_3B_UR50D.pt",
        "plddt.ckpt",
        "simplefold_1.6B.ckpt",
    }
    assert confidence_files.isdisjoint(
        {
            "boltz1_conf.ckpt",
            "esm2_t36_3B_UR50D-contact-regression.pt",
            "simplefold_100M.ckpt",
            "simplefold_360M.ckpt",
        }
    )
    folding_architectures = next(
        source.required_relative_files
        for source in SIMPLEFOLD_FOLDING_ASSET_CLOSURE.sources
        if source.role == "provider_runtime_source"
    )
    confidence_architectures = next(
        source.required_relative_files
        for source in SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE.sources
        if source.role == "provider_runtime_source"
    )
    assert folding_architectures == (
        "configs/model/architecture/foldingdit_100M.yaml",
        "configs/model/architecture/plddt_module.yaml",
        "configs/model/architecture/foldingdit_1.6B.yaml",
    )
    assert confidence_architectures == (
        "configs/model/architecture/plddt_module.yaml",
        "configs/model/architecture/foldingdit_1.6B.yaml",
    )
    assert SIMPLEFOLD_FOLDING_ASSET_CLOSURE.sources[1:] == (
        SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE.sources[1:]
    )


@pytest.mark.parametrize(
    ("route", "location", "relative_path"),
    (
        ("folding", "model_root", "ccd.pkl"),
        ("folding", "model_root", "plddt.ckpt"),
        ("folding", "model_root", "simplefold_1.6B.ckpt"),
        ("folding", "model_root", "simplefold_100M.ckpt"),
        (
            "folding",
            "esm2_model_root",
            "esm2_t36_3B_UR50D.pt",
        ),
        (
            "folding",
            "esm2_model_root",
            "esm2_t36_3B_UR50D-contact-regression.pt",
        ),
        ("folding", "esm2_source_root", "esm/__init__.py"),
        ("folding", "esm2_source_root", "esm/pretrained.py"),
        (
            "folding",
            "package_root",
            "configs/model/architecture/foldingdit_100M.yaml",
        ),
        (
            "folding",
            "package_root",
            "configs/model/architecture/plddt_module.yaml",
        ),
        (
            "folding",
            "package_root",
            "configs/model/architecture/foldingdit_1.6B.yaml",
        ),
        ("confidence", "model_root", "ccd.pkl"),
        ("confidence", "model_root", "plddt.ckpt"),
        ("confidence", "model_root", "simplefold_1.6B.ckpt"),
        (
            "confidence",
            "esm2_model_root",
            "esm2_t36_3B_UR50D.pt",
        ),
        ("confidence", "esm2_source_root", "esm/__init__.py"),
        ("confidence", "esm2_source_root", "esm/pretrained.py"),
        (
            "confidence",
            "package_root",
            "configs/model/architecture/plddt_module.yaml",
        ),
        (
            "confidence",
            "package_root",
            "configs/model/architecture/foldingdit_1.6B.yaml",
        ),
    ),
)
def test_route_readiness_rejects_each_missing_fixed_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    location: str,
    relative_path: str,
) -> None:
    import modules.folding.simplefold_adapter as folding_adapter
    import modules.folding.simplefold_asset_closure as asset_closure
    import modules.folding.simplefold_confidence_adapter as confidence_adapter

    closure = (
        asset_closure.SIMPLEFOLD_FOLDING_ASSET_CLOSURE
        if route == "folding"
        else asset_closure.SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE
    )
    readiness = (
        folding_adapter.simplefold_readiness
        if route == "folding"
        else confidence_adapter.simplefold_confidence_readiness
    )
    unavailable_reason = (
        "simplefold_runtime_unavailable"
        if route == "folding"
        else "simplefold_confidence_runtime_unavailable"
    )
    model_root = tmp_path / "models"
    esm2_model_root = tmp_path / "esm2-models"
    esm2_source_root = tmp_path / "esm2-source"
    package_root = tmp_path / "simplefold-package"
    for root in (model_root, esm2_model_root, package_root):
        root.mkdir(parents=True)
    (esm2_source_root / "esm").mkdir(parents=True)
    (esm2_source_root / "esm" / "__init__.py").touch()
    (esm2_source_root / "esm" / "pretrained.py").touch()
    for entry in closure.files:
        root = {
            "model_root": model_root,
            "esm2_model_root": esm2_model_root,
        }[entry.environment_key]
        (root / entry.runtime_filename).touch()
    for source in closure.sources:
        for required_path in source.required_relative_files:
            path = package_root / required_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    monkeypatch.setattr(
        folding_adapter,
        "simplefold_runtime_structurally_available",
        lambda: True,
    )
    monkeypatch.setattr(
        confidence_adapter,
        "simplefold_confidence_runtime_structurally_available",
        lambda: True,
    )
    monkeypatch.setattr(
        folding_adapter,
        "local_torch_device_is_available",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        confidence_adapter,
        "local_torch_device_is_available",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        asset_closure.importlib.util,
        "find_spec",
        lambda _package_name: SimpleNamespace(
            origin=str(package_root / "__init__.py"),
            submodule_search_locations=(str(package_root),),
        ),
    )
    environment = {
        "model_root": model_root,
        "esm2_model_root": esm2_model_root,
        "esm2_source_root": esm2_source_root,
    }

    assert readiness(environment) == ReadinessResult(
        True,
        proof_source="direct-observation",
    )
    asset_root = {
        "model_root": model_root,
        "esm2_model_root": esm2_model_root,
        "esm2_source_root": esm2_source_root,
        "package_root": package_root,
    }[location]
    (asset_root / relative_path).unlink()
    assert readiness(environment) == ReadinessResult(
        False,
        proof_source="direct-observation",
        reason_code=unavailable_reason,
    )


def test_readiness_does_not_rewrite_local_declaration_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.simplefold_adapter as folding_adapter
    import modules.folding.simplefold_confidence_adapter as confidence_adapter
    import modules.folding.simplefold_contract as contract

    def raise_declaration_error(*_args: object) -> None:
        raise RuntimeError("fixture declaration error")

    monkeypatch.setattr(
        folding_adapter,
        "admit_simplefold_provider_asset_closure",
        raise_declaration_error,
    )
    monkeypatch.setattr(
        confidence_adapter,
        "admit_simplefold_provider_asset_closure",
        raise_declaration_error,
    )
    monkeypatch.setattr(
        folding_adapter,
        "simplefold_runtime_structurally_available",
        lambda: True,
    )
    monkeypatch.setattr(
        confidence_adapter,
        "simplefold_confidence_runtime_structurally_available",
        lambda: True,
    )

    with pytest.raises(RuntimeError, match="fixture declaration error"):
        folding_adapter.simplefold_readiness({})
    with pytest.raises(RuntimeError, match="fixture declaration error"):
        confidence_adapter.simplefold_confidence_readiness({})


def test_admitted_closure_binds_configured_roots_without_copying(
    tmp_path: Path,
) -> None:
    from modules.folding.simplefold_asset_closure import (
        admit_simplefold_provider_asset_closure,
        bind_simplefold_provider_asset_closure,
    )

    closure, environment = _fixture_closure(tmp_path)
    admit_simplefold_provider_asset_closure(closure, environment)

    (environment["model_root"] / "model.ckpt").write_bytes(
        b"trusted-after-admission\n"
    )
    (environment["esm2_source_root"] / "hubconf.py").write_bytes(
        b"trusted-source-after-admission\n"
    )
    bound = bind_simplefold_provider_asset_closure(
        closure,
        environment,
    )

    assert bound.group_root("simplefold_models") == environment["model_root"]
    assert bound.group_root("esm2_models") == environment["esm2_model_root"]
    assert bound.group_root("esm2_source") == environment["esm2_source_root"]
    assert (bound.group_root("simplefold_models") / "model.ckpt").read_bytes() == (
        b"trusted-after-admission\n"
    )
    assert (bound.group_root("esm2_source") / "hubconf.py").read_bytes() == (
        b"trusted-source-after-admission\n"
    )


def test_declaration_projects_operational_readiness_without_content_identity(
) -> None:
    from modules.folding.simplefold_asset_closure import (
        SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
        SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
    )

    for closure in (
        SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
        SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
    ):
        readiness = closure.readiness_prerequisite()
        assert {
            (item["role"], item["runtime_filename"])
            for item in readiness["files"]
        } == {
            (entry.role, entry.runtime_filename)
            for entry in closure.files
        }
        assert {
            item["role"]
            for item in readiness["sources"]
        } == {
            entry.role for entry in closure.sources
        }
        assert "sha256" not in repr(readiness)
        assert "revision" not in repr(readiness)


def test_admission_rejects_missing_route_resource(
    tmp_path: Path,
) -> None:
    from modules.folding.simplefold_asset_closure import (
        admit_simplefold_provider_asset_closure,
    )

    file_closure, file_environment = _fixture_closure(tmp_path / "file")
    (file_environment["model_root"] / "model.ckpt").unlink()
    with pytest.raises(RuntimeError, match="closure file is unavailable"):
        admit_simplefold_provider_asset_closure(
            file_closure,
            file_environment,
        )

    source_closure, source_environment = _fixture_closure(
        tmp_path / "source"
    )
    (
        source_environment["esm2_source_root"] / "esm" / "pretrained.py"
    ).unlink()
    with pytest.raises(
        RuntimeError,
        match="language-model source is unavailable",
    ):
        admit_simplefold_provider_asset_closure(
            source_closure,
            source_environment,
        )


def test_binding_readiness_descriptors_are_projected_from_owned_declarations(
) -> None:
    from modules.folding.simplefold_asset_closure import (
        SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
        SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
    )

    catalog = build_frozen_catalog(module_registrations())
    for binding_id, closure in (
        (
            "folding.fold.simplefold_local",
            SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
        ),
        (
            "folding.simplefold_confidence.simplefold_local",
            SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
        ),
    ):
        binding = catalog.require_contract("binding", binding_id)
        prerequisites = binding.descriptor["readiness_declaration"][
            "prerequisites"
        ]
        assert prerequisites["provider_asset_closure"] == (
            closure.readiness_prerequisite()
        )

    catalog.require_contract(
        "method",
        "folding.fold.simplefold_100m_c7a5570")
    catalog.require_contract(
        "method",
        (
            "folding.simplefold_confidence."
            "existing_structure_1_6b_c7a5570"
        ))
    for contract_kind, contract_id in (
        (
            "method",
            "structure_comparison.three_way_consistency.threshold_graph",
        ),
        (
            "port_type",
            "structure_comparison.three_way_consistency",
        ),
        (
            "node_type",
            "structure_comparison.classify_three_way_consistency",
        ),
        (
            "binding",
            "structure_comparison.classify_three_way_consistency.direct",
        ),
    ):
        catalog.require_contract(contract_kind, contract_id)


def test_catalog_projects_route_specific_architecture_files() -> None:
    catalog = build_frozen_catalog(module_registrations())

    for binding_id, expected_files in (
        (
            "folding.fold.simplefold_local",
            (
                "configs/model/architecture/foldingdit_100M.yaml",
                "configs/model/architecture/plddt_module.yaml",
                "configs/model/architecture/foldingdit_1.6B.yaml",
            ),
        ),
        (
            "folding.simplefold_confidence.simplefold_local",
            (
                "configs/model/architecture/plddt_module.yaml",
                "configs/model/architecture/foldingdit_1.6B.yaml",
            ),
        ),
    ):
        binding = catalog.require_contract("binding", binding_id)
        sources = binding.descriptor["readiness_declaration"][
            "prerequisites"
        ]["provider_asset_closure"]["sources"]
        provider_source = next(
            source
            for source in sources
            if source["role"] == "provider_runtime_source"
        )
        assert provider_source["required_relative_files"] == expected_files
