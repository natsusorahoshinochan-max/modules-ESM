"""Read-only Prompt editor actions registered like any external module."""
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

import yaml

from core.project.manager import ProjectInputDescriptor
from core.catalog.authoring_actions import AuthoringActionContext, AuthoringActionDefinition
from protein_workbench_public.protocol import validate_schema
from .authoring import PromptAuthoringService
from .authoring_codec import encode_prompt_preview, encode_prompt_snapshot


_SCHEMA = yaml.safe_load(files(__package__).joinpath('definitions/authoring-schema.yaml').read_text())


def _service(context: AuthoringActionContext) -> PromptAuthoringService:
    def read_input(project_id: str, reference: str) -> tuple[ProjectInputDescriptor, bytes]:
        if project_id == context.project_id:
            return context.read_input(reference)
        return context.projects.read_input(project_id, reference)
    return PromptAuthoringService(context.projects, context.workflow_authoring,
                                  context.catalog, input_reader=read_input)


def open_prompt(context: AuthoringActionContext, parameters: Mapping[str, Any]) -> dict[str, Any]:
    admitted = {**parameters, 'project_id': context.project_id}
    validate_schema('#/$defs/PromptAuthoringOpenRequest', admitted, definitions=_SCHEMA)
    return encode_prompt_snapshot(_service(context).open(context.project_id, admitted))


def preview_prompt(context: AuthoringActionContext, parameters: Mapping[str, Any]) -> dict[str, Any]:
    admitted = {**parameters, 'project_id': context.project_id}
    validate_schema('#/$defs/PromptAuthoringPreviewRequest', admitted, definitions=_SCHEMA)
    return encode_prompt_preview(_service(context).preview(context.project_id, admitted))


AUTHORING_ACTIONS = (
    AuthoringActionDefinition('prompt_authoring.open', open_prompt),
    AuthoringActionDefinition('prompt_authoring.preview', preview_prompt),
)
