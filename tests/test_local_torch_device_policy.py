"""Public platform policy for local Torch-backed Provider execution."""

from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

from core.local_torch_device import (
    LOCAL_TORCH_DEVICE_POLICY,
    expected_local_torch_device,
    local_torch_device_is_available,
)


ROOT = Path(__file__).resolve().parents[1]


def test_windows_frozen_provider_install_selects_cuda_torch_wheel() -> None:
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    indexes = {
        item["name"]: item for item in project["tool"]["uv"]["index"]
    }
    assert indexes["pytorch-cu130"] == {
        "name": "pytorch-cu130",
        "url": "https://download.pytorch.org/whl/cu130",
        "explicit": True,
    }
    assert {
        (item["index"], item["marker"])
        for item in project["tool"]["uv"]["sources"]["torch"]
    } == {("pytorch-cu130", "sys_platform == 'win32'")}

    lock_text = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert "https://download.pytorch.org/whl/cu130" in lock_text
    assert "torch-2.13.0%2Bcu130-cp312-cp312-win_amd64.whl" in lock_text


def test_local_torch_device_policy_is_one_explicit_cross_platform_contract(
) -> None:
    assert LOCAL_TORCH_DEVICE_POLICY == (
        "cuda_on_linux_windows_cpu_elsewhere"
    )


@pytest.mark.parametrize(
    ("platform_name", "expected_device"),
    (
        ("darwin", "cpu"),
        ("linux", "cuda"),
        ("linux2", "cuda"),
        ("win32", "cuda"),
        ("freebsd14", "cpu"),
    ),
)
def test_local_torch_device_is_selected_from_the_host_platform(
    platform_name: str,
    expected_device: str,
) -> None:
    assert expected_local_torch_device(platform_name) == expected_device


def test_local_torch_device_defaults_to_the_running_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.local_torch_device as policy

    monkeypatch.setattr(policy.sys, "platform", "linux")

    assert expected_local_torch_device() == "cuda"


def test_cuda_probe_executes_and_synchronizes_the_selected_device() -> None:
    class Probe:
        device = "cuda:0"

        def add_(self, value: int) -> None:
            assert value == 1

    class Cuda:
        synchronized: object | None = None

        @staticmethod
        def is_available() -> bool:
            return True

        @classmethod
        def synchronize(cls, device: object) -> None:
            cls.synchronized = device

    class Torch:
        cuda = Cuda

        @staticmethod
        def ones(size: int, *, device: str) -> Probe:
            assert size == 1
            assert device == "cuda"
            return Probe()

    assert local_torch_device_is_available(Torch, "cuda") is True
    assert Cuda.synchronized == "cuda:0"


def test_cuda_probe_failure_is_not_retried_on_cpu() -> None:
    calls: list[str] = []

    class Cuda:
        @staticmethod
        def is_available() -> bool:
            return True

    class Torch:
        cuda = Cuda

        @staticmethod
        def ones(_size: int, *, device: str) -> object:
            calls.append(device)
            raise RuntimeError("fixture CUDA initialization failure")

    assert local_torch_device_is_available(Torch, "cuda") is False
    assert calls == ["cuda"]
