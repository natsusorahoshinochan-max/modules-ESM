"""Artifact publication intent projected from admitted output values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from core.operation import AdmittedPort, ArtifactPayload


ArtifactKind = Literal["standalone", "candidate"]


@dataclass(frozen=True, slots=True)
class ArtifactOutputDeclaration:
    """Compiler-resolved artifact publication intent for one output Port."""

    output_port: str
    artifact_kind: ArtifactKind
    artifact_media_type: str | None
    accepted_media_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdmittedArtifactPublication:
    """Closed artifact facts ready for immutable Result persistence."""

    output_port: str
    artifact_kind: ArtifactKind
    body: bytes
    media_type: str
    filename: str
    candidate_id: str | None


@dataclass(frozen=True, slots=True)
class AdmittedArtifactPublicationPlan:
    """Closed ordinary/artifact output partition for one admitted result."""

    artifact_output_ports: tuple[str, ...]
    publications: tuple[AdmittedArtifactPublication, ...]


def _artifact_publication_plan(
    *,
    declarations: tuple[ArtifactOutputDeclaration, ...],
    outputs: Mapping[str, AdmittedPort],
) -> AdmittedArtifactPublicationPlan:
    """Project intent without revalidating values admitted by their Port."""
    artifact_output_ports: list[str] = []
    publications: list[AdmittedArtifactPublication] = []
    for declaration in declarations:
        admitted = outputs.get(declaration.output_port)
        if admitted is None:
            continue
        artifact_output_ports.append(declaration.output_port)
        for value in admitted.values:
            payload = cast(ArtifactPayload, value.value)
            publications.append(
                AdmittedArtifactPublication(
                    output_port=declaration.output_port,
                    artifact_kind=declaration.artifact_kind,
                    body=payload.body,
                    media_type=(
                        declaration.artifact_media_type
                        if declaration.artifact_media_type is not None
                        else payload.media_type
                    ),
                    filename=payload.filename,
                    candidate_id=(
                        payload.candidate_id
                        if declaration.artifact_kind == "candidate"
                        else None
                    ),
                )
            )
    return AdmittedArtifactPublicationPlan(
        artifact_output_ports=tuple(artifact_output_ports),
        publications=tuple(publications),
    )
