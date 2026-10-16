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


def biohub_esm3_esmfold2_environment() -> dict[str, dict[str, Any]]:
    token = read_biohub_token()

    return {
        "esm3.generate_paired.biohub_medium": {
            "credential_handle": token,
        },
        "folding.fold.esmfold2_remote": {
            "credential_handle": token,
        },
    }
