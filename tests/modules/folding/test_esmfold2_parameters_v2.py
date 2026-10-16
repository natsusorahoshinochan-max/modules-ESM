"""Route-owned ESMFold2 inference parameters without loading local models."""

from pathlib import Path
from typing import Any
import pytest

from core.parameters.contract import admit_values, ParameterValueAdmissionError
from modules.folding.package import MODULE_PACKAGE


def test_esmfold2_bindings_admit_route_specific_sampling_controls() -> None:
    bindings = {binding.binding_id: binding for binding in MODULE_PACKAGE.bindings}
    remote = admit_values(bindings["folding.fold.esmfold2_remote"].parameter_contract, {
        "num_sampling_steps": 37,
        "num_loops": 8,
        "lm_dropout": 0.2,
        "lm_mask_pct": 0.04,
        "msa_max_depth": None,
        "msa_column_mask_rate": 0.25,
    })
    assert dict(remote) == {
        "num_sampling_steps": 37,
        "num_loops": 8,
        "lm_dropout": 0.2,
        "lm_mask_pct": 0.04,
        "msa_max_depth": None,
        "msa_column_mask_rate": 0.25,
    }
    local = admit_values(bindings["folding.fold.esmfold2_local"].parameter_contract, {
        "num_sampling_steps": 250,
        "num_loops": 25,
        "lm_dropout": None,
        "lm_mask_pct": None,
        "msa_max_depth": None,
    })
    assert local["num_sampling_steps"] == 250
    assert local["num_loops"] == 25
    assert local["lm_dropout"] is None
    assert local["lm_mask_pct"] is None
    assert local["msa_max_depth"] is None


def test_remote_folding_config_forwards_all_controls_and_required_outputs() -> None:
    from modules.folding.esmfold2_remote import folding_config

    config = folding_config({
        "num_sampling_steps": 37, "num_loops": 8,
        "lm_dropout": 0.2, "lm_mask_pct": 0.04,
        "msa_max_depth": None, "msa_column_mask_rate": 0.25,
    })
    assert config.num_sampling_steps == 37
    assert config.num_loops == 8
    assert config.lm_dropout == 0.2
    assert config.lm_mask_pct == 0.04
    assert config.msa_max_depth is None
    assert config.msa_column_mask_rate == 0.25
    assert config.include_pae is True
    assert config.include_embeddings is False


def test_local_engine_forwards_controls_to_official_builder_without_model_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pickle
    from types import SimpleNamespace
    import esm.models.esmfold2 as sdk
    from transformers.models.esmfold2.configuration_esmfold2 import ESMFold2Config
    from transformers.models.esmfold2.modeling_esmfold2 import ESMFold2Model
    from modules.folding.esmfold2_local import LocalESMFold2Runtime, load_local_engine

    class ModelBoundary:
        def to(self, device: str) -> "ModelBoundary":
            assert device == "cpu"
            return self

        def eval(self) -> "ModelBoundary":
            return self

    observed: list[tuple[Any, dict[str, Any]]] = []
    result = object()

    class BuilderBoundary:
        def __init__(self, *, ccd_cache: Path) -> None:
            assert ccd_cache == tmp_path

        def fold(self, model: object, provider_input: Any, **kwargs: Any) -> object:
            assert isinstance(model, ModelBoundary)
            observed.append((provider_input, kwargs))
            return result

    (tmp_path / "ccd.pkl").write_bytes(pickle.dumps({}))
    monkeypatch.setattr(ESMFold2Config, "from_pretrained", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(ESMFold2Model, "from_pretrained", lambda *a, **k: ModelBoundary())
    monkeypatch.setattr(sdk, "ESMFold2InputBuilder", BuilderBoundary)
    engine = load_local_engine(LocalESMFold2Runtime(tmp_path, tmp_path, "cpu"))
    actual = engine.fold(sequence="AG", effective_seed=19, parameters={
        "num_sampling_steps": 250, "num_loops": 25,
        "lm_dropout": None, "lm_mask_pct": None,
        "msa_max_depth": None, "msa_column_mask_rate": 0.25,
    })
    assert actual is result
    provider_input, kwargs = observed[0]
    assert [(item.id, item.sequence) for item in provider_input.sequences] == [("A", "AG")]
    assert kwargs == {
        "num_sampling_steps": 250, "num_loops": 25,
        "lm_dropout": None, "lm_mask_pct": None,
        "msa_max_depth": None, "msa_column_mask_rate": 0.25,
        "num_diffusion_samples": 1, "seed": 19,
        "complex_id": "protein-workbench-fold",
    }


def test_remote_bounds_do_not_restrict_local_parameters() -> None:
    bindings = {binding.binding_id: binding for binding in MODULE_PACKAGE.bindings}
    remote = bindings["folding.fold.esmfold2_remote"].parameter_contract
    for values in ({"num_sampling_steps": 101}, {"num_loops": 21},
                   {"msa_max_depth": 16385}, {"lm_dropout": None}):
        with pytest.raises(ParameterValueAdmissionError):
            admit_values(remote, values)
    for route in ("remote", "local"):
        contract = bindings[f"folding.fold.esmfold2_{route}"].parameter_contract
        for values in ({"num_sampling_steps": 0}, {"num_loops": -1},
                       {"msa_max_depth": 0}, {"lm_dropout": 1.1},
                       {"lm_mask_pct": -0.1}, {"msa_column_mask_rate": 1.1}):
            with pytest.raises(ParameterValueAdmissionError):
                admit_values(contract, values)
        assert admit_values(contract, {"num_loops": 0})["num_loops"] == 0
    local = bindings["folding.fold.esmfold2_local"].parameter_contract
    assert admit_values(local, {})["num_sampling_steps"] == 200
    assert admit_values(local, {})["lm_mask_pct"] is None
    assert admit_values(local, {"msa_max_depth": 16385})["msa_max_depth"] == 16385
