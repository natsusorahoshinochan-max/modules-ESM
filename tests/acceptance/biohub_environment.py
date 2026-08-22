"""Trusted Biohub Environment Configuration shared by fresh acceptance."""

from __future__ import annotations

from typing import Any


def biohub_esm3_esmfold2_environment() -> dict[tuple[str, str], Any]:
    from modules.esm3.credentials import read_biohub_token

    token = read_biohub_token()

    return {
        ("esm3.generate_paired.biohub_medium", "8.0.0"): {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": token,
            },
        },
        ("folding.fold.esmfold2_remote", "9.0.0"): {
            "values": {
                "endpoint_id": "biohub",
                "credential_handle": token,
            },
        },
    }
