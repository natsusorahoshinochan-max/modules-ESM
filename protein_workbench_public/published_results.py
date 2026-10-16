"""Public reading composition over published values and their scientific owners."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

from core.catalog.result_reading import ResultReaderDefinition
from core.execution.ledger import V2RunError
from datatypes.candidate import CandidateDataReference

class PublishedResultValue(TypedDict):
    kind: str
    value: dict[str, Any]
    value_content_digest: str


class PublishedResultReader:
    """Keep data identity at its nominal owner; do not reinterpret structures."""

    def __init__(
        self,
        read_value: Callable[..., tuple[dict[str, Any], bytes, tuple[CandidateDataReference, ...]]],
        readers: tuple[ResultReaderDefinition, ...],
    ) -> None:
        self._read_value = read_value
        self._readers = {reader.port_type_id: reader for reader in readers}

    def value(
        self, project_id: str, run_id: str, node_id: str,
        output_port: str, value_index: int,
    ) -> PublishedResultValue:
        metadata, body, _references = self._read_value(
            project_id, run_id, node_id, output_port, value_index,
        )
        type_id = metadata["typed_value"]["port_type"]["contract_id"]
        reader = self._readers.get(type_id)
        if reader is not None:
            return {"kind": reader.kind, "value": reader.read(body),
                    "value_content_digest": metadata["typed_value"]["value_content_digest"]}
        raise V2RunError(
            "malformed_request", "Output has no specialized reading projection",
            details={"field_path": ["output_port"]},
        )
