"""ASGI fixture app with controlled providers at explicit injection seams.

This module is test-only and isn't included in built backend artifacts. The app
still executes the real Workflow through the production FastAPI server and
Execution Engine; only external provider and local-tool boundaries are replaced.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from core.run_context import RunContext
from core.server import create_app
from datatypes import ProteinSequence, ProteinStructure, ScoreCollection
from modules.esm3_generate.module import ESM3GenerateModule
from modules.esmfold2_fold.module import ESMFold2FoldModule
from modules.proteinmpnn.adapter import ProteinMPNNDesignRequest
from modules.proteinmpnn.module_design import ProteinMPNNDesignModule
from modules.stub import EchoModule
from tests.fixtures.canonical_3gb1 import (
    ControlledDSSPModule,
    ControlledESMClient,
    ControlledFoldProvider,
    ControlledProteinMPNNProvider,
)


TELEMETRY_ENV = "PROTEIN_WORKBENCH_DETERMINISTIC_PROVIDER_CALLS"
ALLOWED_RUNTIME_MODULE_IDS = frozenset({
    "import.structure",
    "prompt.build_residue_layout",
    "prompt.apply_residue_edits",
    "prompt.random_mask",
    "prompt.random_insert_masked",
    "compute.dssp",
    "prompt.override_residue_track",
    "prompt.assemble_protein_prompt",
    "esm3.generate",
    "esmfold2.fold",
    "structure.pairwise_align",
    "structure.batch_tm_score",
    "scoring.merge",
    "selection.weighted_rank",
    "selection.top_k",
    "prompt.random_fixed_positions",
    "proteinmpnn.design",
    "export.structure",
    "stub.echo",
})


def _no_sleep(_: float) -> None:
    """Keep deterministic providers independent of wall-clock pacing."""


def _record_fixture_provider_call(operation: str) -> None:
    telemetry = Path(os.environ[TELEMETRY_ENV])
    telemetry.parent.mkdir(parents=True, exist_ok=True)
    with telemetry.open("a", encoding="utf-8") as calls:
        calls.write(f"{operation}\n")
    telemetry.chmod(0o600)


class DeterministicProviderError(RuntimeError):
    """Safe fixture-provider failure observed through public diagnostics."""

    kind = "provider_failure"


class RecordedESMClient(ControlledESMClient):
    """Controlled ESM client with fixture-boundary call telemetry."""

    def generate(self, protein: Any, config: Any) -> Any:
        _record_fixture_provider_call(f"esm3:{config.track}")
        return super().generate(protein, config)


class RecordedFoldProvider(ControlledFoldProvider):
    """Controlled folding provider with stable canonical call indices."""

    def __call__(
        self,
        sequence: ProteinSequence,
        *,
        model_name: str,
        include_pae: bool,
        include_embeddings: bool,
        project_dir: str,
        call_details: dict[str, object] | None = None,
    ) -> tuple[ProteinStructure, ScoreCollection]:
        parent_id = str((call_details or {}).get("parent_candidate_id", ""))
        if self.calls == 0 and parent_id.startswith("mpnn-"):
            self.calls = 10
        _record_fixture_provider_call("esmfold2:fold")
        return super().__call__(
            sequence,
            model_name=model_name,
            include_pae=include_pae,
            include_embeddings=include_embeddings,
            project_dir=project_dir,
            call_details=call_details,
        )


class RecordedProteinMPNNProvider(ControlledProteinMPNNProvider):
    """Controlled ProteinMPNN provider with fixture call telemetry."""

    def design(
        self,
        request: ProteinMPNNDesignRequest,
    ) -> tuple[list[ProteinSequence], list[float]]:
        _record_fixture_provider_call("proteinmpnn:design")
        return super().design(request)


class RecordedDSSPModule(ControlledDSSPModule):
    """Controlled local-tool boundary with fixture call telemetry."""

    async def run_async(
        self,
        inputs: dict[str, object],
        parameters: dict[str, object],
        context: RunContext,
    ) -> dict[str, object]:
        _record_fixture_provider_call("mkdssp:secondary_structure")
        return await super().run_async(inputs, parameters, context)


class DeterministicEchoModule(EchoModule):
    """Fixture-only provider behavior behind the existing Echo contract."""

    async def run_async(
        self,
        inputs: dict[str, Any],
        parameters: dict[str, Any],
        context: RunContext,
    ) -> dict[str, Any]:
        prefix = str(parameters.get("prefix", ""))
        if prefix.startswith("fixture:"):
            operation = prefix.removeprefix("fixture:")
            _record_fixture_provider_call(f"controlled-provider:{operation}")
            context.record_provider_call(
                "controlled-provider",
                operation,
                model="deterministic-acceptance",
            )
        if prefix == "fixture:fail":
            raise DeterministicProviderError("fixture-secret-must-not-leak")
        if prefix == "fixture:block":
            await asyncio.Event().wait()
        return super().run(inputs, parameters, context)


def _recorded_esm_client(model_name: str, project_dir: str) -> RecordedESMClient:
    del model_name, project_dir
    return RecordedESMClient()


def _esm3_module() -> ESM3GenerateModule:
    return ESM3GenerateModule(client_factory=_recorded_esm_client)


def _fold_module() -> ESMFold2FoldModule:
    return ESMFold2FoldModule(
        fold_provider=RecordedFoldProvider(),
        sleep=_no_sleep,
    )


def _proteinmpnn_module() -> ProteinMPNNDesignModule:
    return ProteinMPNNDesignModule(provider=RecordedProteinMPNNProvider())


app = create_app(
    module_factory_overrides={
        "compute.dssp": RecordedDSSPModule,
        "esm3.generate": _esm3_module,
        "esmfold2.fold": _fold_module,
        "proteinmpnn.design": _proteinmpnn_module,
        "stub.echo": DeterministicEchoModule,
    },
    runtime_module_allowlist=ALLOWED_RUNTIME_MODULE_IDS,
)
