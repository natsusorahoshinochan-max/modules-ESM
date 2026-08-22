"""Durable transaction byte stores for the Run Evidence Ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from core.project.storage import write_new_file_durable


class LedgerStore(Protocol):
    """Read and persist canonical transaction bytes for one Run."""

    def read_transactions(
        self,
        *,
        root: Path,
        relative_parts: tuple[str, ...],
    ) -> tuple[tuple[str, bytes], ...]: ...

    def publish(
        self,
        *,
        root: Path,
        relative_parts: tuple[str, ...],
        payload: bytes,
    ) -> None: ...


class FilesystemLedgerStore:
    """Atomic durable filesystem adapter used by production Runs."""

    def read_transactions(
        self,
        *,
        root: Path,
        relative_parts: tuple[str, ...],
    ) -> tuple[tuple[str, bytes], ...]:
        ledger_directory = root.joinpath(*relative_parts)
        if not ledger_directory.is_dir():
            return ()
        return tuple(
            (path.name, path.read_bytes())
            for path in sorted(ledger_directory.glob("*.json"))
        )

    def publish(
        self,
        *,
        root: Path,
        relative_parts: tuple[str, ...],
        payload: bytes,
    ) -> None:
        write_new_file_durable(root, relative_parts, payload)


class InMemoryLedgerStore:
    """Real deterministic byte store for owner tests and local composition."""

    def __init__(self) -> None:
        self._transactions: dict[tuple[str, ...], bytes] = {}

    def publish(
        self,
        *,
        root: Path,
        relative_parts: tuple[str, ...],
        payload: bytes,
    ) -> None:
        del root
        if relative_parts in self._transactions:
            raise FileExistsError("Ledger transaction already exists")
        self._transactions[relative_parts] = bytes(payload)

    def read_transactions(
        self,
        *,
        root: Path,
        relative_parts: tuple[str, ...],
    ) -> tuple[tuple[str, bytes], ...]:
        del root
        prefix_length = len(relative_parts)
        return tuple(
            (parts[-1], payload)
            for parts, payload in sorted(self._transactions.items())
            if parts[:prefix_length] == relative_parts
            and len(parts) == prefix_length + 1
        )

    def read(self, relative_parts: tuple[str, ...]) -> bytes:
        return self._transactions[relative_parts]

    @property
    def transactions(self) -> tuple[tuple[tuple[str, ...], bytes], ...]:
        return tuple(sorted(self._transactions.items()))
