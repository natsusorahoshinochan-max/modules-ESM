"""Single I-JSON owner and pure immutable representation behavior."""

import pytest

from datatypes.i_json import (
    admit_i_json,
    canonical_json_bytes,
    freeze_i_json,
    i_json_values_equal,
    thaw_i_json,
    validate_i_json,
)


@pytest.mark.parametrize(
    "value",
    [
        -(2**53), 2**53, float("nan"), float("inf"), -float("inf"),
        -0.0, "\ud800", {"\udfff": 1}, {1: "value"}, object(),
    ],
)
def test_raw_json_admission_rejects_outside_value_domain(value: object) -> None:
    with pytest.raises(ValueError, match="I-JSON|object key"):
        admit_i_json(value)


def test_admission_preserves_json_types_and_immutable_snapshot() -> None:
    raw = {"array": [True, 1, 1.0, None], "limits": (-(2**53 - 1), 2**53 - 1)}
    admitted = admit_i_json(raw)
    raw["array"].append("later")
    assert thaw_i_json(admitted) == {
        "array": [True, 1, 1.0, None], "limits": [-(2**53 - 1), 2**53 - 1],
    }
    with pytest.raises(TypeError):
        admitted["new"] = 1
    assert not i_json_values_equal(True, 1)
    assert not i_json_values_equal(1, 1.0)


def test_freeze_and_encoding_do_not_hide_domain_admission() -> None:
    frozen = freeze_i_json({"value": -0.0})
    assert canonical_json_bytes(frozen) == b'{"value":0}'
    with pytest.raises(ValueError, match="negative zero"):
        validate_i_json(frozen)


@pytest.mark.parametrize("value", [0.0, 1.25, -2.5])
def test_json_value_comparison_preserves_legal_float_equality(value: float) -> None:
    assert i_json_values_equal(value, value)
