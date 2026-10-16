"""Public diagnostics owned by scientific protein input parsing."""

from core.operation import OperationDiagnosticError


class ProteinInputError(OperationDiagnosticError):
    """An explicitly selected FASTA/PDB/mmCIF input cannot be scientifically read."""
