"""Public v2 contracts for explicit local ESM-3 execution Bindings."""

from __future__ import annotations

from protein_workbench_public.bootstrap import module_registrations

from contextlib import contextmanager
from pathlib import Path
import hashlib
from typing import Any

import pytest

from core.catalog.builder import (
    build_frozen_catalog,
)
from core.run_execution_v2 import (
    V2RunError,
)


def _plain_invocations(
    invocations: list[dict[str, object]],
) -> list[dict[str, object]]:
    plain: list[dict[str, object]] = []
    for invocation in invocations:
        item = dict(invocation)
        provenance = item.get("invocation_provenance")
        if provenance is not None:
            randomness = provenance.effective_randomness  # type: ignore[union-attr]
            public_randomness = {"control": randomness.control}
            if randomness.effective_seed is not None:
                public_randomness["effective_seed"] = randomness.effective_seed
            item["invocation_provenance"] = {
                "effective_randomness": public_randomness,
            }
        plain.append(item)
    return plain


def _patch_local_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    accepted_revision: str = (
        "47f0545b2b6daf26a93439a3cd610f4f7f3d5478"
    ),
) -> None:
    import modules.esm3.local_adapter as local_adapter
    import modules.esm3.package as package

    runtime_directory = tmp_path / "local-runtime"
    snapshot_path = tmp_path / "local-snapshot"
    runtime_directory.mkdir(exist_ok=True)
    snapshot_path.mkdir(exist_ok=True)

    def resolve(environment: Any) -> local_adapter.LocalESM3Runtime:
        if environment.get("model_snapshot_revision") != accepted_revision:
            raise local_adapter.LocalESM3RuntimeUnavailable(
                "fixture model identity changed"
            )
        return local_adapter.LocalESM3Runtime(
            snapshot_path=snapshot_path,
            runtime_directory=runtime_directory,
            device="cpu",
            performance_settings={},
        )

    monkeypatch.setattr(
        package,
        "local_runtime_structurally_available",
        lambda: True,
    )
    monkeypatch.setattr(local_adapter, "resolve_local_runtime", resolve)


def _local_environment(tmp_path: Path) -> dict[str, Any]:
    return {
        "model_snapshot_path": tmp_path / "local-snapshot",
        "model_snapshot_revision": (
            "47f0545b2b6daf26a93439a3cd610f4f7f3d5478"
        ),
        "device": "cpu",
        "runtime_directory": tmp_path / "local-runtime",
        "performance_settings": {},
    }


def test_local_esm3_reuses_generation_nodes_alongside_direct_esmc() -> None:
    registrations = {
        registration.package_id: registration
        for registration in module_registrations()
    }
    registration = registrations["esm3"]
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/generate_sequence.yaml",
        "definitions/generate_structure.yaml",
        "definitions/generate_paired.yaml",
        "definitions/represent_sequence.yaml",
    }

    catalog = build_frozen_catalog(module_registrations())
    for operation in (
        "generate_sequence",
        "generate_structure",
        "generate_paired",
    ):
        local = catalog.require_contract(
            "binding",
            f"esm3.{operation}.local_open",
            "8.0.0",
        )
        remote = catalog.require_contract(
            "binding",
            f"esm3.{operation}.biohub_open",
            "8.0.0",
        )

        assert local.descriptor["node_type"] == remote.descriptor["node_type"]
        assert local.descriptor["produced_observations"] == ()
        assert remote.descriptor["produced_observations"] == ()
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
                "provider_sdk",
            }
        node = catalog.require_contract(
            "node_type",
            f"esm3.{operation}",
            "8.0.0",
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
    catalog = build_frozen_catalog(module_registrations())
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


def test_local_runtime_admits_exact_model_and_runtime_configuration(
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
    environment = {
        "model_snapshot_path": snapshot,
        "model_snapshot_revision": (
            local_adapter.LOCAL_ESM3_SNAPSHOT_REVISION
        ),
        "device": "cpu",
        "runtime_directory": runtime_directory,
        "performance_settings": {},
    }

    runtime = local_adapter.resolve_local_runtime(environment)
    assert runtime.artifact_sources == {
        "data/weights/fixture.pth": artifact,
    }

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

def test_huggingface_blob_links_are_admitted_by_digest_and_staged(
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
    runtime = local_adapter.resolve_local_runtime(
        {
            "model_snapshot_path": snapshot,
            "model_snapshot_revision": (
                local_adapter.LOCAL_ESM3_SNAPSHOT_REVISION
            ),
            "device": "cpu",
            "runtime_directory": runtime_directory,
            "performance_settings": {},
        }
    )

    staged = local_adapter.stage_local_runtime(runtime)
    staged_artifact = staged / "data" / "weights" / "fixture.pth"
    assert staged_artifact.is_file()
    assert not staged_artifact.is_symlink()
    assert staged_artifact.read_bytes() == payload


def test_successful_local_load_has_explicit_staging_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import esm.models.esm3 as esm3_model
    import esm.pretrained as esm_pretrained
    import modules.esm3.local_adapter as local_adapter

    class FakeESM3:
        def float(self) -> FakeESM3:
            return self

    def main_builder(device: object = "cpu") -> FakeESM3:
        del device
        return FakeESM3()

    def component_builder(device: object = "cpu") -> object:
        del device
        return object()

    payload = b"staged fixture"
    digest = hashlib.sha256(payload).hexdigest()
    artifact = tmp_path / "fixture.pth"
    artifact.write_bytes(payload)
    runtime_directory = tmp_path / "runtime"
    runtime_directory.mkdir()
    runtime = local_adapter.LocalESM3Runtime(
        snapshot_path=tmp_path,
        runtime_directory=runtime_directory,
        device="cpu",
        performance_settings={},
        artifact_sources={"fixture.pth": artifact},
    )
    monkeypatch.setattr(esm3_model, "ESM3", FakeESM3)
    monkeypatch.setattr(
        esm_pretrained,
        "LOCAL_MODEL_REGISTRY",
        {
            local_adapter.LOCAL_ESM3_MODEL: main_builder,
            "esm3_structure_encoder_v0": component_builder,
            "esm3_structure_decoder_v0": component_builder,
            "esm3_function_decoder_v0": component_builder,
        },
    )
    monkeypatch.setattr(
        local_adapter,
        "LOCAL_ESM3_WEIGHT_SHA256",
        {"fixture.pth": digest},
    )

    client = local_adapter.load_local_esm3_client(
        {},
        model_name=local_adapter.LOCAL_ESM3_MODEL,
        runtime=runtime,
    )
    staged_root = client._protein_workbench_staged_root
    assert staged_root.is_dir()

    local_adapter.release_local_esm3_client(client)

    assert not staged_root.exists()


def test_local_adapter_applies_the_derived_seed_and_returns_canonical_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import torch
    import modules.esm3.local_adapter as local_adapter

    from datatypes.prompt import ProteinPrompt
    from datatypes.residue import (
        ResidueLayout,
        ResidueTrack,
    )
    from datatypes.sequence import ProteinSequence
    from modules.esm3.adapter import ESM3CallParameters
    from modules.esm3.local_adapter import (
        LOCAL_ESM3_MODEL,
        LocalESM3Adapter,
    )
    from tests.fixtures.esm3_generation import ProviderClient, ProviderResponse

    class SeedRecordingClient(ProviderClient):
        def __init__(self) -> None:
            super().__init__([ProviderResponse("ACD")])
            self.seeds: list[int] = []

        def generate(self, protein: Any, config: Any) -> ProviderResponse:
            self.seeds.append(torch.initial_seed())
            return super().generate(protein, config)

    class InvocationResources:
        def __init__(self) -> None:
            self.invocations: list[dict[str, object]] = []

        @contextmanager
        def engine_invocation(self, **kwargs: object):
            self.invocations.append(dict(kwargs))
            yield "local-invocation"

    _patch_local_runtime(monkeypatch, tmp_path)
    client = SeedRecordingClient()
    monkeypatch.setattr(
        local_adapter,
        "load_local_esm3_client",
        lambda *_args, **_kwargs: client,
    )
    resources = InvocationResources()
    adapter = LocalESM3Adapter(
        environment=_local_environment(tmp_path),
        resources=resources,
        model_name=LOCAL_ESM3_MODEL,
    )
    prompt = ProteinPrompt(
        target_layout=ResidueLayout("A", 3, ["A:1", "A:2", "A:3"]),
        sequence_track=ResidueTrack([None, "C", "D"], None),
    )

    with adapter:
        result = adapter.generate_sequence(
            prompt,
            parameters=ESM3CallParameters(
                num_steps=4,
                temperature=1.0,
                top_p=1.0,
                schedule="cosine",
                strategy="random",
                temperature_annealing=True,
            ),
            derived_call_seed=17,
        )

    assert result.sequence == ProteinSequence(
        "ACD",
        ["A:1", "A:2", "A:3"],
    )
    assert result.effective_num_steps == 4
    assert result.effective_call_seed == 17
    assert client.seeds == [17]
    assert _plain_invocations(resources.invocations) == [
        {
            "engine_role": "sequence_sample",
            "parent_invocation_id": None,
            "invocation_provenance": {
                "effective_randomness": {
                    "control": "exact_seed",
                    "effective_seed": 17,
                }
            },
        }
    ]


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
    import modules.esm3.local_adapter as local_adapter

    from tests.fixtures.esm3_generation import (
        ProviderClient,
        ProviderResponse,
        decode_output,
        run_generation,
        three_residue_provider_pdb,
    )

    _patch_local_runtime(monkeypatch, tmp_path)
    readiness_resolve = local_adapter.resolve_local_runtime
    readiness_calls = 0

    def count_readiness(environment: Any) -> local_adapter.LocalESM3Runtime:
        nonlocal readiness_calls
        readiness_calls += 1
        return readiness_resolve(environment)

    monkeypatch.setattr(
        local_adapter,
        "resolve_local_runtime",
        count_readiness,
    )
    structure_response = lambda: ProviderResponse(
        "ACD",
        coordinates=torch.zeros((3, 37, 3)),
        ptm=torch.tensor([0.75]),
        plddt=torch.tensor([0.7, 0.8, 0.9]),
        pae=torch.tensor(
            [[
                [99.0, 99.0, 99.0, 99.0, 99.0],
                [99.0, 0.0, 1.0, 2.0, 99.0],
                [99.0, 3.0, 4.0, 5.0, 99.0],
                [99.0, 6.0, 7.0, 8.0, 99.0],
                [99.0, 99.0, 99.0, 99.0, 99.0],
            ]]
        ),
        pdb_string=three_residue_provider_pdb(),
    )
    responses = {
        "sequence": [ProviderResponse("ACD")],
        "structure": [structure_response()],
        "paired": [ProviderResponse("ACD"), structure_response()],
    }[response_kind]
    client = ProviderClient(responses)

    service, catalog, projection, events = run_generation(
        tmp_path,
        operation=operation,
        client=client,
        num_samples=1,
        sequence=sequence,
        binding_route="local_open",
        environment_overrides=_local_environment(tmp_path),
    )

    assert projection["status"] == "succeeded"
    assert readiness_calls == 1
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
    primary = decode_output(
        service, catalog, projection, outputs[primary_port]
    )
    assert len(primary.items) == 1
    forbidden = {
        "provider",
        "model",
        "route",
        "runtime_fingerprint",
        "checkpoint",
        "seed_control",
    }
    assert forbidden.isdisjoint(primary.items[0].metadata)
    assert isinstance(primary.items[0].metadata["effective_call_seed"], int)
    assert outputs[primary_port]["result_identity"].startswith("sha256:")
    if operation != "generate_sequence":
        confidence = decode_output(
            service, catalog, projection, outputs["confidence_facts"]
        )
        assert confidence.entries[0].ptm == pytest.approx(0.75)
        assert confidence.entries[0].pae == (
            (0.0, 1.0, 2.0),
            (3.0, 4.0, 5.0),
            (6.0, 7.0, 8.0),
        )
    if operation == "generate_paired":
        structures = decode_output(
            service,
            catalog,
            projection,
            outputs["structure_candidates"],
        )
        pairing = decode_output(
            service, catalog, projection, outputs["counterpart_pairs"]
        )
        assert structures.items[0].parent_ids == (
            primary.items[0].candidate_id,
        )
        assert pairing.entries[0].subject.candidate_id == (
            primary.items[0].candidate_id
        )
        assert pairing.entries[0].reference.candidate_id == (
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
        and event["event"]["engine_role"]
        in {
            "sequence_sample",
            "structure_sample",
            "sequence_parent",
            "structure_child",
        }
    ]
    assert len(generation_events) == (2 if operation == "generate_paired" else 1)
    binding = catalog.require_contract(
        "binding",
        f"esm3.{operation}.local_open",
        "8.0.0",
    )
    method = catalog.require_contract(
        "method",
        binding.descriptor["method"]["contract_id"],
        binding.descriptor["method"]["contract_version"],
    )
    assert {
        event["engine_identity"] for event in generation_events
    } == {method.contract_digest}
    assert all(
        event["invocation_provenance"]["effective_randomness"]["control"]
        == "exact_seed"
        and type(
            event["invocation_provenance"]["effective_randomness"][
                "effective_seed"
            ]
        )
        is int
        for event in generation_events
    )


def test_local_seed_is_declared_result_identity_randomness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.execution._node_attempt_identity as node_attempt_identity

    from tests.fixtures.esm3_generation import (
        ProviderClient,
        ProviderResponse,
        run_generation,
    )

    _patch_local_runtime(monkeypatch, tmp_path)
    descriptors: list[dict[str, Any]] = []
    result_identity_descriptor = (
        node_attempt_identity.result_identity_descriptor
    )

    def capture_result_identity(*args: Any, **kwargs: Any) -> dict[str, Any]:
        descriptor = result_identity_descriptor(*args, **kwargs)
        if args[0].node_id == "generate":
            descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(
        node_attempt_identity,
        "result_identity_descriptor",
        capture_result_identity,
    )
    _, _, projection, events = run_generation(
        tmp_path,
        operation="generate_sequence",
        client=ProviderClient([ProviderResponse("ACD")]),
        num_samples=1,
        binding_route="local_open",
        environment_overrides=_local_environment(tmp_path),
    )

    assert projection["status"] == "succeeded"
    assert descriptors
    assert all(
        "effective_seed" not in descriptor["node_parameters"]
        and descriptor["determinism"]["effective_randomness"]
        == {"effective_seed": 1603}
        for descriptor in descriptors
    )
    invocation = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "sequence_sample"
    )
    randomness = invocation["invocation_provenance"]["effective_randomness"]
    assert randomness["control"] == "exact_seed"
    assert type(randomness["effective_seed"]) is int


def test_default_local_client_releases_staged_runtime_after_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.esm3.local_adapter as local_adapter

    from tests.fixtures.esm3_generation import (
        ProviderClient,
        ProviderResponse,
        run_generation,
    )

    _patch_local_runtime(monkeypatch, tmp_path)
    client = ProviderClient([ProviderResponse("ACD")])
    released: list[Any] = []
    monkeypatch.setattr(
        local_adapter,
        "load_local_esm3_client",
        lambda environment, *, model_name, runtime: client,
    )
    monkeypatch.setattr(
        local_adapter,
        "release_local_esm3_client",
        lambda owned: released.append(owned),
    )

    _, _, projection, _ = run_generation(
        tmp_path,
        operation="generate_sequence",
        client=None,
        num_samples=1,
        binding_route="local_open",
        environment_overrides=_local_environment(tmp_path),
    )

    assert projection["status"] == "succeeded"
    assert released == [client]


def test_cleanup_failure_does_not_replace_primary_execution_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datatypes.prompt import ProteinPrompt
    from datatypes.residue import (
        ResidueLayout,
        ResidueTrack,
    )
    from modules.esm3.adapter import ESM3CallParameters
    import modules.esm3.local_adapter as local_adapter

    class FailingClient:
        @staticmethod
        def generate(protein: Any, config: Any) -> object:
            del protein, config
            raise RuntimeError("fixture provider failed")

    class InvocationResources:
        @contextmanager
        def engine_invocation(self, **kwargs: object):
            del kwargs
            yield "local-invocation"

    runtime_directory = tmp_path / "runtime"
    runtime_directory.mkdir()
    runtime = local_adapter.LocalESM3Runtime(
        snapshot_path=tmp_path,
        runtime_directory=runtime_directory,
        device="cpu",
        performance_settings={},
    )
    client = FailingClient()
    monkeypatch.setattr(
        local_adapter,
        "load_local_esm3_client",
        lambda environment, *, model_name, runtime: client,
    )

    def fail_cleanup(owned: object) -> None:
        assert owned is client
        raise OSError("fixture cleanup failed")

    monkeypatch.setattr(
        local_adapter,
        "release_local_esm3_client",
        fail_cleanup,
    )
    adapter = local_adapter.LocalESM3Adapter(
        environment={
            "model_snapshot_path": runtime.snapshot_path,
            "runtime_directory": runtime.runtime_directory,
        },
        resources=InvocationResources(),
        model_name=local_adapter.LOCAL_ESM3_MODEL,
    )
    prompt = ProteinPrompt(
        target_layout=ResidueLayout("A", 3, ["A:1", "A:2", "A:3"]),
        sequence_track=ResidueTrack([None, "C", "D"], None),
    )

    with pytest.raises(RuntimeError, match="fixture provider failed") as caught:
        with adapter:
            adapter.generate_sequence(
                prompt,
                parameters=ESM3CallParameters(
                    num_steps=4,
                    temperature=1.0,
                    top_p=1.0,
                    schedule="cosine",
                    strategy="random",
                    temperature_annealing=True,
                ),
                derived_call_seed=17,
            )

    assert caught.value.__notes__ == [
        "Local ESM-3 staged-weight cleanup also failed: OSError"
    ]


def test_local_binding_never_falls_back_to_remote_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.esm3_generation import ProviderClient, run_generation

    _patch_local_runtime(
        monkeypatch,
        tmp_path,
        accepted_revision="never-accepted",
    )
    remote_client = ProviderClient([])

    _service, _catalog, projection, _events = run_generation(
        tmp_path,
        operation="generate_sequence",
        client=remote_client,
        num_samples=1,
        binding_route="local_open",
        environment_overrides=_local_environment(tmp_path),
    )

    assert projection["status"] == "failed"
    assert remote_client.calls == []
