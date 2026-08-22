"""Biohub credential-file configuration owned by the ESM-3 package."""

from __future__ import annotations

import os
from pathlib import Path

from core.provider_support import read_private_credential_file


def read_biohub_token(project_dir: str | None = None) -> str:
    """Read the configured Biohub token through shared credential hygiene."""
    configured = os.environ.get("PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE")
    if configured:
        candidates = (Path(configured).expanduser(),)
    else:
        if os.environ.get("PROTEIN_WORKBENCH_VERIFICATION_TIER") in {
            "fresh-1pga",
            "fresh-2emo",
            "fresh-canonical-3gb1",
            "fresh-5g53",
        }:
            raise FileNotFoundError(
                "Fresh source-bound gate requires an explicit Biohub token file"
            )
        project_candidate = (
            ()
            if project_dir is None
            else (Path(project_dir) / ".." / ".." / "keys" / "esmkey.txt",)
        )
        candidates = (Path("keys/esmkey.txt"), *project_candidate)
    for candidate in candidates:
        candidate_path = candidate.expanduser()
        if not candidate_path.is_absolute():
            candidate_path = Path.cwd() / candidate_path
        try:
            return read_private_credential_file(candidate_path)
        except FileNotFoundError:
            continue
    raise FileNotFoundError(
        "Biohub API key not found. Configure "
        "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE."
    )
