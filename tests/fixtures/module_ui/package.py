"""External scientific package with a React editor using the public contract."""

from dataclasses import replace

from core.catalog.declarations import ModuleUiDefinition, NodeEditorDefinition
from tests.fixtures.zero_core_packages.synthetic_echo.package import MODULE_PACKAGE as SCIENCE

MODULE_PACKAGE = replace(SCIENCE, ui_extensions=(ModuleUiDefinition(
    extension_id="external.editor", resource_package="tests.fixtures.module_ui",
    entry="editor.js", styles=(), react_major=19,
    editors=(NodeEditorDefinition(
        editor_id="external.source.editor", title="External editor",
        node_type_ids=("contract_test.synthetic_candidate_source",), component="ExternalEditor",
    ),),
),))
