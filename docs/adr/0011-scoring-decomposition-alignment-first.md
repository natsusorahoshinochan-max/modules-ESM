# Scoring modules: alignment first, then metrics

Structure comparison is decomposed into two stages: structure.align takes two
ProteinStructures and produces a StructureAlignment (residue mapping, rotation,
translation, RMSD, coverage). structure.tm_score and structure.rmsd each take
the StructureAlignment and produce a ScoreCollection.

This lets multiple scoring modules share a single alignment computation. The
alternative (each scorer performing its own alignment internally) would be
simpler for the user (fewer nodes) but would recompute the same superposition
for TM-score and RMSD, and would prevent future scorers from reusing the
alignment.

Implemented via Bio.SVDSuperimposer (alignment), tmtools.tm_align with
pre-computed alignment passed in (TM-score), and direct read of the RMSD
field from StructureAlignment (RMSD).
