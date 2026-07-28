"""Tests for folding modules (ticket 08)."""

import os
from unittest.mock import MagicMock, patch

import pytest

from core.run_context import RunContext
from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
    Score,
    ScoreCollection,
)

# ── Shared test data ─────────────────────────────────────────────────

SAMPLE_PDB = """\
HEADER    MOCK
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00
ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00  0.00
ATOM      3  C   ALA A   1       2.009   1.421   0.000  1.00  0.00
ATOM      4  O   ALA A   1       1.227   2.358   0.000  1.00  0.00
ATOM      5  CB  ALA A   1       2.009  -0.710   1.229  1.00  0.00
ATOM      6  N   GLY A   2       3.346   1.542   0.000  1.00  0.00
ATOM      7  CA  GLY A   2       3.992   2.855   0.000  1.00  0.00
ATOM      8  C   GLY A   2       3.546   3.671  -1.207  1.00  0.00
ATOM      9  O   GLY A   2       3.562   3.152  -2.317  1.00  0.00
ATOM     10  N   SER A   3       3.121   4.909  -0.961  1.00  0.00
ATOM     11  CA  SER A   3       2.667   5.790  -2.041  1.00  0.00
ATOM     12  C   SER A   3       3.797   6.737  -2.430  1.00  0.00
ATOM     13  O   SER A   3       4.971   6.386  -2.386  1.00  0.00
END
"""


def _make_mock_fold_result() -> tuple[ProteinStructure, ScoreCollection]:
    """Create a mock fold result for ESMFold2."""
    struct = ProteinStructure(pdb_string=SAMPLE_PDB, source="esmfold2")
    scores = ScoreCollection(
        collection_id="mock-scores",
        entries=[
            Score(score_id="ptm", value=0.85, subjects=["mock-cid"]),
            Score(score_id="plddt", value=0.78, subjects=["mock-cid"],
                  details={"per_residue": [0.9, 0.8, 0.7]}),
        ],
    )
    return struct, scores


def _make_mock_sf_fold_result() -> tuple[list[ProteinStructure], ScoreCollection]:
    """Create a mock SimpleFold result."""
    struct = ProteinStructure(pdb_string=SAMPLE_PDB, source="simplefold")
    scores = ScoreCollection(
        collection_id="mock-sf-scores",
        entries=[
            Score(score_id="plddt", value=0.72, subjects=["mock-cid"],
                  details={"per_residue": [0.8, 0.7, 0.6], "sample_index": 0}),
        ],
    )
    return [struct], scores


def _make_mock_sf_eval_result() -> ScoreCollection:
    """Create a mock SimpleFold evaluate result."""
    return ScoreCollection(
        collection_id="mock-sf-eval",
        entries=[
            Score(score_id="plddt", value=0.75, subjects=["mock-cid"],
                  details={"per_residue": [0.85, 0.75, 0.65], "model": "simplefold_360M"}),
        ],
    )


# ── ESMFold2 Adapter ─────────────────────────────────────────────────

class TestESMFold2Adapter:
    def test_read_biohub_token_found(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        from modules.esmfold2_adapter import read_biohub_token

        token_path = tmp_path / "esmkey.txt"
        token_path.write_text("configured-test-token")
        token_path.chmod(0o600)
        monkeypatch.setenv(
            "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",
            str(token_path),
        )
        token = read_biohub_token()
        assert token == "configured-test-token"

    def test_explicit_biohub_token_path_never_falls_back(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
    ) -> None:
        from modules.esmfold2_adapter import read_biohub_token

        implicit_root = tmp_path / "keys"
        implicit_root.mkdir()
        implicit_token = implicit_root / "esmkey.txt"
        implicit_token.write_text("implicit-token")
        implicit_token.chmod(0o600)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(
            "PROTEIN_WORKBENCH_BIOHUB_TOKEN_FILE",
            str(tmp_path / "missing-token"),
        )

        with pytest.raises(FileNotFoundError, match="not found"):
            read_biohub_token()

    def test_biohub_token_metadata_fails_closed(
        self,
        tmp_path,
    ) -> None:
        from core.provider_contract import validate_biohub_token_file

        public_token = tmp_path / "public-token"
        public_token.write_text("token")
        public_token.chmod(0o644)
        with pytest.raises(FileNotFoundError, match="unavailable"):
            validate_biohub_token_file(public_token)

        private_token = tmp_path / "private-token"
        private_token.write_text("token")
        private_token.chmod(0o600)
        symlink = tmp_path / "token-link"
        symlink.symlink_to(private_token)
        with pytest.raises(FileNotFoundError, match="unavailable"):
            validate_biohub_token_file(symlink)

        hardlink = tmp_path / "token-hardlink"
        os.link(private_token, hardlink)
        with pytest.raises(FileNotFoundError, match="unavailable"):
            validate_biohub_token_file(private_token)

    def test_esm_protein_to_pdb_string(self) -> None:
        from modules.esmfold2_adapter import _esm_protein_to_pdb_string
        mock_ep = MagicMock()
        mock_chain = MagicMock()
        mock_chain.to_pdb_string.return_value = SAMPLE_PDB
        mock_ep.to_protein_chain.return_value = mock_chain
        mock_chain.infer_oxygen.return_value = mock_chain

        result = _esm_protein_to_pdb_string(mock_ep)
        assert result == SAMPLE_PDB
        mock_ep.to_protein_chain.assert_called_once()
        mock_chain.infer_oxygen.assert_called_once()

    def test_fold_sequence_mocked(self) -> None:
        from modules.esmfold2_adapter import fold_sequence
        mock_ep = MagicMock()
        mock_ep.sequence = "AGS"
        mock_ep.ptm = None
        mock_ep.plddt = None
        mock_ep.pae = None
        mock_ep.output_embedding_pair_pooled = None

        mock_chain = MagicMock()
        mock_chain.to_pdb_string.return_value = SAMPLE_PDB
        mock_ep.to_protein_chain.return_value = mock_chain
        mock_chain.infer_oxygen.return_value = mock_chain

        mock_client = MagicMock()
        mock_client.fold.return_value = mock_ep

        with (
            patch("modules.esmfold2_adapter.read_biohub_token", return_value="test-token"),
            patch("esm.sdk.forge.SequenceStructureForgeInferenceClient",
                  return_value=mock_client),
        ):
            seq = ProteinSequence(sequence="AGS")
            struct, scores = fold_sequence(seq)

        assert isinstance(struct, ProteinStructure)
        assert SAMPLE_PDB in struct.pdb_string
        assert struct.source == "esmfold2"
        assert isinstance(scores, ScoreCollection)

    def test_fold_sequence_with_scores(self) -> None:
        from modules.esmfold2_adapter import fold_sequence
        import torch
        mock_ep = MagicMock()
        mock_ep.sequence = "AGS"
        mock_ep.ptm = torch.tensor([0.85])
        mock_ep.plddt = torch.tensor([0.9, 0.8, 0.7])
        mock_ep.pae = None
        mock_ep.output_embedding_pair_pooled = None

        mock_chain = MagicMock()
        mock_chain.to_pdb_string.return_value = SAMPLE_PDB
        mock_ep.to_protein_chain.return_value = mock_chain
        mock_chain.infer_oxygen.return_value = mock_chain

        mock_client = MagicMock()
        mock_client.fold.return_value = mock_ep

        with (
            patch("modules.esmfold2_adapter.read_biohub_token", return_value="test-token"),
            patch("esm.sdk.forge.SequenceStructureForgeInferenceClient",
                  return_value=mock_client),
        ):
            seq = ProteinSequence(sequence="AGS")
            struct, scores = fold_sequence(seq)

        ptm_entry = [s for s in scores.entries if s.score_id == "ptm"]
        assert len(ptm_entry) == 1
        assert ptm_entry[0].value == pytest.approx(0.85)

        plddt_entry = [s for s in scores.entries if s.score_id == "plddt"]
        assert len(plddt_entry) == 1
        assert abs(plddt_entry[0].value - 0.8) < 0.01

    def test_fold_sequence_error_propagation(self) -> None:
        from modules.esmfold2_adapter import fold_sequence
        from esm.sdk.api import ESMProteinError

        mock_client = MagicMock()
        mock_client.fold.return_value = ESMProteinError(400, "Bad request")

        with (
            patch("modules.esmfold2_adapter.read_biohub_token", return_value="test-token"),
            patch("esm.sdk.forge.SequenceStructureForgeInferenceClient",
                  return_value=mock_client),
        ):
            seq = ProteinSequence(sequence="AGS")
            with pytest.raises(ValueError, match="ESMFold2 fold failed"):
                fold_sequence(seq)


# ── ESMFold2 Fold Module ─────────────────────────────────────────────

class TestESMFold2FoldModule:
    def test_folds_single_sequence(self) -> None:
        from modules.esmfold2_fold.module import ESMFold2FoldModule
        mock_struct, mock_scores = _make_mock_fold_result()

        with patch("modules.esmfold2_adapter.fold_sequence",
                   return_value=(mock_struct, mock_scores)):
            mod = ESMFold2FoldModule(sleep=lambda _: None)
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            seq = ProteinSequence(sequence="AGS")
            result = mod.run(
                {"sequence": seq},
                {"model_name": "esmfold2-fast-2026-05"},
                ctx,
            )

        candidates = result["candidates"]
        assert isinstance(candidates, CandidateCollection)
        assert len(candidates) == 1
        assert candidates.item_type == "protein.structure"
        c = candidates.items[0]
        assert isinstance(c.data, ProteinStructure)
        assert c.metadata["backend"] == "esmfold2"
        assert c.parent_ids == ["seq-0"]

    def test_folds_candidate_collection(self) -> None:
        from modules.esmfold2_fold.module import ESMFold2FoldModule
        mock_struct, mock_scores = _make_mock_fold_result()

        with patch("modules.esmfold2_adapter.fold_sequence",
                   return_value=(mock_struct, mock_scores)):
            mod = ESMFold2FoldModule(sleep=lambda _: None)
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            coll = CandidateCollection(
                collection_id="test-coll",
                item_type="protein.sequence",
                items=[
                    Candidate(
                        candidate_id="c1",
                        data=ProteinSequence(sequence="AGS"),
                        parent_ids=["p1"],
                    ),
                    Candidate(
                        candidate_id="c2",
                        data=ProteinSequence(sequence="WFC"),
                        parent_ids=["p2"],
                    ),
                ],
            )
            result = mod.run(
                {"candidates": coll},
                {},
                ctx,
            )

        candidates = result["candidates"]
        assert len(candidates) == 2
        # Parent lineage preserved
        assert candidates.items[0].parent_ids == ["c1"]
        assert candidates.items[1].parent_ids == ["c2"]

    def test_canonical_batches_keep_twenty_one_calls_over_sixty_seconds(
        self,
    ) -> None:
        from modules.esmfold2_fold.module import ESMFold2FoldModule

        now = [0.0]
        call_starts: list[float] = []

        def advance(seconds: float) -> None:
            now[0] += seconds

        def fold_provider(**kwargs):
            del kwargs
            call_starts.append(now[0])
            return _make_mock_fold_result()

        module = ESMFold2FoldModule(
            fold_provider=fold_provider,
            sleep=advance,
        )
        context = RunContext("/tmp/test", "fold", run_id="test-run")
        for batch_size in (10, 15):
            collection = CandidateCollection(
                collection_id=f"batch-{batch_size}",
                item_type="protein.sequence",
                items=[
                    Candidate(
                        candidate_id=f"candidate-{batch_size}-{index}",
                        data=ProteinSequence(sequence="AGS"),
                    )
                    for index in range(batch_size)
                ],
            )
            module.run({"candidates": collection}, {}, context)

        assert len(call_starts) == 25
        assert all(
            call_starts[index + 20] - call_starts[index] > 60
            for index in range(5)
        )

    def test_wrong_item_type_raises(self) -> None:
        from modules.esmfold2_fold.module import ESMFold2FoldModule
        mod = ESMFold2FoldModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = CandidateCollection(
            collection_id="bad",
            item_type="protein.structure",
            items=[Candidate(candidate_id="c1", data=ProteinStructure(pdb_string=""))],
        )
        with pytest.raises(ValueError, match="protein.sequence"):
            mod.run({"candidates": coll}, {}, ctx)

    def test_no_input_raises(self) -> None:
        from modules.esmfold2_fold.module import ESMFold2FoldModule
        mod = ESMFold2FoldModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="Either 'sequence' or 'candidates'"):
            mod.run({}, {}, ctx)


# ── SimpleFold Adapter ───────────────────────────────────────────────

class TestSimpleFoldAdapter:
    def test_extract_sequence_from_pdb(self) -> None:
        from modules.simplefold_adapter import _extract_sequence_from_pdb
        seq = _extract_sequence_from_pdb(SAMPLE_PDB)
        assert seq == "AGS"

    def test_extract_sequence_from_pdb_empty(self) -> None:
        from modules.simplefold_adapter import _extract_sequence_from_pdb
        seq = _extract_sequence_from_pdb("HEADER EMPTY\nEND\n")
        assert seq == ""


# ── SimpleFold Fold Module ───────────────────────────────────────────

class TestSimpleFoldFoldModule:
    def test_folds_single_sequence(self) -> None:
        from modules.simplefold_fold.module import SimpleFoldFoldModule
        mock_structs, mock_scores = _make_mock_sf_fold_result()

        with patch("modules.simplefold_adapter.fold_sequence",
                   return_value=(mock_structs, mock_scores)):
            mod = SimpleFoldFoldModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            seq = ProteinSequence(sequence="AGS")
            result = mod.run(
                {"sequence": seq},
                {"num_steps": 25, "num_samples": 1},
                ctx,
            )

        candidates = result["candidates"]
        assert len(candidates) == 1
        assert candidates.item_type == "protein.structure"
        c = candidates.items[0]
        assert c.metadata["backend"] == "simplefold"
        assert c.metadata["num_steps"] == 25

    def test_folds_candidate_collection(self) -> None:
        from modules.simplefold_fold.module import SimpleFoldFoldModule
        mock_structs, mock_scores = _make_mock_sf_fold_result()

        with patch("modules.simplefold_adapter.fold_sequence",
                   return_value=(mock_structs, mock_scores)):
            mod = SimpleFoldFoldModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            coll = CandidateCollection(
                collection_id="test-coll",
                item_type="protein.sequence",
                items=[
                    Candidate(
                        candidate_id="c1",
                        data=ProteinSequence(sequence="AGS"),
                    ),
                ],
            )
            result = mod.run({"candidates": coll}, {}, ctx)

        assert len(result["candidates"]) == 1
        assert result["candidates"].items[0].parent_ids == ["c1"]

    def test_num_steps_capped(self) -> None:
        """num_steps is capped at 50 in the adapter; module passes value through."""
        from modules.simplefold_fold.module import SimpleFoldFoldModule
        mock_structs, mock_scores = _make_mock_sf_fold_result()

        with patch("modules.simplefold_adapter.fold_sequence",
                   return_value=(mock_structs, mock_scores)) as mock_fold:
            mod = SimpleFoldFoldModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            seq = ProteinSequence(sequence="AGS")
            mod.run({"sequence": seq}, {"num_steps": 100}, ctx)

            # Module passes the value; adapter caps it
            call_kwargs = mock_fold.call_args.kwargs
            assert call_kwargs["num_steps"] == 100

    def test_maximum_source_ids_produce_a_manifest_safe_candidate_id(
        self,
    ) -> None:
        from core.storage import validate_identifier
        from modules.simplefold_fold.module import SimpleFoldFoldModule

        mock_structs, mock_scores = _make_mock_sf_fold_result()
        parent_id = "p" * 128
        with patch(
            "modules.simplefold_adapter.fold_sequence",
            return_value=(mock_structs, mock_scores),
        ) as mock_fold:
            result = SimpleFoldFoldModule().run(
                {
                    "candidates": CandidateCollection(
                        collection_id="test-coll",
                        item_type="protein.sequence",
                        items=[Candidate(
                            candidate_id=parent_id,
                            data=ProteinSequence(sequence="AGS"),
                        )],
                    ),
                },
                {},
                RunContext("/tmp/test", "n1", run_id="r" * 128),
            )

        candidate = result["candidates"].items[0]
        assert validate_identifier(
            candidate.candidate_id,
            "candidate_id",
        ) == candidate.candidate_id
        assert candidate.parent_ids == [parent_id]
        assert mock_fold.call_args.kwargs["call_details"] == {
            "parent_candidate_id": parent_id,
            "candidate_ids": [candidate.candidate_id],
        }


# ── SimpleFold Evaluate Module ───────────────────────────────────────

class TestSimpleFoldEvaluateModule:
    def test_evaluates_single_structure(self) -> None:
        from modules.simplefold_evaluate.module import SimpleFoldEvaluateModule
        mock_scores = _make_mock_sf_eval_result()

        with patch("modules.simplefold_adapter.evaluate_structure",
                   return_value=mock_scores):
            mod = SimpleFoldEvaluateModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            struct = ProteinStructure(pdb_string=SAMPLE_PDB)
            result = mod.run(
                {"structure": struct},
                {"model_name": "simplefold_360M"},
                ctx,
            )

        scores = result["scores"]
        assert isinstance(scores, ScoreCollection)
        assert len(scores.entries) == 1
        assert scores.entries[0].score_id == "plddt"
        assert scores.entries[0].value == pytest.approx(0.75)

    def test_evaluates_candidate_collection(self) -> None:
        from modules.simplefold_evaluate.module import SimpleFoldEvaluateModule
        mock_scores = _make_mock_sf_eval_result()

        with patch("modules.simplefold_adapter.evaluate_structure",
                   return_value=mock_scores):
            mod = SimpleFoldEvaluateModule()
            ctx = RunContext("/tmp/test", "n1", run_id="test-run")
            coll = CandidateCollection(
                collection_id="test-coll",
                item_type="protein.structure",
                items=[
                    Candidate(
                        candidate_id="c1",
                        data=ProteinStructure(pdb_string=SAMPLE_PDB),
                    ),
                    Candidate(
                        candidate_id="c2",
                        data=ProteinStructure(pdb_string=SAMPLE_PDB),
                    ),
                ],
            )
            result = mod.run({"candidates": coll}, {}, ctx)

        scores = result["scores"]
        assert len(scores.entries) == 2

    def test_wrong_item_type_raises(self) -> None:
        from modules.simplefold_evaluate.module import SimpleFoldEvaluateModule
        mod = SimpleFoldEvaluateModule()
        ctx = RunContext("/tmp/test", "n1")
        coll = CandidateCollection(
            collection_id="bad",
            item_type="protein.sequence",
            items=[Candidate(candidate_id="c1", data=ProteinSequence(sequence="A"))],
        )
        with pytest.raises(ValueError, match="protein.structure"):
            mod.run({"candidates": coll}, {}, ctx)

    def test_no_input_raises(self) -> None:
        from modules.simplefold_evaluate.module import SimpleFoldEvaluateModule
        mod = SimpleFoldEvaluateModule()
        ctx = RunContext("/tmp/test", "n1")
        with pytest.raises(ValueError, match="Either 'structure' or 'candidates'"):
            mod.run({}, {}, ctx)
