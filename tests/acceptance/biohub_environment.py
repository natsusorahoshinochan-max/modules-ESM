"""Trusted Biohub Environment Configuration shared by fresh acceptance."""

from __future__ import annotations

from typing import Any


def biohub_esm3_esmfold2_environment() -> dict[tuple[str, str], Any]:
    from esm.sdk.forge import (
        ESM3ForgeInferenceClient,
        SequenceStructureForgeInferenceClient,
    )
    from modules.folding.adapter import REMOTE_ESMFOLD2_MODEL
    from modules.provider_contract import read_biohub_token

    token = read_biohub_token()

    def esm3_factory(
        *, model_name: str, endpoint_id: str, credential_handle: str
    ) -> Any:
        if endpoint_id != "biohub" or credential_handle != token:
            raise RuntimeError("remote ESM-3 Environment Configuration changed")
        return ESM3ForgeInferenceClient(
            model=model_name,
            token=credential_handle,
            request_timeout=180,
            max_retry_attempts=1,
        )

    def folding_factory(
        *, model_name: str, endpoint_id: str, credential_handle: str
    ) -> Any:
        if (
            endpoint_id != "biohub"
            or credential_handle != token
            or model_name != REMOTE_ESMFOLD2_MODEL
        ):
            raise RuntimeError(
                "remote ESMFold2 Environment Configuration changed"
            )
        return SequenceStructureForgeInferenceClient(
            model=model_name,
            token=credential_handle,
            request_timeout=240,
            max_retry_attempts=1,
        )

    return {
        ("esm3.generate_paired.biohub_medium", "7.0.0"): {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": token,
                "client_factory": esm3_factory,
            },
        },
        ("folding.fold.esmfold2_remote", "7.0.0"): {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": token,
                "client_factory": folding_factory,
            },
        },
    }
