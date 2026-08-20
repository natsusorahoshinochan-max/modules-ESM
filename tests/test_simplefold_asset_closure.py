"""Shared SimpleFold Provider Asset Closure module contracts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from modules.folding.simplefold_asset_closure import (
    SimpleFoldClosureFile,
    SimpleFoldClosureSource,
    SimpleFoldProviderAssetClosure,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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
    (source_root / "esm" / "unrelated.py").write_bytes(b"unrelated\n")
    _git(source_root, "init", "--quiet")
    _git(source_root, "add", "hubconf.py", "esm/__init__.py")
    _git(
        source_root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    revision = _git(source_root, "rev-parse", "HEAD")
    closure = SimpleFoldProviderAssetClosure(
        binding_id="fixture.simplefold",
        files=(
            SimpleFoldClosureFile(
                role="model",
                environment_key="model_root",
                staging_group="simplefold_models",
                runtime_filename="model.ckpt",
                sha256=(
                    "98ad61a25e3683b6adf2474b01bbe1c27de6aad2ce3a80ff"
                    "4140fe473c14e691"
                ),
            ),
            SimpleFoldClosureFile(
                role="language_model",
                environment_key="esm2_model_root",
                staging_group="esm2_models",
                runtime_filename="esm2.pt",
                sha256=(
                    "facf4724c27c2071c26834ed10b5b81b045b42ea0d48ff73"
                    "7b7a32b3d8d39294"
                ),
            ),
        ),
        sources=(
            SimpleFoldClosureSource(
                role="language_model_runtime_source",
                environment_key="esm2_source_root",
                staging_group="esm2_source",
                revision=revision,
                reviewed_files=("esm/__init__.py", "hubconf.py"),
                source_tree_sha256=(
                    "f9348fda71bf91ee55355a6044f2fea9aa021e3a32ce25438"
                    "1fae34974dca70b"
                ),
            ),
        ),
    )
    return closure, {
        "model_root": model_root,
        "esm2_model_root": esm2_model_root,
        "esm2_source_root": source_root,
    }


def test_binding_declarations_fix_distinct_exact_asset_closures() -> None:
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
    assert {
        (source.role, source.revision)
        for source in SIMPLEFOLD_FOLDING_ASSET_CLOSURE.sources
    } == {
        (
            source.role,
            source.revision,
        )
        for source in SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE.sources
    }
    language_source = next(
        source
        for source in SIMPLEFOLD_FOLDING_ASSET_CLOSURE.sources
        if source.role == "language_model_runtime_source"
    )
    assert language_source.reviewed_files == (
        "esm/__init__.py",
        "esm/axial_attention.py",
        "esm/constants.py",
        "esm/data.py",
        "esm/model/__init__.py",
        "esm/model/esm1.py",
        "esm/model/esm2.py",
        "esm/model/msa_transformer.py",
        "esm/modules.py",
        "esm/multihead_attention.py",
        "esm/pretrained.py",
        "esm/rotary_embedding.py",
        "esm/version.py",
    )


def test_incomplete_source_declarations_fail_at_construction() -> None:
    with pytest.raises(ValueError, match="source declaration is incomplete"):
        SimpleFoldClosureSource(
            role="language_model_runtime_source",
            revision="fixture-revision",
            environment_key="esm2_source_root",
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

    with pytest.raises(RuntimeError, match="fixture declaration error"):
        folding_adapter.simplefold_readiness({
            "device": contract.SIMPLEFOLD_DEVICE,
        })
    with pytest.raises(RuntimeError, match="fixture declaration error"):
        confidence_adapter.simplefold_confidence_readiness({
            "device": contract.SIMPLEFOLD_CONFIDENCE_DEVICE,
        })


def test_admitted_closure_stages_only_declared_layout_without_a_second_proof(
    tmp_path: Path,
) -> None:
    from modules.folding.simplefold_asset_closure import (
        admit_simplefold_provider_asset_closure,
        stage_simplefold_provider_asset_closure,
    )

    closure, environment = _fixture_closure(tmp_path)
    admit_simplefold_provider_asset_closure(closure, environment)

    (environment["model_root"] / "model.ckpt").write_bytes(
        b"trusted-after-admission\n"
    )
    (environment["esm2_source_root"] / "hubconf.py").write_bytes(
        b"trusted-source-after-admission\n"
    )
    (environment["esm2_source_root"] / ".git").rename(
        environment["esm2_source_root"] / ".git-after-admission"
    )

    staged = stage_simplefold_provider_asset_closure(
        closure,
        environment,
        tmp_path / "staging",
    )

    assert (
        staged.group_root("simplefold_models") / "model.ckpt"
    ).read_bytes() == b"trusted-after-admission\n"
    assert (
        staged.group_root("esm2_models") / "esm2.pt"
    ).read_bytes() == b"esm2\n"
    assert (
        staged.group_root("esm2_source") / "hubconf.py"
    ).read_bytes() == b"trusted-source-after-admission\n"
    assert (
        staged.group_root("esm2_source") / "esm" / "__init__.py"
    ).read_bytes() == b"init\n"
    assert not (
        staged.group_root("simplefold_models") / "unrelated.ckpt"
    ).exists()
    assert not (staged.group_root("esm2_models") / "contact.pt").exists()
    assert not (
        staged.group_root("esm2_source") / "esm" / "unrelated.py"
    ).exists()


def test_declaration_projects_readiness_and_identity_without_acquisition_metadata(
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
        identity = closure.provider_identity()
        assert {
            (item["role"], item["runtime_filename"], item["sha256"])
            for item in readiness["files"]
        } == {
            (entry.role, entry.runtime_filename, entry.sha256)
            for entry in closure.files
        }
        assert {
            (item["role"], item["revision"])
            for item in readiness["sources"]
        } == {
            (entry.role, entry.revision) for entry in closure.sources
        }
        projected = json.dumps(
            {"readiness": readiness, "identity": identity},
            sort_keys=True,
        )
        assert '"bytes"' not in projected
        assert '"etag"' not in projected
        assert '"object"' not in projected


def test_admission_rejects_declared_file_and_reviewed_source_changes(
    tmp_path: Path,
) -> None:
    from modules.folding.simplefold_asset_closure import (
        admit_simplefold_provider_asset_closure,
    )

    file_closure, file_environment = _fixture_closure(tmp_path / "file")
    (file_environment["model_root"] / "model.ckpt").write_bytes(b"changed\n")
    with pytest.raises(RuntimeError, match="closure file changed"):
        admit_simplefold_provider_asset_closure(
            file_closure,
            file_environment,
        )

    source_closure, source_environment = _fixture_closure(
        tmp_path / "source"
    )
    (source_environment["esm2_source_root"] / "hubconf.py").write_bytes(
        b"changed\n"
    )
    with pytest.raises(RuntimeError, match="reviewed source tree changed"):
        admit_simplefold_provider_asset_closure(
            source_closure,
            source_environment,
        )


def test_binding_readiness_descriptors_are_projected_from_owned_declarations(
) -> None:
    from core import build_discovered_frozen_catalog
    from modules.folding.simplefold_asset_closure import (
        SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
        SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
    )

    catalog = build_discovered_frozen_catalog()
    for binding_id, version, closure in (
        (
            "folding.fold.simplefold_local",
            "10.0.0",
            SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
        ),
        (
            "folding.simplefold_confidence.simplefold_local",
            "6.0.0",
            SIMPLEFOLD_CONFIDENCE_ASSET_CLOSURE,
        ),
    ):
        binding = catalog.require_contract("binding", binding_id, version)
        prerequisites = binding.descriptor["readiness_declaration"][
            "prerequisites"
        ]
        assert prerequisites["provider_asset_closure"] == (
            closure.readiness_prerequisite()
        )

    catalog.require_contract(
        "method",
        "folding.fold.simplefold_100m_c7a5570",
        "5.0.0",
    )
    catalog.require_contract(
        "method",
        (
            "folding.simplefold_confidence."
            "existing_structure_1_6b_c7a5570"
        ),
        "4.0.0",
    )
    for contract_kind, contract_id, version in (
        (
            "method",
            "structure_comparison.three_way_consistency.threshold_graph",
            "2.0.0",
        ),
        (
            "port_type",
            "structure_comparison.three_way_consistency",
            "3.0.0",
        ),
        (
            "node_type",
            "structure_comparison.classify_three_way_consistency",
            "3.0.0",
        ),
        (
            "binding",
            "structure_comparison.classify_three_way_consistency.direct",
            "3.0.0",
        ),
    ):
        catalog.require_contract(contract_kind, contract_id, version)
