"""Public v2 contracts for the SimpleFold folding Binding."""

from __future__ import annotations

from tests.support.ledger import public_run_events, public_run_projection

from protein_workbench_public.bootstrap import module_registrations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from core.project.manager import ProjectManager
from core.catalog.builder import (
    build_frozen_catalog,
)
from core.operation import (
    ReadinessResult,
)
from core.execution.environment import admit_environment_configuration
from core.execution.node_attempt import NodeAttemptFactory
from core.execution.runtime import (
    V2RunService,
)
from tests.support.result_store import result_store
from core.workflow.authoring import WorkflowAuthoringService
from core.workflow.document import (
    WorkflowDocument,
    WorkflowNodeInstance,
)
from core.workflow.document import WorkflowEdge
from datatypes.candidate import (
    Candidate,
    CandidateCollection,
)
from datatypes.sequence import ProteinSequence
from datatypes.structure import ProteinStructure
from tests.fixtures.scientific_operation import (
    operation_call,
    operation_context,
)
from tests.fixtures.simplefold import (
    build_fixture_simplefold_closure,
    install_fixture_source_runtime_group,
)


_SIMPLEFOLD_BINDING_VERSION = "10.0.0"


def test_simplefold_runtime_applies_the_exact_normalized_step_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import sys
    from types import ModuleType

    import modules.folding.simplefold_runtime as simplefold_runtime

    class StopAfterInferenceConstruction(Exception):
        pass

    captured: dict[str, int] = {}

    class InferenceWrapper:
        def __init__(self, **kwargs: Any) -> None:
            captured["num_steps"] = kwargs["num_steps"]
            raise StopAfterInferenceConstruction

    modules = {
        "simplefold": ModuleType("simplefold"),
        "simplefold.utils": ModuleType("simplefold.utils"),
        "simplefold.wrapper": ModuleType("simplefold.wrapper"),
        "simplefold.utils.boltz_utils": ModuleType(
            "simplefold.utils.boltz_utils"
        ),
        "simplefold.utils.fasta_utils": ModuleType(
            "simplefold.utils.fasta_utils"
        ),
        "simplefold.utils.datamodule_utils": ModuleType(
            "simplefold.utils.datamodule_utils"
        ),
        "utils.esm_utils": ModuleType("utils.esm_utils"),
    }
    modules["simplefold.wrapper"].InferenceWrapper = InferenceWrapper
    modules["simplefold.utils.boltz_utils"].process_structure = object()
    modules["simplefold.utils.boltz_utils"].to_pdb = object()
    modules["simplefold.utils.fasta_utils"].process_fastas = (
        lambda **_kwargs: None
    )
    modules[
        "simplefold.utils.datamodule_utils"
    ].process_one_inference_structure = object()
    modules["utils.esm_utils"].esm_registry = {}
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    monkeypatch.setattr(
        simplefold_runtime,
        "_setup_simplefold_imports",
        os.getcwd,
    )
    model_root = tmp_path / "model"
    esm2_source_root = tmp_path / "esm2-source"
    esm2_model_root = tmp_path / "esm2-model"
    for root in (model_root, esm2_source_root, esm2_model_root):
        root.mkdir()
    (model_root / "ccd.pkl").write_bytes(b"reviewed-ccd")

    with pytest.raises(StopAfterInferenceConstruction):
        simplefold_runtime.fold_sequence(
            ProteinSequence("AG", ("A:1", "A:2")),
            num_steps=75,
            num_samples=1,
            staging_directory=tmp_path / "project",
            effective_seed=1603,
            staged_model_root=model_root,
            staged_esm2_source_root=esm2_source_root,
            staged_esm2_model_root=esm2_model_root,
        )

    assert captured == {"num_steps": 75}


def test_simplefold_runtime_releases_esm2_before_loading_folding_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import sys
    from types import ModuleType

    import modules.folding.simplefold_runtime as simplefold_runtime

    class StopAfterStagedModelLoad(Exception):
        pass

    lifecycle: dict[str, bool] = {}

    class LanguageModel:
        def __del__(self) -> None:
            lifecycle["language_model_released"] = True

    class InferenceWrapper:
        def __init__(self, **_kwargs: Any) -> None:
            self.tokenizer = object()
            self.featurizer = object()
            self.processor = object()
            self.esm_model = LanguageModel()
            self.esm_dict = object()
            self.af2_to_esm = object()

        def run_inference(self, *_args: Any) -> object:
            assert len(loaded_modules) == 3
            raise StopAfterStagedModelLoad

    loaded_checkpoints: list[tuple[str, dict[str, Any]]] = []
    loaded_configs: list[str] = []
    loaded_modules: list[dict[str, Any]] = []

    def load_checkpoint(
        path: Path,
        **kwargs: Any,
    ) -> dict[str, str]:
        assert lifecycle["features_prepared"] is True
        assert lifecycle["language_model_released"] is True
        loaded_checkpoints.append((Path(path).name, kwargs))
        return {"checkpoint": Path(path).name}

    class LoadedModule:
        def __init__(self, config: str) -> None:
            self.config = config

        def load_state_dict(
            self,
            checkpoint: dict[str, str],
            *,
            strict: bool,
            assign: bool,
        ) -> None:
            loaded_modules.append(
                {
                    "config": self.config,
                    "checkpoint": checkpoint["checkpoint"],
                    "strict": strict,
                    "assign": assign,
                }
            )

        def to(self, device: object) -> LoadedModule:
            assert str(device) == "cpu"
            return self

        def eval(self) -> LoadedModule:
            return self

    def load_config(path: Path) -> str:
        config = str(path)
        loaded_configs.append(config)
        return config

    def instantiate(config: str) -> LoadedModule:
        return LoadedModule(config)

    def process_fastas(*, out_dir: Path, **_kwargs: Any) -> None:
        structures = Path(out_dir) / "structures"
        records = Path(out_dir) / "records"
        structures.mkdir(parents=True)
        records.mkdir(parents=True)
        (structures / "input.npz").touch()
        (records / "input.json").write_text("{}")

    def process_one_inference_structure(
        *_args: Any,
    ) -> tuple[object, object, object]:
        lifecycle["features_prepared"] = True
        return object(), object(), object()

    modules = {
        "simplefold": ModuleType("simplefold"),
        "simplefold.utils": ModuleType("simplefold.utils"),
        "simplefold.wrapper": ModuleType("simplefold.wrapper"),
        "simplefold.utils.boltz_utils": ModuleType(
            "simplefold.utils.boltz_utils"
        ),
        "simplefold.utils.fasta_utils": ModuleType(
            "simplefold.utils.fasta_utils"
        ),
        "simplefold.utils.datamodule_utils": ModuleType(
            "simplefold.utils.datamodule_utils"
        ),
        "utils.esm_utils": ModuleType("utils.esm_utils"),
        "hydra": ModuleType("hydra"),
        "omegaconf": ModuleType("omegaconf"),
    }

    class HydraUtils:
        instantiate = staticmethod(lambda _config: None)

    class OmegaConf:
        load = staticmethod(lambda _path: None)

    modules["hydra"].utils = HydraUtils
    modules["omegaconf"].OmegaConf = OmegaConf
    modules["simplefold.wrapper"].InferenceWrapper = InferenceWrapper
    modules["simplefold.utils.boltz_utils"].process_structure = object()
    modules["simplefold.utils.boltz_utils"].to_pdb = object()
    modules["simplefold.utils.fasta_utils"].process_fastas = process_fastas
    modules[
        "simplefold.utils.datamodule_utils"
    ].process_one_inference_structure = process_one_inference_structure
    modules["utils.esm_utils"].esm_registry = {}
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    monkeypatch.setattr(
        simplefold_runtime,
        "_setup_simplefold_imports",
        os.getcwd,
    )
    import hydra
    import omegaconf

    monkeypatch.setattr(simplefold_runtime.torch, "load", load_checkpoint)
    monkeypatch.setattr(omegaconf.OmegaConf, "load", load_config)
    monkeypatch.setattr(hydra.utils, "instantiate", instantiate)
    model_root = tmp_path / "model"
    esm2_source_root = tmp_path / "esm2-source"
    esm2_model_root = tmp_path / "esm2-model"
    for root in (model_root, esm2_source_root, esm2_model_root):
        root.mkdir()
    (model_root / "ccd.pkl").write_bytes(b"reviewed-ccd")

    with pytest.raises(StopAfterStagedModelLoad):
        simplefold_runtime.fold_sequence(
            ProteinSequence("AG", ("A:1", "A:2")),
            num_steps=50,
            num_samples=1,
            staging_directory=tmp_path / "project",
            effective_seed=1603,
            staged_model_root=model_root,
            staged_esm2_source_root=esm2_source_root,
            staged_esm2_model_root=esm2_model_root,
        )

    assert loaded_checkpoints == [
        (
            "simplefold_100M.ckpt",
            {"map_location": "cpu", "weights_only": False, "mmap": True},
        ),
        (
            "plddt.ckpt",
            {"map_location": "cpu", "weights_only": False, "mmap": True},
        ),
        (
            "simplefold_1.6B.ckpt",
            {"map_location": "cpu", "weights_only": False, "mmap": True},
        ),
    ]
    assert loaded_configs == [
        "configs/model/architecture/foldingdit_100M.yaml",
        "configs/model/architecture/plddt_module.yaml",
        "configs/model/architecture/foldingdit_1.6B.yaml",
    ]
    assert all(module["strict"] is True for module in loaded_modules)
    assert all(module["assign"] is True for module in loaded_modules)


def test_simplefold_confidence_loads_only_the_two_plddt_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.simplefold_runtime as simplefold_runtime

    loaded: list[tuple[str, str]] = []

    def load_module(
        *,
        config_path: Path,
        checkpoint_path: Path,
        device: object,
    ) -> object:
        assert str(device) == "cpu"
        loaded.append((str(config_path), checkpoint_path.name))
        return object()

    monkeypatch.setattr(
        simplefold_runtime,
        "_load_reviewed_torch_module",
        load_module,
    )

    result = simplefold_runtime._load_reviewed_plddt_models(
        tmp_path,
        "cpu",
    )

    assert loaded == [
        (
            "configs/model/architecture/plddt_module.yaml",
            "plddt.ckpt",
        ),
        (
            "configs/model/architecture/foldingdit_1.6B.yaml",
            "simplefold_1.6B.ckpt",
        ),
    ]
    assert set(result) == {"plddt_out_module", "plddt_latent_module"}


def test_simplefold_is_one_explicit_binding_of_the_shared_folding_node() -> None:
    registrations = {
        registration.package_id: registration
        for registration in module_registrations()
    }
    registration = registrations["folding"]
    assert {
        resource.resource for resource in registration.node_definitions
    } == {
        "definitions/fold.yaml",
        "definitions/simplefold_confidence.yaml",
    }

    catalog = build_frozen_catalog(module_registrations())
    simplefold = catalog.require_contract(
        "binding",
        "folding.fold.simplefold_local",
        _SIMPLEFOLD_BINDING_VERSION,
    )
    esmfold2 = catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local",
        "10.0.0",
    )
    assert simplefold.descriptor["node_type"] == esmfold2.descriptor["node_type"]
    assert simplefold.descriptor["execution_route"] == "adapter"
    assert simplefold.descriptor["binding_parameters"] == {
        "num_steps": {
            "parameter_scope": "scientific",
            "scientific_meaning": (
                "Exact SimpleFold Euler-Maruyama sampling step count."
            ),
            "value_contract": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
            },
            "default": 50,
        },
    }
    assert simplefold.descriptor["deterministic"] is False
    assert simplefold.descriptor["cacheable"] is False
    assert simplefold.descriptor["implementation_identity"]["model"] == (
        "simplefold_100M"
    )
    assert simplefold.descriptor["implementation_identity"]["device"] == (
        "cpu"
    )
    assert simplefold.descriptor["produced_observations"] == ()

    method_reference = simplefold.descriptor["method"]
    method = catalog.require_contract(
        method_reference["contract_kind"],
        method_reference["contract_id"],
        method_reference["contract_version"],
    )
    assert method_reference["contract_version"] == "5.0.0"
    assert method.descriptor["model_identity"]["folding_model"] == (
        "simplefold_100M"
    )
    assert method.descriptor["scale_contract"]["plddt"] == (
        "provider_high_level_[0,100]_identity"
    )
    assert {
        "model",
        "model_name",
        "checkpoint_path",
        "device",
        "staging_directory",
    }.isdisjoint(simplefold.descriptor["binding_parameters"])
    assert set(
        method.descriptor["checkpoint_identity"][
            "simplefold_artifact_sha256"
        ]
    ) == {
        "ccd.pkl",
        "plddt.ckpt",
        "simplefold_1.6B.ckpt",
        "simplefold_100M.ckpt",
    }


def test_simplefold_readiness_validates_assets_without_hiding_siblings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.package as folding_package
    import modules.folding.simplefold_adapter as adapter
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    environment = _simplefold_environment(
        tmp_path,
        monkeypatch,
        client=object(),
    )
    assert adapter.simplefold_readiness(environment) == ReadinessResult(
        True,
        proof_source="direct-observation",
    )
    identity = (
        adapter.simplefold_contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE
        .provider_identity()
    )
    assert set(identity["artifact_sha256"]) == {
        "ccd.pkl",
        "plddt.ckpt",
        "simplefold_1.6B.ckpt",
        "simplefold_100M.ckpt",
    }
    (environment["model_root"] / "simplefold_100M.ckpt").write_bytes(
        b"replacement"
    )
    assert adapter.simplefold_readiness(environment) == ReadinessResult(
        False,
        proof_source="direct-observation",
        reason_code="simplefold_runtime_unavailable",
    )

    monkeypatch.setattr(
        folding_package,
        "simplefold_runtime_structurally_available",
        lambda: False,
    )
    catalog = build_frozen_catalog(
        (
            folding_package.MODULE_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    assert catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_remote",
        "9.0.0",
    )
    assert catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local",
        "10.0.0",
    )
    snapshots = {
        item.binding.contract_id: item
        for item in catalog.availability
    }
    assert not snapshots["folding.fold.simplefold_local"].result.is_available
    assert {
        "folding.fold.esmfold2_remote",
        "folding.fold.esmfold2_local",
    }.issubset(snapshots)


def _two_residue_pdb() -> str:
    return "\n".join(
        (
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 71.00           N  ",
            "ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 71.00           C  ",
            "ATOM      3  C   ALA A   1       2.000   0.000   0.000  1.00 71.00           C  ",
            "ATOM      4  N   GLY A   2       3.000   0.000   0.000  1.00 83.00           N  ",
            "ATOM      5  CA  GLY A   2       4.000   0.000   0.000  1.00 83.00           C  ",
            "ATOM      6  C   GLY A   2       5.000   0.000   0.000  1.00 83.00           C  ",
            "TER",
            "END",
            "",
        )
    )


def _upstream_simplefold_serialized_pdb(
    canonical_pdb: str | None = None,
) -> str:
    """Match the pinned provider writer's padded final sentinel exactly."""
    source = _two_residue_pdb() if canonical_pdb is None else canonical_pdb
    return "\n".join(
        line.ljust(80)
        for line in (*source.splitlines(), "")
    )


def _decode_output(
    catalog: Any,
    service: V2RunService,
    projection: dict[str, Any],
    output: dict[str, Any],
) -> Any:
    from tests.fixtures.public_v2 import decode_service_typed_output_value

    return decode_service_typed_output_value(
        service,
        catalog,
        projection,
        output,
    )


def _trusted_serialized_pdb_with_independent_residue_names() -> str:
    return "\n".join(
        (
            "ATOM      1  N   GLY A   8       0.000   0.000   0.000  1.00 71.00           N  ",
            "ATOM      2  CA  GLY A   8       1.000   0.000   0.000  1.00 71.00           C  ",
            "ATOM      3  C   GLY A   8       2.000   0.000   0.000  1.00 71.00           C  ",
            "ATOM      4  N   ALA A  13       3.000   0.000   0.000  1.00 83.00           N  ",
            "ATOM      5  CA  ALA A  13       4.000   0.000   0.000  1.00 83.00           C  ",
            "ATOM      6  C   ALA A  13       5.000   0.000   0.000  1.00 83.00           C  ",
            "TER",
            "END",
            "",
        )
    )


def _simplefold_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: Any,
) -> dict[str, Any]:
    import modules.folding.simplefold_adapter as adapter
    import modules.folding.simplefold_asset_closure as asset_closure
    import modules.folding.simplefold_contract as contract
    import modules.folding.simplefold_runtime as simplefold_runtime

    def fixture_fold_sequence(**kwargs: Any) -> Any:
        return client.fold(
            sequence=kwargs["sequence"],
            num_steps=kwargs["num_steps"],
            num_samples=kwargs["num_samples"],
            effective_seed=kwargs["effective_seed"],
            staging_directory=kwargs["staging_directory"],
        )

    monkeypatch.setattr(
        simplefold_runtime,
        "fold_sequence",
        fixture_fold_sequence,
    )
    install_fixture_source_runtime_group(monkeypatch, adapter)

    model_root = tmp_path / "models"
    esm2_model_root = tmp_path / "esm2-models"
    esm2_source_root = tmp_path / "esm2-source"
    model_root.mkdir(parents=True)
    esm2_model_root.mkdir()
    esm2_source_root.mkdir()
    model_payloads = {
        entry.runtime_filename: f"fixture-{entry.runtime_filename}".encode()
        for entry in contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE.files
        if entry.environment_key == "model_root"
    }
    esm2_payloads = {
        "esm2_t36_3B_UR50D.pt": b"fixture-esm2",
        "esm2_t36_3B_UR50D-contact-regression.pt": b"fixture-contact",
    }
    for name, payload in model_payloads.items():
        (model_root / name).write_bytes(payload)
    for name, payload in esm2_payloads.items():
        (esm2_model_root / name).write_bytes(payload)
    fixture_digests = {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in (*model_payloads.items(), *esm2_payloads.items())
    }
    fixture_closure = build_fixture_simplefold_closure(
        contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
        fixture_digests,
    )
    monkeypatch.setattr(
        contract,
        "SIMPLEFOLD_FOLDING_ASSET_CLOSURE",
        fixture_closure,
    )
    monkeypatch.setattr(
        asset_closure,
        "validate_installed_provider_checkout",
        lambda *_args, **_kwargs: None,
    )
    return {
        "model_root": model_root,
        "esm2_model_root": esm2_model_root,
        "esm2_source_root": esm2_source_root,
        "device": contract.SIMPLEFOLD_DEVICE,
    }


def _run_simplefold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    client: Any,
    num_samples: int = 2,
    environment_values: dict[str, Any] | None = None,
    project_id: str = "simplefold",
) -> tuple[Any, V2RunService, dict[str, Any], tuple[dict[str, Any], ...]]:
    import modules.folding.package as folding_package
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from tests.fixtures.folding_sources.package import (
        MODULE_PACKAGE as SOURCE_PACKAGE,
    )

    source = WorkflowNodeInstance(
        node_id="source",
        node_type_id="contract_test.folding_sequence_source",
        node_type_version="4.0.0",
        binding_id="contract_test.folding_sequence_source.direct",
        binding_version="4.0.0",
        node_parameters={"sequence": "AG"},
        binding_parameters={},
    )
    fold = WorkflowNodeInstance(
        node_id="fold",
        node_type_id="folding.fold",
        node_type_version="8.0.0",
        binding_id="folding.fold.simplefold_local",
        binding_version=_SIMPLEFOLD_BINDING_VERSION,
        node_parameters={
            "effective_seed": 1603,
            "num_samples": num_samples,
        },
        binding_parameters={"num_steps": 10},
    )
    materialize = WorkflowNodeInstance(
        node_id="materialize-confidence",
        node_type_id="structure_prediction.materialize_confidence",
        node_type_version="2.0.0",
        binding_id="structure_prediction.materialize_confidence.direct",
        binding_version="2.0.0",
        node_parameters={},
        binding_parameters={},
    )
    monkeypatch.setattr(
        folding_package,
        "simplefold_runtime_structurally_available",
        lambda: True,
    )
    catalog = build_frozen_catalog(
        (
            folding_package.MODULE_PACKAGE,
            SOURCE_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    projects = ProjectManager(
        tmp_path / "projects",
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "outputs",
        run_root=tmp_path / "runs",
    )
    project = projects.create(project_id)
    authoring = WorkflowAuthoringService(projects, catalog)
    workflow = WorkflowDocument(
        schema_version="2.1.0",
        workflow_id=project.id,
        nodes=(source, fold, materialize),
        edges=(
            WorkflowEdge(
                "source",
                "sequence_candidates",
                "fold",
                "sequence_candidates",
            ),
            WorkflowEdge(
                "fold",
                "structure_candidates",
                "materialize-confidence",
                "structure_candidates",
            ),
            WorkflowEdge(
                "fold",
                "confidence_facts",
                "materialize-confidence",
                "confidence_facts",
            ),
        ),
        contract_lock=(),
    )
    committed = authoring.commit(
        project.id,
        workflow=workflow,
    )
    if environment_values is None:
        environment_values = _simplefold_environment(
            tmp_path,
            monkeypatch,
            client,
        )
    environment = admit_environment_configuration(
        catalog,
        {
            (
                "folding.fold.simplefold_local",
                _SIMPLEFOLD_BINDING_VERSION,
            ): {
                "values": environment_values,
            }
        },
    )
    service = V2RunService(
        projects,
        catalog,
        authoring,
        NodeAttemptFactory(
            projects,
            environment,
            result_store(projects),
        ),
        result_store(projects),
    )
    try:
        receipt = service.start_background(
            project.id,
            workflow_commit_id=committed.workflow_commit_id,
            client_request_id="simplefold",
        )
        service.shutdown()
        projection = public_run_projection(service, project.id, receipt["run_id"])
        events = public_run_events(service, project.id, receipt["run_id"])
    finally:
        service.shutdown()
    return catalog, service, projection, events


def test_closure_admission_failure_is_a_binding_failure_without_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def fold(self, **_kwargs: Any) -> Any:
            self.calls += 1
            raise AssertionError("Provider entry must not start")

    client = Client()
    environment = _simplefold_environment(
        tmp_path / "environment",
        monkeypatch,
        client,
    )
    (environment["model_root"] / "simplefold_100M.ckpt").write_bytes(
        b"changed-before-admission"
    )

    _, _, projection, events = _run_simplefold(
        tmp_path / "run",
        monkeypatch,
        client=client,
        num_samples=1,
        environment_values=environment,
    )

    event_types = [event["event"]["type"] for event in events]
    assert projection["status"] == "failed"
    assert event_types.count("operation_attempt_started") == 1
    assert event_types.count("operation_attempt_terminal") == 1
    assert all(
        event["event"].get("engine_role") != "fold_parent_0"
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
    )
    terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "node_attempt_terminal"
        and event["event"].get("failure_origin") == "binding"
    )
    assert terminal["error"]["code"] == "readiness_rejected"
    assert client.calls == 0


def test_simplefold_preserves_high_level_plddt_and_exact_multi_sample_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.package as folding_package

    monkeypatch.setattr(
        folding_package,
        "simplefold_runtime_structurally_available",
        lambda: False,
    )

    class Client:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def fold(self, **kwargs: Any) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            self.calls.append(kwargs)
            return (
                [
                    ProteinStructure(_upstream_simplefold_serialized_pdb()),
                    ProteinStructure(_upstream_simplefold_serialized_pdb()),
                ],
                [
                    {
                        "per_residue": (
                            [0.71, 0.83]
                            if sample == 0
                            else [71.0, 83.0]
                        ),
                        "sample_index": sample,
                    }
                    for sample in reversed(range(2))
                ],
            )

    client = Client()
    catalog, service, projection, events = _run_simplefold(
        tmp_path,
        monkeypatch,
        client=client,
    )

    assert projection["status"] == "succeeded", json.dumps(events, indent=2)
    outputs = {
        output["output_port"]: output
        for output in projection["outputs"]
        if output["node_id"] == "fold"
    }
    structures = _decode_output(
        catalog,
        service,
        projection,
        outputs["structure_candidates"],
    )
    facts = _decode_output(
        catalog,
        service,
        projection,
        outputs["confidence_facts"],
    )
    materialized_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "materialize-confidence"
        and output["output_port"] == "observations"
    )
    observations = _decode_output(
        catalog,
        service,
        projection,
        materialized_output,
    )
    assert len(structures.items) == 2
    assert len(set(item.candidate_id for item in structures.items)) == 2
    assert [
        item.metadata["sample_index"] for item in structures.items
    ] == [0, 1]
    assert all(len(item.parent_ids) == 1 for item in structures.items)
    assert len(facts.entries) == 2
    assert {
        fact.plddt_per_residue for fact in facts.entries
    } == {(0.71, 0.83), (71.0, 83.0)}
    facts_by_key = {fact.prediction_key: fact for fact in facts.entries}
    assert [
        facts_by_key[item.metadata["prediction_key"]].plddt_per_residue
        for item in structures.items
    ] == [(0.71, 0.83), (71.0, 83.0)]
    assert all(fact.ptm is None and fact.pae is None for fact in facts.entries)
    assert {
        item.metadata["prediction_key"] for item in structures.items
    } == {fact.prediction_key for fact in facts.entries}
    assert len({fact.prediction_key for fact in facts.entries}) == 2
    assert all(
        fact.prediction_axis == facts.entries[0].prediction_axis
        for fact in facts.entries
    )
    assert {
        (entry.metric.contract_id, entry.value)
        for entry in observations.entries
    } == {
        ("structure.plddt.per_residue", (0.71, 0.83)),
        ("structure.plddt.mean_residue", 0.77),
        ("structure.plddt.per_residue", (71.0, 83.0)),
        ("structure.plddt.mean_residue", 77.0),
    }
    assert len(observations.entries) == 4
    assert {entry.candidate_id for entry in observations.entries} == {
        item.candidate_id for item in structures.items
    }
    assert all(
        entry.residue_axis is not None
        and entry.residue_axis.layout.residue_ids == ("A:1", "A:2")
        for entry in observations.entries
    )
    assert len(client.calls) == 1
    assert client.calls[0]["num_steps"] == 10
    assert client.calls[0]["num_samples"] == 2
    assert not client.calls[0]["staging_directory"].exists()
    readiness_index = next(
        index
        for index, event in enumerate(events)
        if event["event"]["type"] == "readiness_attested"
        and event["event"]["binding"]["contract_id"]
        == "folding.fold.simplefold_local"
    )
    binding = catalog.require_contract(
        "binding",
        "folding.fold.simplefold_local",
        _SIMPLEFOLD_BINDING_VERSION,
    )
    method = catalog.require_contract(
        "method",
        binding.descriptor["method"]["contract_id"],
        binding.descriptor["method"]["contract_version"],
    )
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "fold_parent_0"
    ]
    invocation_index = next(
        index
        for index, event in enumerate(events)
        if event["event"] in started
    )
    assert readiness_index < invocation_index
    terminal = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"]
        in {item["invocation_id"] for item in started}
    ]
    assert len(started) == len(terminal) == 1
    assert terminal[0]["status"] == "succeeded"
    assert started[0]["engine_identity"] == method.contract_digest
    assert started[0]["invocation_provenance"] == {
        "effective_randomness": {
            "control": "exact_seed",
            "effective_seed": structures.items[0].metadata[
                "effective_call_seed"
            ],
        }
    }
    assert {
        "provider",
        "model",
        "route",
        "runtime_fingerprint",
        "checkpoint",
        "seed_control",
    }.isdisjoint(structures.items[0].metadata)


def test_simplefold_translates_provider_pdb_tail_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_pdb = _upstream_simplefold_serialized_pdb()
    assert provider_pdb.endswith(" " * 80)
    assert not provider_pdb.endswith("\n")

    class Client:
        def fold(
            self,
            **_kwargs: Any,
        ) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            return (
                [ProteinStructure(provider_pdb)],
                [{"per_residue": [71.0, 83.0], "sample_index": 0}],
            )

    catalog, service, projection, events = _run_simplefold(
        tmp_path,
        monkeypatch,
        client=Client(),
        num_samples=1,
    )

    assert projection["status"] == "succeeded", json.dumps(events, indent=2)
    structure_output = next(
        output
        for output in projection["outputs"]
        if output["node_id"] == "fold"
        and output["output_port"] == "structure_candidates"
    )
    structures = _decode_output(
        catalog,
        service,
        projection,
        structure_output,
    )
    published_pdb = structures.items[0].data.pdb_string
    assert published_pdb == "\n".join(provider_pdb.splitlines()[:-1]) + "\n"
    assert published_pdb.splitlines()[-1][:6].strip() == "END"


def test_simplefold_does_not_discard_an_undocumented_provider_tail() -> None:
    from modules.folding.simplefold_adapter import _translate_provider_structure

    provider_pdb = _upstream_simplefold_serialized_pdb()
    with pytest.raises(ValueError, match="padded sentinel"):
        _translate_provider_structure(
            ProteinStructure(provider_pdb.removesuffix(" " * 80) + "trailer")
        )


def test_simplefold_admits_provider_pdb_without_rebuilding_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.folding.simplefold_adapter import LocalSimpleFoldAdapter

    class Client:
        def fold(
            self,
            **_kwargs: Any,
        ) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            return (
                [
                    ProteinStructure(
                        _upstream_simplefold_serialized_pdb(
                            _trusted_serialized_pdb_with_independent_residue_names()
                        )
                    )
                ],
                [{"per_residue": [71.0, 83.0], "sample_index": 0}],
            )

    class Resources:
        @staticmethod
        @contextmanager
        def local_provider(provider_id: str):
            assert provider_id == "simplefold-folding"
            yield {}

        @contextmanager
        def temporary_directory(self, *, prefix: str):
            staging = tmp_path / prefix
            staging.mkdir()
            yield staging

        @contextmanager
        def engine_invocation(self, **_kwargs: Any):
            yield

    result = LocalSimpleFoldAdapter(
        environment=_simplefold_environment(
            tmp_path / "environment",
            monkeypatch,
            Client(),
        ),
        resources=Resources(),
    ).fold(
        sequence=ProteinSequence("AG", ("Q:-2A", "Q:10")),
        num_steps=10,
        num_samples=1,
        derived_call_seed=1603,
        engine_role="fold_parent_0",
    )

    assert result.samples[0].structure == ProteinStructure(
        "\n".join(
            line.ljust(80)
            for line in (
                _trusted_serialized_pdb_with_independent_residue_names().splitlines()
            )
        )
        + "\n"
    )


def test_canonical_simplefold_operation_consumes_normalized_adapter_dto() -> None:
    from modules.folding.implementation import (
        SimpleFoldFoldingImplementation,
    )
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.folding.simplefold_adapter import (
        SimpleFoldAdapterResult,
        SimpleFoldSampleResult,
    )
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )
    from core.operation import OutputIdentityIntent
    from datatypes.prediction import PendingConfidenceFactCollection

    class Adapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def fold(self, **kwargs: Any) -> SimpleFoldAdapterResult:
            self.calls.append(kwargs)
            return SimpleFoldAdapterResult(
                samples=(
                    SimpleFoldSampleResult(
                        sample_index=0,
                        structure=ProteinStructure(
                            _two_residue_pdb(),
                        ),
                        per_residue_plddt=(71.0, 83.0),
                    ),
                ),
                effective_call_seed=kwargs["derived_call_seed"],
            )

    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    context = operation_context(
        catalog,
        "folding.fold.simplefold_local",
        object(),
        binding_version=_SIMPLEFOLD_BINDING_VERSION,
        environment={"native_scores": object()},
    )
    adapter = Adapter()
    operation = SimpleFoldFoldingImplementation(
        adapter=adapter,
        method=context.method,
    )
    parent = Candidate(
        "parent",
        ProteinSequence("AG"),
        [],
        {},
    )

    outputs = operation.execute(
        operation_call(
            catalog=catalog,
            binding_id="folding.fold.simplefold_local",
            binding_version=_SIMPLEFOLD_BINDING_VERSION,
            inputs={
                "sequence_candidates": CandidateCollection(
                    "parents",
                    "protein.sequence",
                    [parent],
                )
            },
            node_parameters={"num_samples": 1},
            binding_parameters={"num_steps": 10},
            effective_randomness={"effective_seed": 1603},
        )
    )

    structures = outputs["structure_candidates"]
    intent = outputs["confidence_facts"]
    assert type(structures) is CandidateCollection
    assert type(intent) is OutputIdentityIntent
    facts = intent.relation
    assert type(facts) is PendingConfidenceFactCollection
    assert {
        "provider",
        "model",
        "route",
        "runtime_fingerprint",
        "checkpoint",
        "seed_control",
    }.isdisjoint(structures.items[0].metadata)
    assert len(facts.entries) == 1
    fact = facts.entries[0]
    assert fact.plddt_per_residue == (71.0, 83.0)
    assert fact.ptm is None
    assert fact.pae is None
    assert fact.prediction_axis.sequence.sequence == "AG"
    assert fact.prediction_axis.sequence.residue_ids == ("A:1", "A:2")
    assert fact.prediction_axis.layout.residue_ids == ("A:1", "A:2")
    assert facts.observation_method == context.method
    assert "prediction_key" not in structures.items[0].metadata
    assert set(outputs) == {"structure_candidates", "confidence_facts"}
    assert adapter.calls == [
        {
            "sequence": parent.data,
            "num_steps": 10,
            "num_samples": 1,
            "derived_call_seed": structures.items[0].metadata[
                "effective_call_seed"
            ],
            "engine_role": "fold_parent_0",
        }
    ]


def test_simplefold_call_seed_uses_candidate_content_not_candidate_identity(
) -> None:
    from modules.folding.implementation import SimpleFoldFoldingImplementation
    from modules.folding.package import MODULE_PACKAGE as FOLDING_PACKAGE
    from modules.folding.simplefold_adapter import (
        SimpleFoldAdapterResult,
        SimpleFoldSampleResult,
    )
    from modules.structure_prediction.package import (
        MODULE_PACKAGE as STRUCTURE_PREDICTION_PACKAGE,
    )
    from modules.structure_transform.package import (
        MODULE_PACKAGE as STRUCTURE_TRANSFORM_PACKAGE,
    )

    class Adapter:
        def __init__(self) -> None:
            self.seeds: list[int] = []

        def fold(self, **kwargs: Any) -> SimpleFoldAdapterResult:
            seed = kwargs["derived_call_seed"]
            self.seeds.append(seed)
            return SimpleFoldAdapterResult(
                samples=(
                    SimpleFoldSampleResult(
                        sample_index=0,
                        structure=ProteinStructure(_two_residue_pdb()),
                        per_residue_plddt=(71.0, 83.0),
                    ),
                ),
                effective_call_seed=seed,
            )

    catalog = build_frozen_catalog(
        (
            FOLDING_PACKAGE,
            STRUCTURE_PREDICTION_PACKAGE,
            STRUCTURE_TRANSFORM_PACKAGE,
        )
    )
    context = operation_context(
        catalog,
        "folding.fold.simplefold_local",
        object(),
        binding_version=_SIMPLEFOLD_BINDING_VERSION,
    )

    def observed(candidate_id: str, sequence: str) -> int:
        adapter = Adapter()
        operation = SimpleFoldFoldingImplementation(
            adapter=adapter,
            method=context.method,
        )
        parent = Candidate(candidate_id, ProteinSequence(sequence), [], {})
        operation.execute(
            operation_call(
                catalog=catalog,
                binding_id="folding.fold.simplefold_local",
                binding_version=_SIMPLEFOLD_BINDING_VERSION,
                inputs={
                    "sequence_candidates": CandidateCollection(
                        "parents",
                        "protein.sequence",
                        [parent],
                    )
                },
                node_parameters={"num_samples": 1},
                binding_parameters={"num_steps": 10},
                effective_randomness={"effective_seed": 1603},
            )
        )
        return adapter.seeds[0]

    original = observed("candidate-a", "AG")
    renamed = observed("candidate-renamed", "AG")
    changed_content = observed("candidate-a", "AA")

    assert original == renamed
    assert original != changed_content


def test_concurrent_runs_use_disjoint_live_staging_and_stable_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = threading.Barrier(2)

    class Client:
        def __init__(self) -> None:
            self.staging: list[Path] = []
            self.lock = threading.Lock()

        def fold(
            self,
            **kwargs: Any,
        ) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            staging = kwargs["staging_directory"]
            owned = staging / "fixed-provider-name"
            assert not owned.exists()
            owned.write_text("owned")
            with self.lock:
                self.staging.append(staging)
            barrier.wait(timeout=5)
            assert owned.read_text() == "owned"
            return (
                [ProteinStructure(_upstream_simplefold_serialized_pdb())],
                [{"per_residue": [71.0, 83.0], "sample_index": 0}],
            )

    client = Client()
    environment_values = _simplefold_environment(
        tmp_path,
        monkeypatch,
        client,
    )
    for root_name in ("projects", "cache", "outputs", "runs"):
        (tmp_path / root_name).mkdir(exist_ok=True)

    def run(project_id: str) -> tuple[Any, dict[str, Any], Any]:
        return _run_simplefold(
            tmp_path,
            monkeypatch,
            client=client,
            num_samples=1,
            environment_values=environment_values,
            project_id=project_id,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(run, "simplefold-concurrent-a")
        second_future = executor.submit(run, "simplefold-concurrent-b")
        first_catalog, first_service, first_projection, _ = (
            first_future.result(timeout=20)
        )
        second_catalog, second_service, second_projection, _ = (
            second_future.result(timeout=20)
        )

    def candidate_id(
        catalog: Any,
        service: V2RunService,
        projection: dict[str, Any],
    ) -> str:
        output = next(
            item
            for item in projection["outputs"]
            if item["node_id"] == "fold"
            and item["output_port"] == "structure_candidates"
        )
        return _decode_output(
            catalog,
            service,
            projection,
            output,
        ).items[0].candidate_id

    assert first_projection["status"] == second_projection["status"] == "succeeded"
    assert candidate_id(
        first_catalog,
        first_service,
        first_projection,
    ) == candidate_id(
        second_catalog,
        second_service,
        second_projection,
    )
    assert len(client.staging) == 2
    assert client.staging[0] != client.staging[1]
    assert all(not path.exists() for path in client.staging)
