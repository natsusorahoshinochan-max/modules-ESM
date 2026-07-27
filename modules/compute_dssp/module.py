"""Compute DSSP: runs mkdssp and produces per-residue DSSP secondary structure codes.

Uses async subprocess execution to avoid blocking the event loop.
"""

import asyncio
from pathlib import Path
import signal
from typing import Any

from core.module_definition import ModuleDefinition
from core.process_control import signal_process_group
from core.run_context import RunContext
from core.workflow_module import WorkflowModule
from datatypes import ProteinStructure, ResidueTrack

# Reuse the mmCIF parser from the prompt DSSP module
from modules.compute_secondary_structure.module import _parse_dssp_mmcif


class ComputeDSSPModule(WorkflowModule):
    def __init__(self) -> None:
        d = Path(__file__).parent / "definition.yaml"
        self._definition = ModuleDefinition.from_yaml(d)

    @property
    def definition(self) -> ModuleDefinition:
        return self._definition

    def run(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        """Synchronous fallback: delegates to async implementation."""
        import asyncio
        return asyncio.run(self.run_async(inputs, parameters, context))

    async def run_async(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        structure: ProteinStructure | None = inputs.get("structure")
        if structure is None:
            raise ValueError("structure input is required")

        dssp_bin = str(parameters.get("dssp_binary", "/opt/homebrew/bin/mkdssp"))
        timeout = int(parameters.get("timeout", 30))
        with context.temporary_file(
            mode="w", suffix=".pdb", delete=False
        ) as tmp:
            tmp.write(structure.pdb_string)
            pdb_path = tmp.name

        try:
            context.record_provider_call(
                "mkdssp",
                "secondary_structure",
                model=Path(dssp_bin).name,
            )
            proc = await asyncio.create_subprocess_exec(
                dssp_bin, pdb_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.CancelledError:
                if proc.returncode is None:
                    signal_process_group(
                        proc.pid,
                        signal.SIGTERM,
                        fallback=proc.terminate,
                    )
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=1)
                    except asyncio.TimeoutError:
                        signal_process_group(
                            proc.pid,
                            signal.SIGKILL,
                            fallback=proc.kill,
                        )
                        await proc.wait()
                raise
            except asyncio.TimeoutError:
                signal_process_group(
                    proc.pid,
                    signal.SIGKILL,
                    fallback=proc.kill,
                )
                await proc.wait()
                raise RuntimeError(
                    f"mkdssp timed out after {timeout}s"
                )

            if proc.returncode != 0:
                err_msg = stderr.decode().strip() if stderr else "unknown error"
                if "No such file" in err_msg or "not found" in err_msg.lower():
                    raise RuntimeError(
                        f"mkdssp binary not found at '{dssp_bin}'. "
                        f"Install mkdssp or set dssp_binary parameter."
                    )
                raise RuntimeError(f"mkdssp failed (exit {proc.returncode}): {err_msg}")

            ss_codes, _ = _parse_dssp_mmcif(stdout.decode())
            track = ResidueTrack(values=ss_codes, sentinel=None)
            return {"secondary_structure_track": track}
        finally:
            Path(pdb_path).unlink(missing_ok=True)
