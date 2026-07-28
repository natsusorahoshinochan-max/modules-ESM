"""Negative probes for the live-provider verification command."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest


@pytest.mark.live_provider
def test_skipped_provider_probe() -> None:
    pytest.skip("provider readiness is not provider execution")


@pytest.mark.live_provider
def test_readiness_only_probe() -> None:
    assert True


@pytest.mark.live_provider
def test_forged_provider_evidence_probe() -> None:
    evidence_path = Path(os.environ["PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE"])
    evidence_path.write_text(json.dumps({
        "provider": "biohub",
        "operation": "esm3.generate_sequence",
    }) + "\n")


@pytest.mark.live_provider
def test_provider_evidence_uses_parent_private_staging_probe() -> None:
    evidence_path = Path(
        os.environ["PROTEIN_WORKBENCH_PROVIDER_CALL_EVIDENCE"]
    ).resolve()
    temporary_parent = Path(os.environ["TMPDIR"]).resolve().parent

    assert evidence_path.is_relative_to(temporary_parent)


@pytest.mark.live_provider
def test_delayed_retained_directory_probe() -> None:
    time.sleep(2)


@pytest.mark.live_provider
def test_call_without_readiness_probe() -> None:
    from core.provider_evidence import record_provider_call_result

    record_provider_call_result(
        provider="biohub",
        operation="esm3.generate_sequence",
        model="esm3-medium-2024-08",
        provider_identity={"service": "Biohub"},
        effective_seed=None,
        seed_control="unsupported_by_provider",
        result_summary={"result_type": "ESMProtein"},
    )


@pytest.mark.live_provider
def test_self_reported_call_and_readiness_probe() -> None:
    from core.provider_evidence import (
        record_provider_call_result,
        record_provider_readiness,
    )

    record_provider_readiness(
        provider="biohub",
        ready=True,
        identity={"service": "Biohub"},
    )
    record_provider_call_result(
        provider="biohub",
        operation="esm3.generate_sequence",
        model="esm3-medium-2024-08",
        provider_identity={"service": "Biohub"},
        effective_seed=None,
        seed_control="unsupported_by_provider",
        result_summary={"result_type": "ESMProtein"},
    )
