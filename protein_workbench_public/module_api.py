"""Public, scientific-model-free declarations for independently authored modules.

Execute must finish and close all output files before returning Outcome. Returning
transfers file ownership to the host; modules must not subsequently mutate them.
Delivery file values are relative to the current runtime workdir. File keys are
stable package names and may differ from those temporary source locations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Literal, Mapping, Protocol, Any


@dataclass(frozen=True)
class InputPort:
    accepts: tuple[str, ...]
    cardinality: Literal["one", "many"] = "one"
    required: bool = True


@dataclass(frozen=True)
class OutputPort:
    format: str
    cardinality: Literal["one", "many"] = "one"


@dataclass(frozen=True)
class Delivery:
    format: str
    entry: str
    files: Mapping[str, str]


class Package(Protocol):
    """Read-only access to received files, independent of the producer."""
    id: str
    format: str
    entry: str
    files: tuple[str, ...]

    def open(self, key: str) -> BinaryIO: ...
    def metadata(self) -> dict[str, Any]: ...


class Runtime(Protocol):
    workdir: Path
    cancelled: bool

    def progress(self, message: str) -> None: ...


@dataclass(frozen=True)
class Call:
    inputs: Mapping[str, tuple[Package, ...]]
    parameters: dict[str, Any]
    settings: dict[str, Any]
    tool_parameters: dict[str, Any] = field(default_factory=dict)
    previous: Any = None


@dataclass(frozen=True)
class Outcome:
    status: Literal["succeeded", "failed", "cancelled"] = "succeeded"
    outputs: Mapping[str, list[Delivery]] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    continuation: Any = None


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    execute: Callable[[Call, Runtime], Outcome]
    inputs: Mapping[str, InputPort] = field(default_factory=dict)
    outputs: Mapping[str, OutputPort] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Module:
    id: str
    name: str
    nodes: tuple[Node, ...] = ()
    settings: dict[str, Any] = field(default_factory=dict)
    ui: str | None = None
