"""Deterministic red reproductions for post-handoff backend findings."""

from __future__ import annotations

import asyncio
import hashlib
import json
import stat
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from core.executor import Executor
from core.graph import Workflow, WorkflowEdge, WorkflowNode
from core.project import ProjectManager
from core.recovery import RunRecoveryService
from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
    Score,
    ScoreCollection,
)
from modules.export_sequence.module import ExportSequenceModule
from modules.import_sequence.module import ImportSequenceModule
from tests.deterministic_acceptance.backend_client import (
    BackendAcceptanceClient,
)


PROJECT_ID = "canonical-3gb1"
SEQUENCE_EXPORT_PAYLOAD = b">exported_sequence len=10\nMTYKLILNGK\n"
SEQUENCE_EXPORT_SHA256 = (
    "fc0335349b5216471f859559c7a35670776bbba860962f34621d12c206b89e5b"
)
REQUIRED_FINAL_SECONDARY_STRUCTURE = (
    "EEEEEEEEEEEEEEEEEEE___HHHHHHHH____"
    "EEEEEEEEEEEEEEEEEEEEEE_______________"
)

pytestmark = pytest.mark.repair_findings


def _prompt_records(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line
    ]


def test_canonical_provider_prompt_keeps_absolute_secondary_structure_intent(
    backend_client: BackendAcceptanceClient,
    provider_prompt_probe: Path,
) -> None:
    """Insertion must not shift final-layout E/H positions at the provider."""
    observed_by_seed: dict[int, str] = {}
    for seed in (4242, 7):
        accepted = backend_client.run_saved(PROJECT_ID, seed=seed)
        run_id = accepted["run_id"]
        backend_client.receive_run_events(PROJECT_ID, run_id)
        prompts = {
            str(record["secondary_structure"])
            for record in _prompt_records(provider_prompt_probe)
            if record.get("run_id") == run_id
            and record.get("track") == "sequence"
        }
        assert len(prompts) == 1
        observed_by_seed[seed] = prompts.pop()

    assert observed_by_seed == {
        4242: REQUIRED_FINAL_SECONDARY_STRUCTURE,
        7: REQUIRED_FINAL_SECONDARY_STRUCTURE,
    }, (
        "Observed insertion-shifted provider prompts; repaired behavior "
        "must keep the same 71-position absolute E/H layout for both seeds."
    )


def _sequence_export_workflow() -> Workflow:
    workflow = Workflow()
    workflow.add_node(WorkflowNode(
        node_id="import-sequence",
        module_id="import.sequence",
        module_version="1.0.0",
        parameters={"file_path": "source.fasta"},
    ))
    workflow.add_node(WorkflowNode(
        node_id="export-sequence",
        module_id="export.sequence",
        module_version="2.0.0",
        parameters={"filename": "out.fa"},
    ))
    workflow.add_edge(WorkflowEdge(
        source_node_id="import-sequence",
        source_port="sequence",
        target_node_id="export-sequence",
        target_port="sequence",
    ))
    return workflow


def _run_sequence_export(
    manager: ProjectManager,
    project_id: str,
    run_id: str,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    result = asyncio.run(Executor().execute(
        _sequence_export_workflow(),
        {
            "import.sequence": ImportSequenceModule(),
            "export.sequence": ExportSequenceModule(),
        },
        str(manager.project_dir(project_id)),
        run_id,
        seed=4242,
        project_manager=manager,
        project_id=project_id,
    ))
    manifest = RunRecoveryService(manager).manifest(project_id, run_id)
    outputs = RunRecoveryService(manager).outputs(project_id, run_id)
    return Path(result["export-sequence"]["file_path"]), manifest, outputs


def _export_cache_fact(
    manifest: dict[str, Any],
) -> dict[str, Any]:
    matches = [
        fact
        for fact in manifest["cache"]
        if fact["node_id"] == "export-sequence"
    ]
    assert len(matches) == 1
    return matches[0]


def test_cached_sequence_export_stays_in_the_consuming_run_namespace(
    tmp_path: Path,
) -> None:
    """A cached second run must materialize its own exported FASTA."""
    manager = ProjectManager(tmp_path / "projects")
    project = manager.create("Sequence export")
    source = manager.input_path(project.id, "source.fasta")
    source.write_text(">source\nMTYKLILNGK\n")
    first_path, first_manifest, first_outputs = _run_sequence_export(
        manager, project.id, "run-1",
    )
    second_path, second_manifest, second_outputs = _run_sequence_export(
        manager, project.id, "run-2",
    )

    assert first_path == manager.output_path(project.id, "run-1", "out.fa")
    assert second_path == manager.output_path(project.id, "run-2", "out.fa")
    assert first_path.read_bytes() == SEQUENCE_EXPORT_PAYLOAD
    assert second_path.read_bytes() == SEQUENCE_EXPORT_PAYLOAD
    expected_artifact = {
        "node_id": "export-sequence",
        "output_port": "file_path",
        "artifact_kind": "standalone",
        "reference": "out.fa",
        "size": len(SEQUENCE_EXPORT_PAYLOAD),
        "sha256": SEQUENCE_EXPORT_SHA256,
    }
    assert first_outputs["artifacts"] == [expected_artifact]
    assert second_outputs["artifacts"] == [expected_artifact]
    first_cache = _export_cache_fact(first_manifest)
    second_cache = _export_cache_fact(second_manifest)
    assert (first_cache["outcome"], first_cache["published"]) == (
        "miss", False,
    )
    assert (second_cache["outcome"], second_cache["published"]) == (
        "miss", False,
    )
    assert first_cache["cache_key"] == second_cache["cache_key"]


def _configure_small_reviewed_simplefold_models(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
) -> None:
    from modules import simplefold_adapter

    artifact_bytes = {
        name: f"reviewed:{name}".encode()
        for name in (
            "simplefold_100M.ckpt",
            "simplefold_360M.ckpt",
            "simplefold_1.6B.ckpt",
            "plddt.ckpt",
            "ccd.pkl",
            "boltz1_conf.ckpt",
        )
    }
    main_names = tuple(
        name for name in artifact_bytes if name.endswith(".ckpt")
        and name not in {"boltz1_conf.ckpt"}
    )
    auxiliary_names = ("ccd.pkl", "boltz1_conf.ckpt")
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ARTIFACT_IDENTITIES",
        {
            name: {"bytes": len(artifact_bytes[name])}
            for name in main_names
        },
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_AUXILIARY_ARTIFACTS",
        auxiliary_names,
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_ARTIFACT_SHA256",
        {
            name: hashlib.sha256(content).hexdigest()
            for name, content in artifact_bytes.items()
        },
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "SIMPLEFOLD_EXECUTION_ENABLED",
        True,
    )
    monkeypatch.setattr(
        simplefold_adapter,
        "validate_installed_provider_checkout",
        lambda *_: None,
    )
    root.mkdir()
    for name, content in artifact_bytes.items():
        (root / name).write_bytes(content)
    monkeypatch.setenv(
        "PROTEIN_WORKBENCH_SIMPLEFOLD_MODEL_ROOT",
        str(root),
    )


def test_simplefold_collection_items_use_independent_staging_namespaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Both public collection paths must survive their second item."""
    from modules import simplefold_adapter
    from modules.simplefold_evaluate.module import SimpleFoldEvaluateModule
    from modules.simplefold_fold.module import SimpleFoldFoldModule

    _configure_small_reviewed_simplefold_models(
        monkeypatch,
        tmp_path / "reviewed-models",
    )

    pdb = (
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000"
        "  1.00  0.00           C\nEND\n"
    )
    fold_calls: list[dict[str, object]] = []
    evaluate_calls: list[dict[str, object]] = []

    def staged_fold(**kwargs: object) -> tuple[
        list[ProteinStructure],
        ScoreCollection,
    ]:
        fold_calls.append(kwargs)
        working_dir = Path(str(kwargs["project_dir"]))
        assert working_dir.is_dir()
        assert stat.S_IMODE(working_dir.stat().st_mode) == 0o700
        simplefold_adapter.validated_simplefold_model_dir(
            working_dir
        )
        return (
            [ProteinStructure(pdb_string=pdb, source="simplefold")],
            ScoreCollection(
                collection_id="fold-scores",
                entries=[Score(
                    score_id="plddt",
                    value=0.8,
                    subjects=["provider-placeholder"],
                    details={"sample_index": 0},
                )],
            ),
        )

    def staged_evaluate(**kwargs: object) -> ScoreCollection:
        evaluate_calls.append(kwargs)
        working_dir = Path(str(kwargs["project_dir"]))
        assert working_dir.is_dir()
        assert stat.S_IMODE(working_dir.stat().st_mode) == 0o700
        simplefold_adapter.validated_simplefold_model_dir(
            working_dir
        )
        return ScoreCollection(
            collection_id="evaluation-scores",
            entries=[Score(
                score_id="plddt",
                value=0.8,
                subjects=["provider-placeholder"],
            )],
        )

    monkeypatch.setattr(simplefold_adapter, "fold_sequence", staged_fold)
    monkeypatch.setattr(
        simplefold_adapter,
        "evaluate_structure",
        staged_evaluate,
    )
    sequences = CandidateCollection(
        collection_id="two-sequences",
        item_type="protein.sequence",
        items=[
            Candidate(
                candidate_id=f"sequence-{index}",
                data=ProteinSequence(sequence="AA"),
            )
            for index in range(2)
        ],
    )
    structures = CandidateCollection(
        collection_id="two-structures",
        item_type="protein.structure",
        items=[
            Candidate(
                candidate_id=f"structure-{index}",
                data=ProteinStructure(pdb_string=pdb),
            )
            for index in range(2)
        ],
    )

    observed: dict[str, str] = {}
    fold_context = RunContext(
        str(tmp_path),
        "fold",
        run_id="fold-run",
    )
    try:
        fold_result = SimpleFoldFoldModule().run(
            {"candidates": sequences},
            {},
            fold_context,
        )
    except FileExistsError as error:
        expected_collision = (
            Path(str(fold_context.temp_dir)) / "verified_provider"
        )
        if Path(str(error.filename)) != expected_collision:
            raise
        observed["fold"] = (
            f"known staging collision: {expected_collision}"
        )
    else:
        folded_candidates = fold_result["candidates"].items
        assert [
            candidate.parent_ids
            for candidate in folded_candidates
        ] == [["sequence-0"], ["sequence-1"]]
        assert [
            score.subjects
            for score in fold_result["scores"].entries
        ] == [
            [candidate.candidate_id]
            for candidate in folded_candidates
        ]
        observed["fold"] = "completed with correct lineage"

    evaluate_context = RunContext(
        str(tmp_path),
        "evaluate",
        run_id="evaluate-run",
    )
    try:
        evaluate_result = SimpleFoldEvaluateModule().run(
            {"candidates": structures},
            {},
            evaluate_context,
        )
    except FileExistsError as error:
        expected_collision = (
            Path(str(evaluate_context.temp_dir)) / "verified_provider"
        )
        if Path(str(error.filename)) != expected_collision:
            raise
        observed["evaluate"] = (
            f"known staging collision: {expected_collision}"
        )
    else:
        assert [
            score.subjects
            for score in evaluate_result["scores"].entries
        ] == [["structure-0"], ["structure-1"]]
        observed["evaluate"] = "completed with correct subjects"

    assert observed == {
        "fold": "completed with correct lineage",
        "evaluate": "completed with correct subjects",
    }, (
        "Observed fixed-name staging collisions on the second collection "
        "item; repaired behavior requires invocation-isolated staging."
    )
    assert [
        call["call_details"]
        for call in fold_calls
    ] == [
        {
            "parent_candidate_id": "sequence-0",
            "candidate_ids": ["sfold-fold-run-sequence-0-0"],
        },
        {
            "parent_candidate_id": "sequence-1",
            "candidate_ids": ["sfold-fold-run-sequence-1-0"],
        },
    ]
    assert [
        call["call_details"]
        for call in evaluate_calls
    ] == [
        {"candidate_id": "structure-0"},
        {"candidate_id": "structure-1"},
    ]
    fold_working_dirs = [
        Path(str(call["project_dir"]))
        for call in fold_calls
    ]
    evaluate_working_dirs = [
        Path(str(call["project_dir"]))
        for call in evaluate_calls
    ]
    assert len(set(fold_working_dirs)) == 2
    assert len(set(evaluate_working_dirs)) == 2
    assert all(
        path.parent == Path(str(fold_context.temp_dir))
        and not path.exists()
        and not path.is_symlink()
        for path in fold_working_dirs
    )
    assert all(
        path.parent == Path(str(evaluate_context.temp_dir))
        and not path.exists()
        and not path.is_symlink()
        for path in evaluate_working_dirs
    )


def test_public_manifest_contains_every_scientific_call(
    backend_client: BackendAcceptanceClient,
) -> None:
    """The run manifest itself must own all 89 scientific call facts."""
    accepted = backend_client.run_saved(PROJECT_ID, seed=4242)
    run_id = accepted["run_id"]
    backend_client.receive_run_events(PROJECT_ID, run_id)
    manifest = backend_client.manifest(PROJECT_ID, run_id)

    observed = Counter(
        (record["provider"], record["operation"])
        for record in manifest["providers"]["calls"]
    )
    required = Counter({
        ("local_open", "generate(track=sequence)"): 10,
        ("local_open", "generate(track=structure)"): 10,
        ("biohub", "fold"): 25,
        ("controlled-proteinmpnn", "design_sequences"): 3,
        ("mkdssp", "secondary_structure"): 1,
        ("biopython-svd", "structure_align"): 20,
        ("tmtools", "tm_score"): 20,
    })
    assert observed == required, (
        "Observed an incomplete public run manifest; repaired behavior must "
        "source-bind all 89 scientific calls without an outer acceptance "
        "evidence stream."
    )
    scientific_calls = [
        record
        for record in manifest["providers"]["calls"]
        if record["provider"] in {"biopython-svd", "tmtools"}
    ]
    assert [
        (
            record["details"]["node_id"],
            record["provider"],
            record["operation"],
        )
        for record in scientific_calls
    ] == [
        ("align_3gb1", "biopython-svd", "structure_align")
    ] * 10 + [
        ("align_pw", "biopython-svd", "structure_align")
    ] * 10 + [
        ("tm_3gb1", "tmtools", "tm_score")
    ] * 10 + [
        ("tm_esm3", "tmtools", "tm_score")
    ] * 10
    assert all(
        record["details"]["actual_call"] is True
        and record["details"]["call_count"] == 1
        and record["details"]["readiness"] == "ready_at_call_boundary"
        and record["details"]["cache_decision"]
        == "bypassed_fresh_direct_call"
        and record["details"]["result"]["status"] == "succeeded"
        and record["details"]["candidate_id"]
        for record in scientific_calls
    )
    assert all(
        len(record["details"]["input_identity"].get(
            "tm_align_input_sha256",
            record["details"]["input_identity"].get(
                "reference_pdb_sha256",
                "",
            ),
        )) == 64
        for record in scientific_calls
    )
    manifest_text = json.dumps(manifest, sort_keys=True)
    assert "authorization" not in manifest_text.lower()
    assert "cookie" not in manifest_text.lower()


def test_public_manifest_contains_every_readiness_fact(
    backend_client: BackendAcceptanceClient,
) -> None:
    """The run manifest itself must own all 6 readiness facts."""
    accepted = backend_client.run_saved(PROJECT_ID, seed=4242)
    run_id = accepted["run_id"]
    backend_client.receive_run_events(PROJECT_ID, run_id)
    manifest = backend_client.manifest(PROJECT_ID, run_id)

    observed = Counter(
        record["provider"]
        for record in manifest["providers"]["readiness"]
    )
    required = Counter({
        "biohub": 1,
        "local_open": 1,
        "controlled-proteinmpnn": 1,
        "mkdssp": 1,
        "biopython-svd": 1,
        "tmtools": 1,
    })
    assert observed == required, (
        "Observed an incomplete public run manifest; repaired behavior must "
        "source-bind all 6 readiness records separately from calls."
    )
    assert len(manifest["providers"]["calls"]) == 89
    assert all(
        record["status"] == "ready"
        and record["ready"] is True
        and record["provider_identity"]
        and record["source"]["kind"] == "workflow_required_boundary"
        and record["source"]["node_ids"]
        and record["source"]["module_ids"]
        for record in manifest["providers"]["readiness"]
    )
