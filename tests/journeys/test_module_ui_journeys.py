"""Module UI discovery and resources through the public application boundary."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.catalog.builder import build_frozen_catalog
from modules.selection.package import MODULE_PACKAGE as SELECTION_PACKAGE
from tests.fixtures.zero_core_packages.synthetic_echo.package import MODULE_PACKAGE as EXTERNAL_PACKAGE
from tests.support.application import create_application


def test_official_and_external_editors_share_public_discovery_and_asset_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.catalog.declarations import ModuleUiDefinition, NodeEditorDefinition

    monkeypatch.setenv("PROTEIN_WORKBENCH_DATA_ROOT", str(tmp_path))
    external = replace(
        EXTERNAL_PACKAGE,
        package_id="external.selection",
        ui_extensions=(ModuleUiDefinition(
            extension_id="external.editor",
            resource_package="tests.fixtures.module_ui",
            entry="editor.js",
            styles=(),
            react_major=19,
            editors=(NodeEditorDefinition(
                editor_id="external.selection.editor", title="External selection",
                node_type_ids=("contract_test.synthetic_candidate_source",), component="ExternalEditor",
            ),),
        ),),
    )
    catalog = build_frozen_catalog((SELECTION_PACKAGE, external))
    with TestClient(create_application(frozen_catalog_override=catalog)) as http:
        response = http.get("/api/v2/module-ui")
        assert response.status_code == 200, response.text
        extensions = {item["extension_id"]: item for item in response.json()["extensions"]}
        assert set(extensions) == {"selection.editors", "external.editor"}
        for extension_id in ("selection.editors", "external.editor"):
            manifest = extensions[extension_id]
            assert manifest["react_major"] == 19
            assert manifest["entry_url"].startswith(f"/api/v2/module-ui/{extension_id}/assets/")
            asset = http.get(manifest["entry_url"])
            assert asset.status_code == 200, asset.text
            assert "javascript" in asset.headers["content-type"]
            assert "register" in asset.text
        assert extensions["external.editor"]["editors"] == [{
            "editor_id": "external.selection.editor", "title": "External selection",
            "node_type_ids": ["contract_test.synthetic_candidate_source"], "component": "ExternalEditor",
        }]
