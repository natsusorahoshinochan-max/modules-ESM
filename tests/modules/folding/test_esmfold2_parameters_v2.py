"""Route-owned ESMFold2 inference parameters without loading local models."""

from core.parameters.contract import admit_values
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
