"""Focused contract tests for local Torch device selection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.local_torch_device import (
    expected_local_torch_device,
    local_torch_device_is_available,
)


@pytest.mark.parametrize(
    ("platform_name", "expected"),
    (("linux", "cuda"), ("win32", "cuda"), ("darwin", "cpu")),
)
def test_platform_default_device(platform_name: str, expected: str) -> None:
    assert expected_local_torch_device(platform_name) == expected


def test_cuda_probe_executes_and_synchronizes_one_kernel() -> None:
    calls: list[object] = []
    probe = SimpleNamespace(
        device="cuda:0",
        add_=lambda value: calls.append(("add", value)),
    )
    torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True,
            synchronize=lambda device: calls.append(("sync", device)),
        ),
        ones=lambda size, *, device: (
            calls.append(("ones", size, device)) or probe
        ),
    )

    assert local_torch_device_is_available(torch, "cuda") is True
    assert calls == [
        ("ones", 1, "cuda"),
        ("add", 1),
        ("sync", "cuda:0"),
    ]


def test_unavailable_cuda_never_attempts_cpu_fallback() -> None:
    torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False),
        ones=lambda *_args, **_kwargs: pytest.fail(
            "unavailable CUDA must not run any tensor operation"
        ),
    )

    assert local_torch_device_is_available(torch, "cuda") is False
