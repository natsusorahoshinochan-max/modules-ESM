"""Real public app with an external package for module-editor browser journeys."""

from fastapi import FastAPI

from core.catalog.builder import build_frozen_catalog
from modules.selection.package import MODULE_PACKAGE as SELECTION
from tests.fixtures.module_ui.package import MODULE_PACKAGE as EXTERNAL
from tests.support.application import create_application as compose


def create_application() -> FastAPI:
    registrations = (SELECTION, EXTERNAL)
    return compose(
        frozen_catalog_override=build_frozen_catalog(registrations),
        authoring_registrations=registrations,
        v2_environment_configuration={binding.binding_id: {
            "fixture_ready": True,
            "credential": "module-ui-test-credential",
            "runtime_path": "/private/module-ui-fixture",
        } for binding in EXTERNAL.bindings},
    )
