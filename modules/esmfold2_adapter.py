"""ESMFold2 adapter: translates ProteinSequence to Biohub /fold request.

Strict single-chain contract. Uses SDK to_protein_chain() +
infer_oxygen() to avoid SDK 3.3.0 to_pdb_string() rendering defect.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import torch

from datatypes import (
    Candidate,
    CandidateCollection,
    ProteinSequence,
    ProteinStructure,
    Score,
    ScoreCollection,
)


def read_biohub_token(project_dir: str | None = None) -> str:
    """Read Biohub API token from keys/esmkey.txt."""
    candidates = [Path("keys/esmkey.txt")]
    if project_dir:
        candidates.append(Path(project_dir) / ".." / ".." / "keys" / "esmkey.txt")
    for p in candidates:
        if p.exists():
            return p.read_text().strip()
    raise FileNotFoundError(
        "Biohub API key not found. Place your token in keys/esmkey.txt"
    )


def _esm_protein_to_pdb_string(esm_protein: Any) -> str:
    """Render ESMProtein to PDB string using single-chain path.

    Uses to_protein_chain() + infer_oxygen() instead of the
    direct to_pdb_string() which has a Biotite res_id casting
    defect in SDK 3.3.0 when residue_index is a float tensor.
    """
    chain = esm_protein.to_protein_chain()
    chain = chain.infer_oxygen()
    return chain.to_pdb_string()


def fold_sequence(
    sequence: ProteinSequence,
    model_name: str = "esmfold2-fast-2026-05",
    include_pae: bool = False,
    include_embeddings: bool = False,
    project_dir: str | None = None,
) -> tuple[ProteinStructure, ScoreCollection]:
    """Fold a single protein sequence using ESMFold2 via Biohub.

    Returns (ProteinStructure, ScoreCollection).

    Raises FileNotFoundError if the Biohub token is missing.
    Raises ValueError if the fold call fails.
    """
    from esm.sdk.forge import SequenceStructureForgeInferenceClient
    from esm.sdk.api import FoldingConfig, ESMProteinError

    token = read_biohub_token(project_dir)

    client = SequenceStructureForgeInferenceClient(
        model=model_name,
        token=token,
    )

    config = FoldingConfig(
        include_pae=include_pae,
        include_embeddings=include_embeddings,
    )

    from core.run_context import RunContext

    RunContext.record_active_provider_call(
        "biohub",
        "fold",
        model=model_name,
    )
    result = client.fold(
        sequence=sequence.sequence,
        model_name=model_name,
        config=config,
    )

    if isinstance(result, ESMProteinError):
        raise ValueError(f"ESMFold2 fold failed: {result}")

    # Render PDB using single-chain path (avoids SDK 3.3.0 rendering defect)
    pdb_string = _esm_protein_to_pdb_string(result)
    structure = ProteinStructure(pdb_string=pdb_string, source="esmfold2")

    # Extract scores
    cid = str(uuid.uuid4())
    scores = _extract_scores(result, cid)

    return structure, scores


def _extract_scores(esm_protein: Any, candidate_id: str) -> ScoreCollection:
    """Extract pTM, pLDDT, and optionally PAE from folded ESMProtein."""
    entries: list[Score] = []

    ptm = getattr(esm_protein, "ptm", None)
    if ptm is not None:
        if isinstance(ptm, torch.Tensor):
            ptm_val = float(ptm.detach().cpu().flatten()[0])
        else:
            ptm_val = float(ptm)
        entries.append(Score(score_id="ptm", value=ptm_val, subjects=[candidate_id]))

    plddt = getattr(esm_protein, "plddt", None)
    if plddt is not None:
        if isinstance(plddt, torch.Tensor):
            plddt_vals = plddt.detach().cpu().flatten().tolist()
            mean_plddt = sum(plddt_vals) / len(plddt_vals) if plddt_vals else 0.0
        else:
            mean_plddt = float(plddt)
        entries.append(Score(
            score_id="plddt",
            value=mean_plddt,
            subjects=[candidate_id],
            details={"per_residue": plddt_vals if isinstance(plddt, torch.Tensor) else None},
        ))

    pae = getattr(esm_protein, "pae", None)
    if pae is not None:
        if isinstance(pae, torch.Tensor):
            pae_arr = pae.detach().cpu().numpy()
            # Shape should be (L, L) per product contract
            if pae_arr.ndim != 2:
                raise ValueError(
                    f"Unexpected PAE shape {pae_arr.shape}, expected (L,L)"
                )
            entries.append(Score(
                score_id="pae",
                value=0.0,  # PAE is a matrix, not a scalar summary; value is placeholder
                subjects=[candidate_id],
                details={"matrix": pae_arr.tolist()},
            ))

    embedding_pair = getattr(esm_protein, "output_embedding_pair_pooled", None)
    if embedding_pair is not None:
        if isinstance(embedding_pair, torch.Tensor):
            emb_arr = embedding_pair.detach().cpu().numpy()
            entries.append(Score(
                score_id="embedding_pair_pooled",
                value=0.0,  # Embedding is not a scalar
                subjects=[candidate_id],
                details={"shape": list(emb_arr.shape)},
            ))

    return ScoreCollection(
        collection_id=str(uuid.uuid4()),
        entries=entries,
    )
