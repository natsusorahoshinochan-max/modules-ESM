"""Inspect selected, possibly unpublished inputs for the module's import UI."""
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

import yaml

from core.catalog.authoring_actions import AuthoringActionContext, AuthoringActionDefinition
from core.workflow.authoring import WorkflowAuthoringError
from protein_workbench_public.protocol import validate_schema
from .errors import ProteinInputError
from .inspection import inspect_project_input


_SCHEMA = yaml.safe_load(files(__package__).joinpath('definitions/authoring-schema.yaml').read_text())


def inspect_input(context: AuthoringActionContext, parameters: Mapping[str, Any]) -> dict[str, Any]:
    admitted = {**parameters, 'project_id': context.project_id}
    validate_schema('#/$defs/ProjectInputInspectionRequest', admitted, definitions=_SCHEMA)
    reference = admitted['project_input_ref']
    descriptor, payload = context.read_input(reference)
    try:
        inspection = inspect_project_input(payload, admitted['format'])
    except ProteinInputError as error:
        raise WorkflowAuthoringError('project_input_invalid', str(error),
            details={'project_input_ref': reference, 'format': admitted['format']}) from error
    return {'project_id': context.project_id, 'project_input_ref': reference,
            'content_digest': descriptor.content_digest, **inspection}


INSPECT_INPUT = AuthoringActionDefinition('protein_io.inspect_input', inspect_input)
