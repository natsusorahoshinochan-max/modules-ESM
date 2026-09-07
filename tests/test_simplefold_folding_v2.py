"""Public v2 contracts for the SimpleFold folding Binding."""

from __future__ import annotations

from core.catalog.authoring import AuthoringCapabilityProjection

import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from core.local_torch_device import (
    expected_local_torch_device,
)
from tests.support.local_torch_device import provider_free_cpu_device_policy
from tests.support.ledger import public_run_events, public_run_projection

from protein_workbench_public.bootstrap import module_registrations

pytestmark = pytest.mark.usefixtures("provider_free_cpu_device_policy")

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
)


def test_folding_package_import_does_not_require_optional_torch(
) -> None:
    """Base installs reach Availability without importing optional Torch."""
    script = """
import importlib.abc
import sys

class BlockTorch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "torch" or fullname.startswith("torch."):
            raise ModuleNotFoundError("No module named 'torch'", name="torch")
        return None

sys.meta_path.insert(0, BlockTorch())
sys.path.insert(0, sys.argv[1])
from modules.folding.package import MODULE_PACKAGE
assert MODULE_PACKAGE.package_id == "folding"
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            script,
            str(Path(__file__).resolve().parents[1]),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


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
    }
    provider_directory = tmp_path / "simplefold"
    provider_directory.mkdir()
    modules["simplefold"].__file__ = str(
        provider_directory / "__init__.py"
    )
    modules["simplefold"].wrapper = modules["simplefold.wrapper"]
    modules["simplefold.wrapper"].InferenceWrapper = InferenceWrapper
    modules["simplefold.wrapper"].esm_registry = {
        "esm2_3B": lambda: (object(), object())
    }
    modules["simplefold.utils.boltz_utils"].process_structure = object()
    modules["simplefold.utils.boltz_utils"].to_pdb = object()
    modules["simplefold.utils.fasta_utils"].process_fastas = (
        lambda **_kwargs: None
    )
    modules[
        "simplefold.utils.datamodule_utils"
    ].process_one_inference_structure = object()
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    model_root = tmp_path / "model"
    esm2_source_root = tmp_path / "esm2-source"
    esm2_model_root = tmp_path / "esm2-model"
    for root in (model_root, esm2_source_root, esm2_model_root):
        root.mkdir()
    (model_root / "ccd.pkl").write_bytes(b"reviewed-ccd")

    original_cwd = os.getcwd()
    original_path = tuple(sys.path)
    prefixes = ("utils", "model", "processor", "boltz_data_pipeline")
    original_bare_modules = {
        module_name: module
        for module_name, module in sys.modules.items()
        if any(
            module_name == prefix
            or module_name.startswith(f"{prefix}.")
            for prefix in prefixes
        )
    }
    with pytest.raises(StopAfterInferenceConstruction):
        simplefold_runtime.activate_fold_sequence(
            ProteinSequence("AG", ("A:1", "A:2")),
            num_steps=75,
            num_samples=1,
            staging_directory=tmp_path / "project",
            effective_seed=1603,
            staged_model_root=model_root,
            staged_esm2_source_root=esm2_source_root,
            staged_esm2_model_root=esm2_model_root,
            device="cpu",
        )

    assert captured == {"num_steps": 75}
    assert os.getcwd() == original_cwd
    assert tuple(sys.path) == original_path
    restored_bare_modules = {
        module_name: module
        for module_name, module in sys.modules.items()
        if any(
            module_name == prefix
            or module_name.startswith(f"{prefix}.")
            for prefix in prefixes
        )
    }
    assert restored_bare_modules == original_bare_modules
    assert all(
        restored_bare_modules[module_name] is module
        for module_name, module in original_bare_modules.items()
    )


def test_cached_simplefold_folding_activation_restores_its_loader_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import ModuleType

    import modules.folding.simplefold_runtime as simplefold_runtime

    observed_loaders: list[object] = []

    def original_loader() -> tuple[object, object]:
        return object(), object()

    registry: dict[str, object] = {"esm2_3B": original_loader}

    class InferenceWrapper:
        def __init__(self, **_kwargs: Any) -> None:
            observed_loaders.append(registry["esm2_3B"])

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
    }
    provider_directory = tmp_path / "simplefold"
    provider_directory.mkdir()
    modules["simplefold"].__file__ = str(
        provider_directory / "__init__.py"
    )
    modules["simplefold"].wrapper = modules["simplefold.wrapper"]
    modules["simplefold.wrapper"].InferenceWrapper = InferenceWrapper
    modules["simplefold.wrapper"].esm_registry = registry
    modules["simplefold.utils.boltz_utils"].process_structure = object()
    modules["simplefold.utils.boltz_utils"].to_pdb = object()
    modules["simplefold.utils.fasta_utils"].process_fastas = (
        lambda **_kwargs: None
    )
    modules[
        "simplefold.utils.datamodule_utils"
    ].process_one_inference_structure = object()
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "utils.esm_utils", raising=False)

    model_root = tmp_path / "model"
    esm2_source_root = tmp_path / "esm2-source"
    esm2_model_root = tmp_path / "esm2-model"
    for root in (model_root, esm2_source_root, esm2_model_root):
        root.mkdir()

    prior_mappings = ({"esm2_3B": original_loader}, {})
    for call_index, prior_mapping in enumerate(prior_mappings):
        registry.clear()
        registry.update(prior_mapping)
        simplefold_runtime.activate_fold_sequence(
            ProteinSequence("AG", ("A:1", "A:2")),
            num_steps=50,
            num_samples=1,
            staging_directory=tmp_path / f"project-{call_index}",
            effective_seed=1603,
            staged_model_root=model_root,
            staged_esm2_source_root=esm2_source_root,
            staged_esm2_model_root=esm2_model_root,
            device="cpu",
        )
        assert registry == prior_mapping
        if "esm2_3B" in prior_mapping:
            assert registry["esm2_3B"] is original_loader

    assert len(observed_loaders) == 2
    assert all(loader is not original_loader for loader in observed_loaders)


def test_simplefold_folding_activation_restores_process_import_state(
    tmp_path: Path,
) -> None:
    provider_root = tmp_path / "provider"
    package_root = provider_root / "simplefold"
    utils_root = package_root / "utils"
    utils_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("")
    (utils_root / "__init__.py").write_text("")
    (package_root / "wrapper.py").write_text(
        "from utils.esm_utils import esm_registry\n"
        "class InferenceWrapper:\n"
        "    def __init__(self, **kwargs):\n"
        "        pass\n"
    )
    (utils_root / "esm_utils.py").write_text(
        "def original_loader():\n"
        "    return object(), object()\n"
        "esm_registry = {'esm2_3B': original_loader}\n"
    )
    (utils_root / "boltz_utils.py").write_text(
        "process_structure = object()\n"
        "to_pdb = object()\n"
    )
    (utils_root / "fasta_utils.py").write_text(
        "def process_fastas(**kwargs):\n"
        "    pass\n"
    )
    (utils_root / "datamodule_utils.py").write_text(
        "process_one_inference_structure = object()\n"
    )
    model_root = tmp_path / "model"
    esm2_source_root = tmp_path / "esm2-source"
    esm2_model_root = tmp_path / "esm2-model"
    for root in (model_root, esm2_source_root, esm2_model_root):
        root.mkdir()

    script = """
import os
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])

from datatypes.sequence import ProteinSequence
from modules.folding.simplefold_runtime import activate_fold_sequence

prefixes = ("utils", "model", "processor", "boltz_data_pipeline")
def is_bare(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)

original_cwd = os.getcwd()
original_path = tuple(sys.path)
assert not any(is_bare(name) for name in sys.modules)

activate_fold_sequence(
    ProteinSequence("AG", ("A:1", "A:2")),
    num_steps=50,
    num_samples=1,
    staging_directory=Path(sys.argv[3]),
    effective_seed=1603,
    staged_model_root=Path(sys.argv[4]),
    staged_esm2_source_root=Path(sys.argv[5]),
    staged_esm2_model_root=Path(sys.argv[6]),
    device="cpu",
)

assert os.getcwd() == original_cwd
assert tuple(sys.path) == original_path
assert not any(is_bare(name) for name in sys.modules)
from simplefold import wrapper
assert wrapper.esm_registry["esm2_3B"].__name__ == "original_loader"
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            script,
            str(Path(__file__).resolve().parents[1]),
            str(provider_root),
            str(tmp_path / "staging"),
            str(model_root),
            str(esm2_source_root),
            str(esm2_model_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_simplefold_final_model_activation_restores_process_import_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib
    import os
    from types import ModuleType

    import modules.folding.simplefold_runtime as simplefold_runtime

    provider_directory = tmp_path / "simplefold"
    model_package = provider_directory / "model"
    model_package.mkdir(parents=True)
    (model_package / "__init__.py").write_text("")
    (model_package / "provider_model.py").write_text("value = 1\n")
    simplefold_module = ModuleType("simplefold")
    simplefold_module.__file__ = str(provider_directory / "__init__.py")
    monkeypatch.setitem(sys.modules, "simplefold", simplefold_module)
    for module_name in tuple(sys.modules):
        if module_name == "model" or module_name.startswith("model."):
            monkeypatch.delitem(sys.modules, module_name)

    def load_models(
        model_directory: Path,
        device: object,
    ) -> tuple[object, dict[str, object]]:
        assert model_directory == tmp_path / "models"
        assert device == "device"
        assert Path.cwd() == provider_directory
        assert str(provider_directory) in sys.path
        assert importlib.import_module("model.provider_model").value == 1
        return "folding", {"plddt": "models"}

    monkeypatch.setattr(
        simplefold_runtime,
        "_load_reviewed_folding_models",
        load_models,
    )
    original_cwd = os.getcwd()
    original_path = tuple(sys.path)
    activated = simplefold_runtime.ActivatedSimpleFoldFolding(
        provider_directory=provider_directory,
        model_directory=tmp_path / "models",
        output_directory=tmp_path / "output",
        inference_wrapper=object(),
        process_one_inference_structure=lambda: None,
        torch_device="device",
        torch_module=object(),
        effective_seed=1603,
        num_samples=1,
        process_structure=lambda: None,
        to_pdb=lambda: "",
    )

    activated.activate_final_models()

    assert activated.folding_model == "folding"
    assert activated.plddt_models == {"plddt": "models"}
    assert os.getcwd() == original_cwd
    assert tuple(sys.path) == original_path
    assert "model" not in sys.modules
    assert "model.provider_model" not in sys.modules


@pytest.mark.parametrize("raise_during_scope", [False, True])
def test_simplefold_scope_restores_preexisting_bare_modules_by_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raise_during_scope: bool,
) -> None:
    import importlib
    import os
    from types import ModuleType

    import modules.folding.simplefold_runtime as simplefold_runtime

    provider_directory = tmp_path / "simplefold"
    provider_utils = provider_directory / "utils"
    provider_utils.mkdir(parents=True)
    (provider_utils / "__init__.py").write_text("")
    (provider_utils / "provider_module.py").write_text("value = 1\n")
    simplefold_module = ModuleType("simplefold")
    simplefold_module.__file__ = str(provider_directory / "__init__.py")
    prior_utils = ModuleType("utils")
    prior_utils_child = ModuleType("utils.preexisting")
    monkeypatch.setitem(sys.modules, "simplefold", simplefold_module)
    monkeypatch.setitem(sys.modules, "utils", prior_utils)
    monkeypatch.setitem(sys.modules, "utils.preexisting", prior_utils_child)
    original_cwd = os.getcwd()
    original_path = tuple(sys.path)

    def enter_scope() -> None:
        with simplefold_runtime._simplefold_activation_scope():
            assert importlib.import_module("utils.provider_module").value == 1
            if raise_during_scope:
                raise RuntimeError("activation failed")

    if raise_during_scope:
        with pytest.raises(RuntimeError, match="activation failed"):
            enter_scope()
    else:
        enter_scope()

    assert os.getcwd() == original_cwd
    assert tuple(sys.path) == original_path
    assert sys.modules["utils"] is prior_utils
    assert sys.modules["utils.preexisting"] is prior_utils_child
    assert "utils.provider_module" not in sys.modules


def test_simplefold_releases_esm2_before_loading_folding_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            assert lifecycle["features_prepared"] is True
            assert lifecycle["language_model_released"] is True
            raise StopAfterStagedModelLoad

    loaded_checkpoints: list[tuple[str, dict[str, Any]]] = []
    loaded_configs: list[str] = []
    loaded_modules: list[dict[str, Any]] = []

    def load_checkpoint(
        path: Path,
        **kwargs: Any,
    ) -> dict[str, str]:
        assert lifecycle["request_processed"] is True
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
        lifecycle["request_processed"] = True
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
        "hydra": ModuleType("hydra"),
        "omegaconf": ModuleType("omegaconf"),
    }

    class HydraUtils:
        instantiate = staticmethod(lambda _config: None)

    class OmegaConf:
        load = staticmethod(lambda _path: None)

    modules["hydra"].utils = HydraUtils
    modules["omegaconf"].OmegaConf = OmegaConf
    provider_directory = tmp_path / "simplefold"
    provider_directory.mkdir()
    modules["simplefold"].__file__ = str(
        provider_directory / "__init__.py"
    )
    modules["simplefold"].wrapper = modules["simplefold.wrapper"]
    modules["simplefold.wrapper"].InferenceWrapper = InferenceWrapper
    modules["simplefold.wrapper"].esm_registry = {
        "esm2_3B": lambda: (object(), object())
    }
    modules["simplefold.utils.boltz_utils"].process_structure = object()
    modules["simplefold.utils.boltz_utils"].to_pdb = object()
    modules["simplefold.utils.fasta_utils"].process_fastas = process_fastas
    modules[
        "simplefold.utils.datamodule_utils"
    ].process_one_inference_structure = process_one_inference_structure
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    import hydra
    import omegaconf

    import torch

    monkeypatch.setattr(torch, "load", load_checkpoint)
    monkeypatch.setattr(omegaconf.OmegaConf, "load", load_config)
    monkeypatch.setattr(hydra.utils, "instantiate", instantiate)
    model_root = tmp_path / "model"
    esm2_source_root = tmp_path / "esm2-source"
    esm2_model_root = tmp_path / "esm2-model"
    for root in (model_root, esm2_source_root, esm2_model_root):
        root.mkdir()
    (model_root / "ccd.pkl").write_bytes(b"reviewed-ccd")

    activated = simplefold_runtime.activate_fold_sequence(
        ProteinSequence("AG", ("A:1", "A:2")),
        num_steps=50,
        num_samples=1,
        staging_directory=tmp_path / "project",
        effective_seed=1603,
        staged_model_root=model_root,
        staged_esm2_source_root=esm2_source_root,
        staged_esm2_model_root=esm2_model_root,
        device="cpu",
    )
    assert lifecycle == {"request_processed": True}
    assert loaded_checkpoints == []

    activated.prepare_inputs()
    assert lifecycle == {
        "request_processed": True,
        "features_prepared": True,
        "language_model_released": True,
    }
    assert loaded_checkpoints == []

    activated.activate_final_models()

    with pytest.raises(StopAfterStagedModelLoad):
        activated.invoke()

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
        "folding.fold.simplefold_local")
    esmfold2 = catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local")
    assert simplefold.descriptor["node_type"] == esmfold2.descriptor["node_type"]
    assert simplefold.descriptor["execution_route"] == "adapter"
    assert simplefold.descriptor["route_behavior"]["parameters"][
        "staging"
    ] == "one-private-directory-per-adapter-call"
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
    assert simplefold.descriptor["produced_observations"] == ()

    method_reference = simplefold.descriptor["method"]
    method = catalog.require_contract(
        method_reference["contract_kind"],
        method_reference["contract_id"])
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
    (environment["model_root"] / "simplefold_100M.ckpt").unlink()
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
        "folding.fold.esmfold2_remote")
    assert catalog.require_contract(
        "binding",
        "folding.fold.esmfold2_local")
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
    from tests.support.runtime_results import decode_service_typed_output_value

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
    import modules.folding.simplefold_contract as contract
    import modules.folding.simplefold_runtime as simplefold_runtime

    class FixtureActivatedFold:
        def __init__(self, kwargs: dict[str, Any]) -> None:
            self._kwargs = kwargs

        def prepare_inputs(self) -> None:
            pass

        def activate_final_models(self) -> None:
            pass

        def invoke(self) -> Any:
            return client.fold(
                sequence=self._kwargs["sequence"],
                num_steps=self._kwargs["num_steps"],
                num_samples=self._kwargs["num_samples"],
                effective_seed=self._kwargs["effective_seed"],
                staging_directory=self._kwargs["staging_directory"],
                device=self._kwargs["device"],
            )

    def fixture_activate_fold_sequence(**kwargs: Any) -> Any:
        return FixtureActivatedFold(kwargs)

    monkeypatch.setattr(
        simplefold_runtime,
        "activate_fold_sequence",
        fixture_activate_fold_sequence,
    )
    model_root = tmp_path / "models"
    esm2_model_root = tmp_path / "esm2-models"
    esm2_source_root = tmp_path / "esm2-source"
    model_root.mkdir(parents=True)
    esm2_model_root.mkdir()
    (esm2_source_root / "esm").mkdir(parents=True)
    (esm2_source_root / "esm" / "__init__.py").write_bytes(b"fixture")
    (esm2_source_root / "esm" / "pretrained.py").write_bytes(b"fixture")
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
    fixture_closure = build_fixture_simplefold_closure(
        contract.SIMPLEFOLD_FOLDING_ASSET_CLOSURE,
    )
    monkeypatch.setattr(
        contract,
        "SIMPLEFOLD_FOLDING_ASSET_CLOSURE",
        fixture_closure,
    )
    return {
        "model_root": model_root,
        "esm2_model_root": esm2_model_root,
        "esm2_source_root": esm2_source_root,
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
        binding_id="contract_test.folding_sequence_source.direct",
        node_parameters={"sequence": "AG"},
        binding_parameters={},
    )
    fold = WorkflowNodeInstance(
        node_id="fold",
        node_type_id="folding.fold",
        binding_id="folding.fold.simplefold_local",
        node_parameters={
            "effective_seed": 1603,
            "num_samples": num_samples,
        },
        binding_parameters={"num_steps": 10},
    )
    materialize = WorkflowNodeInstance(
        node_id="materialize-confidence",
        node_type_id="structure_prediction.materialize_confidence",
        binding_id="structure_prediction.materialize_confidence.direct",
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
        ))
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
            "folding.fold.simplefold_local": environment_values
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


def test_simplefold_activation_failure_records_zero_engine_invocations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.simplefold_runtime as simplefold_runtime

    class Client:
        def fold(
            self,
            **_kwargs: Any,
        ) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            return (
                [ProteinStructure(_upstream_simplefold_serialized_pdb())],
                [{"per_residue": [71.0, 83.0], "sample_index": 0}],
            )

    environment = _simplefold_environment(
        tmp_path,
        monkeypatch,
        Client(),
    )

    def fail_activation(**_kwargs: Any) -> object:
        raise RuntimeError("fixture SimpleFold activation failed")

    monkeypatch.setattr(
        simplefold_runtime,
        "activate_fold_sequence",
        fail_activation,
        raising=False,
    )

    _, _, projection, events = _run_simplefold(
        tmp_path,
        monkeypatch,
        client=Client(),
        num_samples=1,
        environment_values=environment,
    )

    assert projection["status"] == "failed"
    assert not any(
        event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"].startswith("fold_parent_0")
        for event in events
    )


def test_simplefold_esm2_failure_is_recorded_before_final_engine_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.folding.simplefold_runtime as simplefold_runtime

    class Client:
        def fold(self, **_kwargs: Any) -> object:
            raise AssertionError("final SimpleFold engine must not run")

    environment = _simplefold_environment(
        tmp_path,
        monkeypatch,
        Client(),
    )

    class FailingFeatureEngine:
        def prepare_inputs(self) -> None:
            raise RuntimeError("fixture ESM2 feature failure")

        def activate_final_models(self) -> None:
            raise AssertionError("final models must not load")

        def invoke(self) -> object:
            raise AssertionError("final SimpleFold engine must not run")

    monkeypatch.setattr(
        simplefold_runtime,
        "activate_fold_sequence",
        lambda **_kwargs: FailingFeatureEngine(),
    )

    _, _, projection, events = _run_simplefold(
        tmp_path,
        monkeypatch,
        client=Client(),
        num_samples=1,
        environment_values=environment,
    )

    assert projection["status"] == "failed"
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"].startswith("fold_parent_0")
    ]
    assert [event["engine_role"] for event in started] == [
        "fold_parent_0_esm2_features"
    ]
    terminal = next(
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_terminal"
        and event["event"]["invocation_id"] == started[0]["invocation_id"]
    )
    assert terminal["status"] == "failed"


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
        "folding.fold.simplefold_local")
    method = catalog.require_contract(
        "method",
        binding.descriptor["method"]["contract_id"])
    started = [
        event["event"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"] == "fold_parent_0"
    ]
    assert [
        event["event"]["engine_role"]
        for event in events
        if event["event"]["type"] == "engine_invocation_started"
        and event["event"]["engine_role"].startswith("fold_parent_0")
    ] == ["fold_parent_0_esm2_features", "fold_parent_0"]
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
    assert started[0]["engine_identity"] == method.contract_id
    assert started[0]["invocation_provenance"] == {
        "effective_randomness": {
            "control": "exact_seed",
            "effective_seed": structures.items[0].metadata[
                "effective_call_seed"
            ],
        },
    }
    assert {
        "provider",
        "model",
        "route",
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
        def __init__(self) -> None:
            self.devices: list[str] = []

        def fold(
            self,
            **_kwargs: Any,
        ) -> tuple[list[ProteinStructure], list[dict[str, Any]]]:
            self.devices.append(_kwargs["device"])
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

    client = Client()
    environment = _simplefold_environment(
        tmp_path / "device-environment",
        monkeypatch,
        client,
    )
    result = LocalSimpleFoldAdapter(
        environment=environment,
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
    assert client.devices == [expected_local_torch_device()]


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
        object())

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
