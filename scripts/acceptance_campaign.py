#!/usr/bin/env python3
"""CLI for one structured real-Provider Acceptance Campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

import modules.acceptance_campaign as campaign


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_VERIFICATION_TIERS = (
    "routine",
    "examples-v2",
    "deterministic-acceptance",
    "scientific-repro",
    "local-esmfold2-v2-contract",
    "installed-package",
)


def verify_repository(profile: campaign.ExecutionProfile) -> None:
    """Run the separate repository matrix with one explicit profile."""
    for tier in REPOSITORY_VERIFICATION_TIERS:
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "verify_backend.py"),
                tier,
            ],
            cwd=PROJECT_ROOT,
            env=profile.complete_environment(),
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("root", type=Path)
    prepare.add_argument("--profile", required=True, type=Path)
    run = subparsers.add_parser("run")
    run.add_argument("root", type=Path)
    run.add_argument("--profile", required=True, type=Path)
    status = subparsers.add_parser("status")
    status.add_argument("root", type=Path)
    repository = subparsers.add_parser("verify-repository")
    repository.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "status":
        print(
            json.dumps(
                campaign.campaign_status(args.root.resolve()),
                sort_keys=True,
            )
        )
        return 0
    profile = campaign.ExecutionProfile.load(args.profile.resolve())
    if args.command == "verify-repository":
        verify_repository(profile)
    elif args.command == "prepare":
        campaign.prepare_campaign(args.root.resolve(), profile)
    else:
        campaign.run_campaign(args.root.resolve(), profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
