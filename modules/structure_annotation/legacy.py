"""Thin compatibility adapters for the pre-v2 structure modules.

The legacy WorkflowModule contracts remain discoverable, but their DSSP
parsing, invocation, and agreement calculation live with the cohesive v2
package instead of being copied across four modules.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import signal
from typing import Any, Callable
import uuid

from core.process_control import verification_uses_shared_process_group
from core.provider_evidence import record_provider_call_result
from core.run_context import RunContext
from datatypes import ProteinStructure, ResidueTrack, Score, ScoreCollection

from .implementation import _parse_dssp_rows


def parse_dssp_mmcif_legacy(text: str) -> tuple[list[str], list[float]]:
    """Adapt the shared DSSP row parser to the historical loose track types."""
    if not text.strip():
        return [], []
    rows = _parse_dssp_rows(text)
    secondary = [
        "-" if row.secondary_structure == "." else row.secondary_structure
        for row in rows
    ]
    sasa: list[float] = []
    for row in rows:
        try:
            sasa.append(float(row.accessibility))
        except ValueError:
            sasa.append(0.0)
    return secondary, sasa


def run_dssp_sync_legacy(
    inputs: dict[str, Any],
    parameters: dict[str, Any],
    context: RunContext,
    *,
    operation: str,
    output_port: str,
    select_values: Callable[
        [tuple[list[str], list[float]]],
        list[str] | list[float],
    ],
    run_process: Callable[..., Any],
) -> dict[str, Any]:
    """Run the legacy synchronous DSSP boundary through one adapter."""
    structure: ProteinStructure | None = inputs.get("structure")
    if structure is None:
        raise ValueError("structure input is required")

    dssp_bin = str(parameters.get("dssp_binary", "/opt/homebrew/bin/mkdssp"))
    with context.temporary_file(mode="w", suffix=".pdb", delete=False) as tmp:
        tmp.write(structure.pdb_string)
        pdb_path = tmp.name

    try:
        context.record_provider_call(
            "mkdssp",
            operation,
            model=Path(dssp_bin).name,
        )
        result = run_process(
            [dssp_bin, pdb_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"mkdssp failed: {result.stderr.strip()}")
        values = select_values(parse_dssp_mmcif_legacy(result.stdout))
        return {output_port: ResidueTrack(values=values, sentinel=None)}
    finally:
        Path(pdb_path).unlink(missing_ok=True)


async def run_dssp_async_legacy(
    inputs: dict[str, Any],
    parameters: dict[str, Any],
    context: RunContext,
    *,
    signal_process_group_fn: Callable[..., None],
) -> dict[str, Any]:
    """Run the legacy asynchronous DSSP boundary through one adapter."""
    structure: ProteinStructure | None = inputs.get("structure")
    if structure is None:
        raise ValueError("structure input is required")

    dssp_bin = str(parameters.get("dssp_binary", "/opt/homebrew/bin/mkdssp"))
    timeout = int(parameters.get("timeout", 30))
    with context.temporary_file(mode="w", suffix=".pdb", delete=False) as tmp:
        tmp.write(structure.pdb_string)
        pdb_path = tmp.name

    try:
        context.record_provider_call(
            "mkdssp",
            "secondary_structure",
            model=Path(dssp_bin).name,
        )
        process = await asyncio.create_subprocess_exec(
            dssp_bin,
            pdb_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=not verification_uses_shared_process_group(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except asyncio.CancelledError:
            if process.returncode is None:
                signal_process_group_fn(
                    process.pid,
                    signal.SIGTERM,
                    fallback=process.terminate,
                )
                try:
                    await asyncio.wait_for(process.wait(), timeout=1)
                except asyncio.TimeoutError:
                    signal_process_group_fn(
                        process.pid,
                        signal.SIGKILL,
                        fallback=process.kill,
                    )
                    await process.wait()
            raise
        except asyncio.TimeoutError:
            signal_process_group_fn(
                process.pid,
                signal.SIGKILL,
                fallback=process.kill,
            )
            await process.wait()
            raise RuntimeError(f"mkdssp timed out after {timeout}s")

        if process.returncode != 0:
            message = stderr.decode().strip() if stderr else "unknown error"
            if "No such file" in message or "not found" in message.lower():
                raise RuntimeError(
                    f"mkdssp binary not found at '{dssp_bin}'. "
                    "Install mkdssp or set dssp_binary parameter."
                )
            raise RuntimeError(
                f"mkdssp failed (exit {process.returncode}): {message}"
            )

        secondary, _ = parse_dssp_mmcif_legacy(stdout.decode())
        record_provider_call_result(
            provider="mkdssp",
            operation="secondary_structure",
            model=Path(dssp_bin).name,
            provider_identity={
                "binary": Path(dssp_bin).name,
                "required_version": "4.6.1",
            },
            effective_seed=None,
            seed_control="deterministic_no_rng",
            result_summary={
                "return_code": process.returncode,
                "output_bytes": len(stdout),
                "output_sha256": hashlib.sha256(stdout).hexdigest(),
                "residue_count": len(secondary),
            },
        )
        return {
            "secondary_structure_track": ResidueTrack(
                values=secondary,
                sentinel=None,
            )
        }
    finally:
        Path(pdb_path).unlink(missing_ok=True)


def secondary_structure_agreement_legacy(
    inputs: dict[str, Any],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Preserve the historical coarse/exact score behind one adapter."""
    expected: ResidueTrack | None = inputs.get("expected")
    observed: ResidueTrack | None = inputs.get("observed")
    if expected is None:
        raise ValueError("expected input is required")
    if observed is None:
        raise ValueError("observed input is required")

    use_coarse = bool(parameters.get("coarse", True))
    count = min(len(expected), len(observed))
    if count == 0:
        raise ValueError("Both tracks are empty")

    helix = {"H", "G", "I"}
    sheet = {"B", "E"}

    def coarse(value: str) -> str:
        if value in helix:
            return "helix"
        if value in sheet:
            return "sheet"
        return "coil"

    matches: list[bool] = []
    for index in range(count):
        expected_value = expected.values[index]
        observed_value = observed.values[index]
        if expected_value is None or observed_value is None:
            matches.append(False)
        elif use_coarse:
            matches.append(
                coarse(str(expected_value)) == coarse(str(observed_value))
            )
        else:
            matches.append(str(expected_value) == str(observed_value))

    maximum = max(len(expected), len(observed))
    return {
        "scores": ScoreCollection(
            collection_id=str(uuid.uuid4()),
            entries=[
                Score(
                    score_id="ss_overlap",
                    value=round(sum(matches) / count, 4),
                    subjects=[],
                    details={
                        "matched": sum(matches),
                        "compared": count,
                        "coverage": count / maximum if maximum else 1.0,
                        "per_residue_match": matches,
                        "coarse": use_coarse,
                    },
                )
            ],
        )
    }
