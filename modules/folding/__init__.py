"""Shared folding Node Type and explicit execution Bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .package import MODULE_PACKAGE

__all__ = ["MODULE_PACKAGE"]


def __getattr__(name: str) -> Any:
    if name != "MODULE_PACKAGE":
        raise AttributeError(name)
    from .package import MODULE_PACKAGE

    return MODULE_PACKAGE
