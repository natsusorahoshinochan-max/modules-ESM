"""ESM3 Adapter parameter contracts without loading a local model."""

from modules.esm3.adapter import ESM3CallParameters, generation_config


def test_generation_config_transmits_explicit_sampling_exclusions_and_conditioning() -> None:
    parameters = ESM3CallParameters(
        num_steps=7,
        temperature=0.6,
        top_p=0.9,
        schedule="linear",
        strategy="entropy",
        temperature_annealing=False,
        invalid_ids=(5, 9),
        condition_on_coordinates_only=False,
    )

    config = generation_config("sequence", parameters)

    assert config.track == "sequence"
    assert list(config.invalid_ids) == [5, 9]
    assert config.condition_on_coordinates_only is False
    assert config.num_steps == 7
    assert config.temperature == 0.6
    assert config.top_p == 0.9
    assert config.schedule == "linear"
    assert config.strategy == "entropy"
    assert config.temperature_annealing is False


def test_binding_parameters_preserve_route_limits_and_independent_pair_settings() -> None:
    import pytest
    from core.parameters.contract import admit_values, ParameterValueAdmissionError
    from modules.esm3.package import MODULE_PACKAGE

    bindings = {binding.binding_id: binding for binding in MODULE_PACKAGE.bindings}
    remote = bindings["esm3.generate_paired.biohub_medium"].parameter_contract
    local = bindings["esm3.generate_paired.local_open"].parameter_contract
    submitted = {"sequence_num_steps": 7, "structure_num_steps": 30,
                 "sequence_temperature": 0.6, "structure_temperature": 12.0}
    admitted = admit_values(remote, submitted)
    assert admitted["sequence_num_steps"] == 7
    assert admitted["structure_num_steps"] == 30
    assert admitted["structure_temperature"] == 12.0
    assert admitted["sequence_invalid_ids"] == ()
    assert "effective_seed" not in admitted
    for invalid in ({"sequence_num_steps": 101}, {"structure_top_p": 0},
                    {"effective_seed": 9}):
        with pytest.raises(ParameterValueAdmissionError):
            admit_values(remote, invalid)
    local_admitted = admit_values(local, {
        "effective_seed": 9, "sequence_num_steps": 4096, "structure_top_p": 0,
    })
    assert local_admitted["sequence_num_steps"] == 4096
    assert local_admitted["structure_top_p"] == 0
    assert local_admitted["sequence_temperature"] == 1.0
