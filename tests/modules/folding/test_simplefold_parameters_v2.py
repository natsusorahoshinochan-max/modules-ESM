"""SimpleFold sampling controls at the public Binding contract, without models."""

from core.parameters.contract import admit_values
from modules.folding.package import MODULE_PACKAGE


def test_simplefold_fold_admits_official_sampling_controls() -> None:
    bindings = {binding.binding_id: binding for binding in MODULE_PACKAGE.bindings}
    contract = bindings["folding.fold.simplefold_local"].parameter_contract

    # The pinned official CLI defaults to 500 steps; its README uses tau 0.01.
    # Neither the CLI nor the selected sampler imposes a 50-step ceiling.
    values = admit_values(contract, {"num_steps": 500, "tau": 0.01})
    assert dict(values) == {"num_steps": 500, "tau": 0.01}
    assert dict(admit_values(contract, {})) == {"num_steps": 500, "tau": 0.1}

    confidence = bindings[
        "folding.simplefold_confidence.simplefold_local"
    ].binding_parameters
    assert "tau" not in confidence
    assert "num_steps" not in confidence
