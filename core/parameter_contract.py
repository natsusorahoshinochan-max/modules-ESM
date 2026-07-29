"""Closed parameter-contract vocabulary shared by Catalog build and compiler."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


class ParameterContractDefinitionError(ValueError):
    """A Catalog parameter declaration is open or semantically unsafe."""


_SUPPORTED_VALUE_CONTRACT_KEYS = frozenset(
    {
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "items",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "oneOf",
        "pattern",
        "properties",
        "required",
        "type",
        "uniqueItems",
    }
)
_PARAMETER_METADATA_KEYS = frozenset(
    {
        "default",
        "description",
        "display_name",
        "group",
        "meaning",
        "required",
        "scientific_meaning",
        "summary",
        "title",
        "unit",
        "utility_transform",
        "value_contract",
    }
)
_ENVIRONMENT_TOKENS = frozenset(
    {
        "auth",
        "checkpoint",
        "credential",
        "credentials",
        "cuda",
        "deployment",
        "device",
        "endpoint",
        "environment",
        "gpu",
        "header",
        "model",
        "path",
        "provider",
        "runtime",
        "secret",
        "token",
        "url",
    }
)
_ENVIRONMENT_TOKEN_PAIRS = frozenset(
    {
        ("api", "key"),
        ("private", "key"),
    }
)


def parameter_name_tokens(name: str) -> tuple[str, ...]:
    """Normalize snake/kebab/dotted/camel/acronym names to semantic tokens."""
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", separated)
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", separated).strip("_").lower()
    return tuple(part for part in normalized.split("_") if part)


def is_environment_parameter_name(name: str) -> bool:
    """Return whether a field denotes runtime/model/environment selection."""
    tokens = parameter_name_tokens(name)
    if set(tokens).intersection(_ENVIRONMENT_TOKENS):
        return True
    return any(
        pair in _ENVIRONMENT_TOKEN_PAIRS
        for pair in zip(tokens, tokens[1:])
    )


def validate_parameter_declarations(
    declarations: Mapping[str, Any],
    *,
    path: str,
) -> None:
    """Fail closed unless declarations use the supported value vocabulary."""
    for name, declaration in declarations.items():
        declaration_path = f"{path}.{name}"
        if is_environment_parameter_name(name):
            raise ParameterContractDefinitionError(
                f"{declaration_path} declares Environment Configuration "
                "or model identity"
            )
        if not isinstance(declaration, Mapping):
            raise ParameterContractDefinitionError(
                f"{declaration_path} must be an object"
            )
        value_contract = declaration.get("value_contract")
        if value_contract is None:
            schema = {
                key: value
                for key, value in declaration.items()
                if key in _SUPPORTED_VALUE_CONTRACT_KEYS
            }
            allowed = (
                _SUPPORTED_VALUE_CONTRACT_KEYS
                | _PARAMETER_METADATA_KEYS
            )
        else:
            if not isinstance(value_contract, Mapping):
                raise ParameterContractDefinitionError(
                    f"{declaration_path}.value_contract must be an object"
                )
            schema = value_contract
            allowed = _PARAMETER_METADATA_KEYS
        unexpected = set(declaration) - allowed
        if unexpected:
            raise ParameterContractDefinitionError(
                f"{declaration_path} has unsupported fields "
                f"{sorted(unexpected)!r}"
            )
        _validate_value_contract_schema(
            schema,
            path=(
                f"{declaration_path}.value_contract"
                if value_contract is not None
                else declaration_path
            ),
        )


def _validate_value_contract_schema(
    schema: Mapping[str, Any],
    *,
    path: str,
) -> None:
    unexpected = set(schema) - _SUPPORTED_VALUE_CONTRACT_KEYS
    if unexpected:
        raise ParameterContractDefinitionError(
            f"{path} has unsupported value-contract keywords "
            f"{sorted(unexpected)!r}"
        )
    for keyword in ("allOf", "anyOf", "oneOf"):
        alternatives = schema.get(keyword)
        if alternatives is None:
            continue
        if not isinstance(alternatives, (list, tuple)) or not alternatives:
            raise ParameterContractDefinitionError(
                f"{path}.{keyword} must be a non-empty array"
            )
        for index, alternative in enumerate(alternatives):
            if not isinstance(alternative, Mapping):
                raise ParameterContractDefinitionError(
                    f"{path}.{keyword}[{index}] must be an object"
                )
            _validate_value_contract_schema(
                alternative,
                path=f"{path}.{keyword}[{index}]",
            )
    item_schema = schema.get("items")
    if item_schema is not None:
        if not isinstance(item_schema, Mapping):
            raise ParameterContractDefinitionError(
                f"{path}.items must be an object"
            )
        _validate_value_contract_schema(
            item_schema,
            path=f"{path}.items",
        )
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            raise ParameterContractDefinitionError(
                f"{path}.properties must be an object"
            )
        for name, property_schema in properties.items():
            if is_environment_parameter_name(name):
                raise ParameterContractDefinitionError(
                    f"{path}.properties.{name} declares Environment "
                    "Configuration or model identity"
                )
            if not isinstance(property_schema, Mapping):
                raise ParameterContractDefinitionError(
                    f"{path}.properties.{name} must be an object"
                )
            _validate_value_contract_schema(
                property_schema,
                path=f"{path}.properties.{name}",
            )
    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, bool):
        if not isinstance(additional, Mapping):
            raise ParameterContractDefinitionError(
                f"{path}.additionalProperties must be boolean or an object"
            )
        _validate_value_contract_schema(
            additional,
            path=f"{path}.additionalProperties",
        )
