"""Public v2 contracts for explicit local ESM-3 execution Bindings."""

from __future__ import annotations

from pathlib import Path
import hashlib
from typing import Any

import pytest

from core import (
    ResultReplaySource,
    V2RunError,
    build_discovered_frozen_catalog,
    build_frozen_catalog,
    discover_module_packages,
)


def _patch_local_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    accepted_generation: str = "fixture-a",
) -> None:
    import modules.esm3.implementation as implementation
    import modules.esm3.local_adapter as local_adapter
    import modules.esm3.package as package

    runtime_directory = tmp_path / "local-runtime"
    snapshot_path = tmp_path / "local-snapshot"
    runtime_directory.mkdir(exist_ok=True)
    snapshot_path.mkdir(exist_ok=True)

    def resolve(environment: Any) -> local_adapter.LocalESM3Runtime:
        if environment.get("artifact_generation") != accepted_generation:
            raise RuntimeError("fixture model identity changed")
        return local_adapter.LocalESM3Runtime(
            snapshot_path=snapshot_path,
            runtime_directory=runtime_directory,
            device="cpu",
            performance_settings={},
            safe_fingerprint=f"sha256:{'a' * 64}",
        )

    monkeypatch.setattr(
        package,
        "local_runtime_structurally_available",
        lambda: True,
    )
    monkeypatch.setattr(local_adapter, "resolve_local_runtime", resolve)
    monkeypatch.setattr(implementation, "resolve_local_runtime", resolve)


def _local_environment(tmp_path: Path) -> dict[str, Any]:
    return {
        "model_snapshot_path": tmp_path / "local-snapshot",
        "model_snapshot_revision": (
            "47f0545b2b6daf26a93439a3cd610f4f7f3d5478"
        ),
        "device": "cpu",
        "runtime_directory": tmp_path / "local-runtime",
        "performance_settings": {},
        "resolved_runtime_fingerprint": f"sha256:{'a' * 64}",
        "artifact_generation": "fixture-a",
        "private_model_token": "local-secret-must-not-publish",
    }


def test_local_esm3_reuses_remote_nodes_and_observation_contracts() -> None:
    registrations = {
        registration.package_id: registration
        for registration in discover_module_packages()
    }
    registration = registrations["esm3"]
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/generate_sequence.yaml",
        "definitions/generate_structure.yaml",
        "definitions/generate_paired.yaml",
    }

    catalog = build_discovered_frozen_catalog()
    for operation in (
        "generate_sequence",
        "generate_structure",
        "generate_paired",
    ):
        local = catalog.require_contract(
            "binding",
            f"esm3.{operation}.local_open",
            "2.0.0",
        )
        remote = catalog.require_contract(
            "binding",
            f"esm3.{operation}.biohub_open",
            "2.0.0",
        )

        assert local.descriptor["node_type"] == remote.descriptor["node_type"]
        assert local.descriptor["produced_observations"] == (
            remote.descriptor["produced_observations"]
        )
        assert local.descriptor["binding_parameters"] == {}
        assert local.descriptor["execution_route"] == "adapter"
        assert local.descriptor["method"]["contract_id"] == (
            f"esm3.{operation}.esm3_sm_open_v1_local"
        )
        assert local.descriptor["deterministic"] is False
        assert local.descriptor["cacheable"] is False
        assert local.descriptor["implementation_identity"][
            "model"
        ] == "esm3_sm_open_v1"
        assert local.descriptor["implementation_identity"]["device"] == "cpu"
        assert local.descriptor["implementation_identity"][
            "torch_version"
        ] == "2.13.0"
        assert local.descriptor["implementation_identity"][
            "performance_settings"
        ] == {}
        assert set(local.descriptor["readiness_declaration"][
            "prerequisites"
        ]) == {
            "model_snapshot",
            "device",
            "runtime_directory",
            "performance_settings",
            "runtime_fingerprint",
            "provider_sdk",
        }
        node = catalog.require_contract(
            "node_type",
            f"esm3.{operation}",
            "2.0.0",
        )
        forbidden = {
            "model",
            "model_name",
            "model_snapshot_path",
            "device",
            "runtime_directory",
            "performance_settings",
        }
        assert forbidden.isdisjoint(node.descriptor["node_parameters"])


def test_local_startup_failure_isolated_from_remote_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.esm3.package as package

    monkeypatch.setattr(
        package,
        "local_runtime_structurally_available",
        lambda: False,
    )
    catalog = build_discovered_frozen_catalog()
    availability = {
        snapshot["binding"]["contract_id"]: snapshot
        for snapshot in catalog.availability
    }

    assert availability["esm3.generate_sequence.local_open"][
        "available"
    ] is False
    assert availability["esm3.generate_sequence.local_open"]["reason"] == {
        "code": "local_esm3_runtime_unavailable",
        "message": (
            "The exact local ESM SDK and Torch runtime prerequisites are "
            "unavailable."
        ),
        "retryable": False,
    }
    assert availability["esm3.generate_sequence.biohub_open"][
        "available"
    ] is True


def test_local_runtime_rejects_model_replacement_and_stale_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.esm3.local_adapter as local_adapter

    snapshot = tmp_path / "snapshot"
    runtime_directory = tmp_path / "runtime"
    artifact = snapshot / "data" / "weights" / "fixture.pth"
    artifact.parent.mkdir(parents=True)
    runtime_directory.mkdir()
    artifact.write_bytes(b"locked fixture")
    monkeypatch.setattr(
        local_adapter,
        "local_runtime_structurally_available",
        lambda: True,
    )
    monkeypatch.setattr(
        local_adapter,
        "LOCAL_ESM3_WEIGHT_SHA256",
        {
            "data/weights/fixture.pth": hashlib.sha256(
                b"locked fixture"
            ).hexdigest()
        },
    )
    fingerprint = local_adapter.configured_runtime_fingerprint(
        device="cpu",
    )
    environment = {
        "model_snapshot_path": snapshot,
        "model_snapshot_revision": (
            local_adapter.LOCAL_ESM3_SNAPSHOT_REVISION
        ),
        "device": "cpu",
        "runtime_directory": runtime_directory,
        "performance_settings": {},
        "resolved_runtime_fingerprint": fingerprint,
    }

    assert local_adapter.resolve_local_runtime(
        environment
    ).safe_fingerprint == fingerprint

    artifact.write_bytes(b"replaced fixture")
    with pytest.raises(RuntimeError, match="identity mismatch"):
        local_adapter.resolve_local_runtime(environment)

    artifact.write_bytes(b"locked fixture")
    changed_configuration = {
        **environment,
        "performance_settings": {"torch_num_threads": 1},
    }
    with pytest.raises(RuntimeError, match="performance settings"):
        local_adapter.resolve_local_runtime(changed_configuration)

    wrong_device = {**environment, "device": "mps"}
    with pytest.raises(RuntimeError, match="device does not match"):
        local_adapter.resolve_local_runtime(wrong_device)

    symlink_target = tmp_path / "outside-model.pth"
    symlink_target.write_bytes(b"locked fixture")
    artifact.unlink()
    artifact.symlink_to(symlink_target)
    with pytest.raises(RuntimeError, match="not repository-contained"):
        local_adapter.resolve_local_runtime(environment)


def test_huggingface_blob_links_are_contained_and_staged_as_regular_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.esm3.local_adapter as local_adapter

    repository = tmp_path / "models--biohub--esm3-sm-open-v1"
    snapshot = (
        repository
        / "snapshots"
        / local_adapter.LOCAL_ESM3_SNAPSHOT_REVISION
    )
    runtime_directory = tmp_path / "runtime"
    weights = snapshot / "data" / "weights"
    blobs = repository / "blobs"
    weights.mkdir(parents=True)
    blobs.mkdir()
    runtime_directory.mkdir()
    payload = b"locked huggingface blob"
    digest = hashlib.sha256(payload).hexdigest()
    blob = blobs / digest
    blob.write_bytes(payload)
    linked = weights / "fixture.pth"
    linked.symlink_to(Path("../../../../blobs") / digest)
    monkeypatch.setattr(
        local_adapter,
        "local_runtime_structurally_available",
        lambda: True,
    )
    monkeypatch.setattr(
        local_adapter,
        "LOCAL_ESM3_WEIGHT_SHA256",
        {"data/weights/fixture.pth": digest},
    )
    fingerprint = local_adapter.configured_runtime_fingerprint(device="cpu")
    runtime = local_adapter.resolve_local_runtime(
        {
            "model_snapshot_path": snapshot,
            "model_snapshot_revision": (
                local_adapter.LOCAL_ESM3_SNAPSHOT_REVISION
            ),
            "device": "cpu",
            "runtime_directory": runtime_directory,
            "performance_settings": {},
            "resolved_runtime_fingerprint": fingerprint,
        }
    )

    staged = local_adapter.stage_local_runtime(runtime)
    staged_artifact = staged / "data" / "weights" / "fixture.pth"
    assert staged_artifact.is_file()
    assert not staged_artifact.is_symlink()
    assert staged_artifact.read_bytes() == payload


@pytest.mark.parametrize(
    ("operation", "sequence", "response_kind"),
    (
        ("generate_sequence", None, "sequence"),
        ("generate_structure", "ACD", "structure"),
        ("generate_paired", None, "paired"),
    ),
)
def test_local_execution_preserves_remote_scientific_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    sequence: str | None,
    response_kind: str,
) -> None:
    import torch

    from tests.test_esm3_v2 import (
        _ProviderClient,
        _ProviderResponse,
        _decode_output,
        _run_generation,
        _three_residue_pdb,
    )

    _patch_local_runtime(monkeypatch, tmp_path)
    structure_response = lambda: _ProviderResponse(
        "ACD",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor(0.75),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
        pdb_string=_three_residue_pdb(),
    )
    responses = {
        "sequence": [_ProviderResponse("ACD")],
        "structure": [structure_response()],
        "paired": [_ProviderResponse("ACD"), structure_response()],
    }[response_kind]
    client = _ProviderClient(responses)

    catalog, projection, events = _run_generation(
        tmp_path,
        operation=operation,
        client=client,
        num_samples=1,
        sequence=sequence,
        binding_route="local_open",
        environment_overrides=_local_environment(tmp_path),
        safe_environment_fingerprint=f"sha256:{'a' * 64}",
        invalidation_token="local-fixture-a",
    )

    assert projection["status"] == "succeeded"
    outputs = {
        output["output_port"]: output
        for output in projection["outputs"]
        if output["node_id"] == "generate"
    }
    primary_port = {
        "generate_sequence": "sequence_candidates",
        "generate_structure": "structure_candidates",
        "generate_paired": "sequence_candidates",
    }[operation]
    primary = _decode_output(catalog, outputs[primary_port])
    assert len(primary.items) == 1
    assert primary.items[0].metadata["provider"] == "local_open"
    assert primary.items[0].metadata["model"] == "esm3_sm_open_v1"
    assert primary.items[0].metadata["seed_control"] == "torch_local"
    assert isinstance(primary.items[0].metadata["effective_call_seed"], int)
    assert outputs[primary_port]["result_identity"].startswith("sha256:")
    if operation == "generate_paired":
        structures = _decode_output(
            catalog,
            outputs["structure_candidates"],
        )
        pairing = _decode_output(catalog, outputs["counterpart_pairs"])
        assert structures.items[0].parent_ids == [
            primary.items[0].candidate_id
        ]
        assert pairing.entries[0].subject_candidate_id == (
            primary.items[0].candidate_id
        )
        assert pairing.entries[0].reference_candidate_id == (
            structures.items[0].candidate_id
        )
    readiness = [
        event["event"]
        for event in events
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == f"esm3.{operation}.local_open"
    ]
    assert len(readiness) == 1
    assert readiness[0]["attestation_digest"].startswith("sha256:")
    generation_events = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_identity"].startswith("esm3.local_open.")
    ]
    assert len(generation_events) == (2 if operation == "generate_paired" else 1)


def test_local_readiness_rechecks_model_identity_before_any_cache_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_esm3_v2 import (
        _ProviderClient,
        _ProviderResponse,
        _run_generation,
    )

    class LookupRecorder(ResultReplaySource):
        def __init__(self) -> None:
            self.lookups = 0

        def lookup(self, **kwargs: Any) -> None:
            del kwargs
            self.lookups += 1
            return None

    _patch_local_runtime(monkeypatch, tmp_path)
    cache = LookupRecorder()
    environment = _local_environment(tmp_path)
    environment["artifact_generation"] = "fixture-b"

    with pytest.raises(V2RunError) as rejected:
        _run_generation(
            tmp_path,
            operation="generate_sequence",
            client=_ProviderClient([_ProviderResponse("ACD")]),
            num_samples=1,
            binding_route="local_open",
            environment_overrides=environment,
            result_replay_source=cache,
            safe_environment_fingerprint=f"sha256:{'b' * 64}",
            invalidation_token="local-fixture-b",
        )

    assert rejected.value.code == "readiness_rejected"
    assert rejected.value.details["reason_code"] == "local_runtime_unavailable"
    assert "fixture model identity changed" not in str(rejected.value.details)
    assert "local-secret-must-not-publish" not in str(rejected.value.details)
    assert cache.lookups == 0


def test_local_binding_never_falls_back_to_remote_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_esm3_v2 import _ProviderClient, _run_generation

    _patch_local_runtime(
        monkeypatch,
        tmp_path,
        accepted_generation="never-accepted",
    )
    remote_client = _ProviderClient([])

    with pytest.raises(V2RunError) as rejected:
        _run_generation(
            tmp_path,
            operation="generate_sequence",
            client=remote_client,
            num_samples=1,
            binding_route="local_open",
            environment_overrides=_local_environment(tmp_path),
        )

    assert rejected.value.code == "readiness_rejected"
    assert remote_client.calls == []
