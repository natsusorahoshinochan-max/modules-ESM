"""Trusted Biohub Environment Configuration shared by fresh acceptance."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.provider_support import read_private_credential_file


def read_biohub_token() -> str:
    """Read the one explicitly configured private Biohub credential."""
    return read_private_credential_file(
        Path(os.environ["PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE"])
        .expanduser()
    )


def biohub_esm3_esmfold2_environment() -> dict[tuple[str, str], Any]:
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
