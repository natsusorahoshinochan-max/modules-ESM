"""Parameter declarations and values cross one typed admission seam each."""

from __future__ import annotations

import pytest

from core.parameters.contract import (
    ParameterContractDefinitionError,
    ParameterValueAdmissionError,
    admit_declarations,
    admit_values,
)
from core.parameters.model import AdmittedParameterValues, ParameterContract


def test_parameter_contract_admits_defaults_and_submitted_values_once() -> None:
    contract = admit_declarations(
        {
            "count": {
                "parameter_scope": "scientific",
                "scientific_meaning": "Number of returned scientific samples.",
                "required": False,
                "default": 2,
                "value_contract": {"type": "integer", "minimum": 1},
            },
            "label": {
                "parameter_scope": "scientific",
                "scientific_meaning": "Exact scientific population label.",
                "required": True,
                "value_contract": {"type": "string", "minLength": 1},
            },
        },
        path="fixture.parameters",
    )

    admitted = admit_values(contract, {"label": "population-a"})

    assert isinstance(contract, ParameterContract)
    assert isinstance(admitted, AdmittedParameterValues)
    assert dict(admitted) == {"count": 2, "label": "population-a"}


def test_parameter_value_admission_reports_the_exact_contract_path() -> None:
    contract = admit_declarations(
        {
            "count": {
                "parameter_scope": "scientific",
                "scientific_meaning": "Number of returned scientific samples.",
                "required": True,
                "value_contract": {"type": "integer", "minimum": 1},
            },
        },
        path="fixture.parameters",
    )

    with pytest.raises(ParameterValueAdmissionError) as raised:
        admit_values(contract, {"count": 0})

    assert raised.value.code == "invalid_parameter"
    assert raised.value.path == ("count",)


def test_value_admission_is_the_only_owner_of_default_value_semantics() -> None:
    contract = admit_declarations(
        {
            "count": {
                "parameter_scope": "scientific",
                "scientific_meaning": "Number of returned scientific samples.",
                "default": 0,
                "value_contract": {"type": "integer", "minimum": 1},
            },
        },
        path="fixture.parameters",
    )

    with pytest.raises(ParameterValueAdmissionError) as raised:
        admit_values(contract, {})

    assert raised.value.code == "invalid_parameter"
    assert raised.value.path == ("count",)


def test_declaration_admission_owns_environment_field_classification() -> None:
    with pytest.raises(
        ParameterContractDefinitionError,
        match="Environment Configuration",
    ):
        admit_declarations(
            {
                "options": {
                    "parameter_scope": "scientific",
                    "scientific_meaning": "Scientific selection options.",
                    "value_contract": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "modelPath": {
                                "field_scope": "scientific",
                                "scientific_meaning": "Invalid environment field.",
                                "type": "string",
                            },
                        },
                    },
                },
            },
            path="fixture.parameters",
        )


@pytest.mark.parametrize(
    ("value_contract", "submitted", "expected_path"),
    (
        ({"type": "string", "enum": ["a", "b"]}, "c", ("value",)),
        ({"type": "number", "minimum": 0, "maximum": 1}, 2, ("value",)),
        (
            {
                "type": "array",
                "minItems": 2,
                "items": {"type": "integer"},
            },
            [1],
            ("value",),
        ),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["count"],
                "properties": {
                    "count": {
                        "field_scope": "scientific",
                        "scientific_meaning": "Scientific sample count.",
                        "type": "integer",
                        "minimum": 1,
                    },
                },
            },
            {"count": 0},
            ("value", "count"),
        ),
    ),
)
def test_value_admission_owns_range_enum_and_shape_semantics(
    value_contract: dict,
    submitted: object,
    expected_path: tuple[str | int, ...],
) -> None:
    contract = admit_declarations(
        {
            "value": {
                "parameter_scope": "scientific",
                "scientific_meaning": "Scientific fixture value.",
                "required": True,
                "value_contract": value_contract,
            },
        },
        path="fixture.parameters",
    )

    with pytest.raises(ParameterValueAdmissionError) as raised:
        admit_values(contract, {"value": submitted})

    assert raised.value.code == "invalid_parameter"
    assert raised.value.path == expected_path


@pytest.mark.parametrize(
    ("submitted", "expected_code", "expected_path"),
    (
        ({}, "required_parameter_missing", ("value",)),
        ({"value": 1, "extra": 2}, "unknown_parameter", ()),
    ),
)
def test_value_admission_owns_required_and_field_closure(
    submitted: dict,
    expected_code: str,
    expected_path: tuple[str | int, ...],
) -> None:
    contract = admit_declarations(
        {
            "value": {
                "parameter_scope": "scientific",
                "scientific_meaning": "Required scientific fixture value.",
                "required": True,
                "value_contract": {"type": "integer"},
            },
        },
        path="fixture.parameters",
    )

    with pytest.raises(ParameterValueAdmissionError) as raised:
        admit_values(contract, submitted)

    assert raised.value.code == expected_code
    assert raised.value.path == expected_path


def test_value_admission_returns_canonical_immutable_values() -> None:
    contract = admit_declarations(
        {
            "values": {
                "parameter_scope": "scientific",
                "scientific_meaning": "Ordered scientific fixture values.",
                "required": True,
                "value_contract": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
            },
        },
        path="fixture.parameters",
    )

    submitted = [1, 2]
    admitted = admit_values(contract, {"values": submitted})
    submitted.append(3)

    assert admitted["values"] == (1, 2)
