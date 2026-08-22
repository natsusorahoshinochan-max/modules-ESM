"""Shared fixtures for exact SimpleFold Provider Asset Closures."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from modules.folding.simplefold_asset_closure import (
    SimpleFoldProviderAssetClosure,
)


def build_fixture_simplefold_closure(
    closure: SimpleFoldProviderAssetClosure,
    file_sha256: Mapping[str, str],
) -> SimpleFoldProviderAssetClosure:
    """Replace production proofs with exact files and installed fixture source."""
    return replace(
        closure,
        files=tuple(
            replace(
                entry,
                sha256=file_sha256[entry.runtime_filename],
            )
            for entry in closure.files
        ),
        sources=tuple(
            replace(
                source,
                package_name="fixture",
                environment_key=None,
                staging_group=None,
                reviewed_files=(),
                source_tree_sha256=None,
            )
            for source in closure.sources
        ),
    )


def install_fixture_source_staging_group(
    monkeypatch: object,
    adapter_module: object,
) -> None:
    """Supply the empty source group needed by a replaced test runtime."""
    original = adapter_module.stage_simplefold_provider_asset_closure

    def stage(*args: object, **kwargs: object):
        staged = original(*args, **kwargs)
        source_root = staged.root / "esm2_source"
        source_root.mkdir(exist_ok=True)
        return replace(
            staged,
            groups=(*staged.groups, ("esm2_source", source_root)),
        )

    monkeypatch.setattr(  # type: ignore[attr-defined]
        adapter_module,
        "stage_simplefold_provider_asset_closure",
        stage,
    )
