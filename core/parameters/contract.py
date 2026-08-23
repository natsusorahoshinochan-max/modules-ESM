"""Closed parameter-contract vocabulary shared by Catalog build and compiler."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from core.parameters.model import (
    AdmittedParameterValues,
    ParameterContract,
    ParameterDeclaration,
)
from datatypes.i_json import thaw_i_json


class ParameterContractDefinitionError(ValueError):
    """A Catalog parameter declaration is outside the scientific contract."""


_SUPPORTED_VALUE_CONTRACT_KEYS = frozenset(
    {
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "enum",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "field_scope",
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
        "scientific_meaning",
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
        "parameter_scope",
        "resource_kind",
        "required",
        "scientific_meaning",
        "summary",
        "title",
        "unit",
        "utility_transform",
        "value_contract",
    }
)


def _validate_parameter_declarations(
    declarations: Mapping[str, Any],
    *,
    path: str,
) -> None:
    """Fail closed unless declarations use the supported value vocabulary."""
    for name, declaration in declarations.items():
        declaration_path = f"{path}.{name}"
        if not isinstance(declaration, Mapping):
            raise ParameterContractDefinitionError(
                f"{declaration_path} must be an object"
            )
        if declaration.get("parameter_scope") != "scientific":
            raise ParameterContractDefinitionError(
                f"{declaration_path}.parameter_scope must explicitly equal "
                "'scientific'"
            )
        scientific_meaning = declaration.get("scientific_meaning")
        if (
            not isinstance(scientific_meaning, str)
            or not scientific_meaning.strip()
        ):
            raise ParameterContractDefinitionError(
                f"{declaration_path}.scientific_meaning must explicitly "
                "describe the cross-Binding scientific parameter"
            )
        resource_kind = declaration.get("resource_kind")
        if resource_kind is not None and resource_kind != "project_input":
            raise ParameterContractDefinitionError(
                f"{declaration_path}.resource_kind must equal "
                "'project_input'"
            )
        if resource_kind == "project_input" and (
            declaration.get("required") is not True
            or "default" in declaration
        ):
            raise ParameterContractDefinitionError(
                f"{declaration_path} Project input resources must be "
                "required and cannot declare a default"
            )
        value_contract = declaration.get("value_contract")
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
            path=f"{declaration_path}.value_contract",
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
    discriminators = {"allOf", "anyOf", "const", "enum", "oneOf", "type"}
    if not set(schema).intersection(discriminators):
        raise ParameterContractDefinitionError(
            f"{path} must declare type, const, enum, or a schema combinator"
        )
    expected_type = schema.get("type")
    supported_types = {
        "array",
        "boolean",
        "integer",
        "null",
        "number",
        "object",
        "string",
    }
    if "type" in schema:
        if isinstance(expected_type, str):
            types = (expected_type,)
        elif (
            isinstance(expected_type, (list, tuple))
            and all(isinstance(item, str) for item in expected_type)
        ):
            types = tuple(expected_type)
        else:
            raise ParameterContractDefinitionError(
                f"{path}.type must be a type name or array of type names"
            )
        if (
            not types
            or any(item not in supported_types for item in types)
            or len(set(types)) != len(types)
        ):
            raise ParameterContractDefinitionError(
                f"{path}.type must contain supported unique value types"
            )
    else:
        types = ()
    enum = schema.get("enum")
    if "enum" in schema and (
        not isinstance(enum, (list, tuple)) or not enum
    ):
        raise ParameterContractDefinitionError(
            f"{path}.enum must be a non-empty array"
        )
    if types:
        typed_values = list(enum or ())
        if "const" in schema:
            typed_values.append(schema["const"])
        if any(
            not any(_parameter_type_matches(value, item) for item in types)
            for value in typed_values
        ):
            raise ParameterContractDefinitionError(
                f"{path}.enum/const values must conform to type"
            )
    for keyword in (
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
    ):
        if keyword not in schema:
            continue
        bound = schema[keyword]
        if (
            not isinstance(bound, (int, float))
            or isinstance(bound, bool)
        ):
            raise ParameterContractDefinitionError(
                f"{path}.{keyword} must be a number"
            )
    numeric_keywords = {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
    }
    if set(schema).intersection(numeric_keywords) and not set(types).intersection(
        {"integer", "number"}
    ):
        raise ParameterContractDefinitionError(
            f"{path} numeric bounds require an integer or number type"
        )
    for minimum_keyword, maximum_keyword in (
        ("minimum", "maximum"),
        ("exclusiveMinimum", "exclusiveMaximum"),
        ("minLength", "maxLength"),
        ("minItems", "maxItems"),
        ("minProperties", "maxProperties"),
    ):
        if (
            minimum_keyword in schema
            and maximum_keyword in schema
            and schema[minimum_keyword] > schema[maximum_keyword]
        ):
            raise ParameterContractDefinitionError(
                f"{path}.{minimum_keyword} must not exceed {maximum_keyword}"
            )
    for keyword in (
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
    ):
        if keyword not in schema:
            continue
        limit = schema[keyword]
        if (
            type(limit) is not int or limit < 0
        ):
            raise ParameterContractDefinitionError(
                f"{path}.{keyword} must be a non-negative integer"
            )
    required = schema.get("required")
    keyword_type_groups = (
        (
            {"minLength", "maxLength", "pattern"},
            "string",
        ),
        (
            {"minItems", "maxItems", "uniqueItems", "items"},
            "array",
        ),
        (
            {
                "minProperties",
                "maxProperties",
                "properties",
                "required",
                "additionalProperties",
            },
            "object",
        ),
    )
    for keywords, required_type in keyword_type_groups:
        present = set(schema).intersection(keywords)
        if present and required_type not in types:
            raise ParameterContractDefinitionError(
                f"{path} fields {sorted(present)!r} require "
                f"type {required_type!r}"
            )
    pattern = schema.get("pattern")
    if "pattern" in schema:
        if not isinstance(pattern, str):
            raise ParameterContractDefinitionError(
                f"{path}.pattern must be a string"
            )
        try:
            re.compile(pattern)
        except re.error as error:
            raise ParameterContractDefinitionError(
                f"{path}.pattern is invalid"
            ) from error
    unique_items = schema.get("uniqueItems")
    if "uniqueItems" in schema and type(unique_items) is not bool:
        raise ParameterContractDefinitionError(
            f"{path}.uniqueItems must be boolean"
        )
    if "required" in schema:
        if (
            not isinstance(required, (list, tuple))
            or any(not isinstance(name, str) for name in required)
            or len(set(required)) != len(required)
        ):
            raise ParameterContractDefinitionError(
                f"{path}.required must be a unique array of field names"
            )
    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword not in schema:
            continue
        alternatives = schema[keyword]
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
    if "items" in schema:
        if not isinstance(item_schema, Mapping):
            raise ParameterContractDefinitionError(
                f"{path}.items must be an object"
            )
        _validate_value_contract_schema(
            item_schema,
            path=f"{path}.items",
        )
    properties = schema.get("properties")
    if "properties" in schema:
        if not isinstance(properties, Mapping):
            raise ParameterContractDefinitionError(
                f"{path}.properties must be an object"
            )
        for name, property_schema in properties.items():
            if not isinstance(property_schema, Mapping):
                raise ParameterContractDefinitionError(
                    f"{path}.properties.{name} must be an object"
                )
            if property_schema.get("field_scope") != "scientific":
                raise ParameterContractDefinitionError(
                    f"{path}.properties.{name}.field_scope must explicitly "
                    "equal 'scientific'"
                )
            field_meaning = property_schema.get("scientific_meaning")
            if (
                not isinstance(field_meaning, str)
                or not field_meaning.strip()
            ):
                raise ParameterContractDefinitionError(
                    f"{path}.properties.{name}.scientific_meaning must "
                    "explicitly describe the scientific value field"
                )
            _validate_value_contract_schema(
                property_schema,
                path=f"{path}.properties.{name}",
            )
        undeclared = set(required or ()) - set(properties)
        if undeclared:
            raise ParameterContractDefinitionError(
                f"{path}.required contains undeclared fields "
                f"{sorted(undeclared)!r}"
            )
    additional = schema.get("additionalProperties")
    expresses_object = "object" in types or properties is not None
    if expresses_object and additional is not False:
        raise ParameterContractDefinitionError(
            f"{path}.additionalProperties must explicitly be false "
            "for Workflow object parameters"
        )
    if (
        "additionalProperties" in schema
        and type(additional) is not bool
    ):
        raise ParameterContractDefinitionError(
            f"{path}.additionalProperties must be boolean"
        )


def _parameter_contract_violation(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: tuple[str | int, ...],
) -> tuple[tuple[str | int, ...], str] | None:
    """Return the first violation of one validated value contract."""
    if "const" in schema and value != schema["const"]:
        return path, f"must equal {schema['const']!r}"
    if "enum" in schema and value not in schema["enum"]:
        return path, f"must be one of {list(schema['enum'])!r}"

    for keyword in ("allOf", "anyOf", "oneOf"):
        alternatives = schema.get(keyword)
        if alternatives is None:
            continue
        results = [
            _parameter_contract_violation(value, item, path=path)
            for item in alternatives
        ]
        matches = sum(result is None for result in results)
        if keyword == "allOf" and any(result is not None for result in results):
            return next(result for result in results if result is not None)
        if keyword == "anyOf" and matches == 0:
            return path, "must match at least one value-contract alternative"
        if keyword == "oneOf" and matches != 1:
            return path, "must match exactly one value-contract alternative"

    expected_type = schema.get("type")
    if isinstance(expected_type, (list, tuple)):
        valid_type = any(
            _parameter_type_matches(value, candidate)
            for candidate in expected_type
        )
    else:
        valid_type = (
            True
            if expected_type is None
            else _parameter_type_matches(value, expected_type)
        )
    if not valid_type:
        return path, f"must be {expected_type}"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for keyword, comparison, reason in (
            ("minimum", lambda item, bound: item < bound, "at least"),
            ("maximum", lambda item, bound: item > bound, "at most"),
            (
                "exclusiveMinimum",
                lambda item, bound: item <= bound,
                "greater than",
            ),
            (
                "exclusiveMaximum",
                lambda item, bound: item >= bound,
                "less than",
            ),
        ):
            bound = schema.get(keyword)
            if bound is not None and comparison(value, bound):
                return path, f"must be {reason} {bound}"

    if isinstance(value, str):
        if (
            schema.get("minLength") is not None
            and len(value) < schema["minLength"]
        ):
            return path, f"must contain at least {schema['minLength']} characters"
        if (
            schema.get("maxLength") is not None
            and len(value) > schema["maxLength"]
        ):
            return path, f"must contain at most {schema['maxLength']} characters"
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            return path, f"must match {pattern!r}"

    if isinstance(value, (list, tuple)):
        if (
            schema.get("minItems") is not None
            and len(value) < schema["minItems"]
        ):
            return path, f"must contain at least {schema['minItems']} items"
        if (
            schema.get("maxItems") is not None
            and len(value) > schema["maxItems"]
        ):
            return path, f"must contain at most {schema['maxItems']} items"
        if schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if item in value[:index]:
                    return (*path, index), "must be unique"
        if "items" in schema:
            for index, item in enumerate(value):
                violation = _parameter_contract_violation(
                    item,
                    schema["items"],
                    path=(*path, index),
                )
                if violation is not None:
                    return violation

    object_keywords = {
        "additionalProperties",
        "maxProperties",
        "minProperties",
        "properties",
        "required",
    }
    if isinstance(value, Mapping) and set(schema).intersection(
        object_keywords
    ):
        properties = schema.get("properties", {})
        required = schema.get("required", ())
        missing = [name for name in required if name not in value]
        if missing:
            return path, f"must contain required fields {missing!r}"
        if (
            schema.get("minProperties") is not None
            and len(value) < schema["minProperties"]
        ):
            return path, f"must contain at least {schema['minProperties']} fields"
        if (
            schema.get("maxProperties") is not None
            and len(value) > schema["maxProperties"]
        ):
            return path, f"must contain at most {schema['maxProperties']} fields"
        for name, item in value.items():
            item_schema = properties.get(name)
            if item_schema is None:
                return (*path, name), "is not an allowed field"
            violation = _parameter_contract_violation(
                item,
                item_schema,
                path=(*path, name),
            )
            if violation is not None:
                return violation
    return None


def _parameter_type_matches(value: Any, expected_type: Any) -> bool:
    return {
        "null": value is None,
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": type(value) is str,
        "array": isinstance(value, (list, tuple)),
        "object": isinstance(value, Mapping),
    }[expected_type]


class ParameterValueAdmissionError(ValueError):
    """One submitted value set does not satisfy its admitted contract."""

    def __init__(
        self,
        code: str,
        path: tuple[str | int, ...],
        reason: str,
    ) -> None:
        super().__init__(reason)
        self.code = code
        self.path = path
        self.reason = reason


def admit_declarations(
    declarations: Mapping[str, Any],
    *,
    path: str,
) -> ParameterContract:
    """Admit one complete parameter declaration mapping."""
    _validate_parameter_declarations(declarations, path=path)
    return ParameterContract(
        tuple(
            ParameterDeclaration(
                name=name,
                value_contract=declaration["value_contract"],
                required=declaration.get("required") is True,
                has_default="default" in declaration,
                default=declaration.get("default"),
                resource_kind=declaration.get("resource_kind"),
            )
            for name, declaration in declarations.items()
        )
    )


def admit_values(
    contract: ParameterContract,
    submitted_values: Mapping[str, Any],
) -> AdmittedParameterValues:
    """Admit defaults and submitted values once against one exact contract."""
    unknown = sorted(set(submitted_values) - set(contract))
    if unknown:
        raise ParameterValueAdmissionError(
            "unknown_parameter",
            (),
            f"contains undeclared parameters: {unknown}",
        )
    resolved = {
        entry.name: thaw_i_json(entry.default)
        for entry in contract.entries
        if entry.has_default
    }
    resolved.update(thaw_i_json(submitted_values))
    for declaration in contract.entries:
        if (
            declaration.required
            and declaration.name not in submitted_values
            and not declaration.has_default
        ):
            raise ParameterValueAdmissionError(
                "required_parameter_missing",
                (declaration.name,),
                "is required",
            )
        if declaration.name not in resolved:
            continue
        violation = _parameter_contract_violation(
            resolved[declaration.name],
            declaration.value_contract,
            path=(declaration.name,),
        )
        if violation is not None:
            value_path, reason = violation
            raise ParameterValueAdmissionError(
                "invalid_parameter",
                value_path,
                reason,
            )
    return AdmittedParameterValues(resolved)
