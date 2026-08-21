"""Documented CSH component to SER-HIS-GLY parent-span normalization."""

from __future__ import annotations

from collections import defaultdict

from core.operation import (
    OperationResources,
    OperationCall,
)
from datatypes.residue import (
    ModifiedResidueAtomMapping,
    ModifiedResidueNormalization,
    ModifiedResidueNormalizationCollection,
)
from datatypes.structure import ProteinStructure

from .residue_axis import (
    _AtomRecord,
    _pdb_polymer_declarations,
    _renumbered_atom_line,
    _single_model_records,
)


_CSH_PARENT_ATOMS = (
    ("SER", "S", (
        ("N1", "N"),
        ("CA1", "CA"),
        ("C1", "C"),
        ("CB1", "CB"),
        ("OG2", "OG"),
    )),
    ("HIS", "H", (
        ("N2", "N"),
        ("CA2", "CA"),
        ("C2", "C"),
        ("O2", "O"),
        ("CB2", "CB"),
        ("CG", "CG"),
        ("CD2", "CD2"),
        ("ND1", "ND1"),
        ("CE1", "CE1"),
        ("NE2", "NE2"),
    )),
    ("GLY", "G", (
        ("N3", "N"),
        ("CA3", "CA"),
        ("C3", "C"),
        ("O3", "O"),
    )),
)


def _parent_atom_line(
    record: _AtomRecord,
    *,
    serial: int,
    residue_name: str,
    residue_number: int,
    atom_name: str,
) -> str:
    line = list(record.line)
    line[0:6] = "ATOM  "
    line[6:11] = f"{serial:5d}"
    line[12:16] = f" {atom_name:<3}"
    line[16] = " "
    line[17:20] = f"{residue_name:>3}"
    line[22:26] = f"{residue_number:4d}"
    line[26] = " "
    return "".join(line)


def _canonical_seqres_lines(
    chain_id: str,
    components: tuple[str, ...],
) -> tuple[str, ...]:
    if len(components) > 9999:
        raise ValueError("normalized CSH SEQRES residue count exceeds PDB limits")
    return tuple(
        (
            f"SEQRES {serial:3d} {chain_id} {len(components):4d}  "
            + " ".join(components[offset : offset + 13])
        ).ljust(80)
        for serial, offset in enumerate(range(0, len(components), 13), start=1)
    )


def _normalized_csh_polymer_declarations(
    structure: ProteinStructure,
    normalized_identities: set[tuple[str, str, str]],
) -> list[str]:
    _, seqres = _pdb_polymer_declarations(structure)
    normalized_count_by_chain: dict[str, int] = defaultdict(int)
    for chain_id, _, _ in normalized_identities:
        normalized_count_by_chain[chain_id] += 1

    seqres_rewrites: dict[str, tuple[str, ...]] = {}
    for chain_id, normalized_count in normalized_count_by_chain.items():
        components = seqres.get(chain_id)
        if components is None or "CSH" not in components:
            continue
        if components.count("CSH") != normalized_count:
            raise ValueError(
                "CSH SEQRES correspondence does not match normalized "
                f"components in chain {chain_id}"
            )
        normalized_components = tuple(
            parent_component
            for component in components
            for parent_component in (
                ("SER", "HIS", "GLY")
                if component == "CSH"
                else (component,)
            )
        )
        seqres_rewrites[chain_id] = _canonical_seqres_lines(
            chain_id,
            normalized_components,
        )

    declarations: list[str] = []
    emitted_seqres_chains: set[str] = set()
    for line in structure.pdb_string.splitlines():
        if line.startswith("MODRES"):
            identity = (line[16], line[18:22].strip(), line[22].strip())
            if identity in normalized_identities:
                if line[12:15].strip().upper() != "CSH":
                    raise ValueError(
                        "CSH coordinate component contradicts its MODRES "
                        "declaration"
                    )
                continue
            declarations.append(line)
            continue
        if not line.startswith("SEQRES"):
            continue
        chain_id = line[11]
        rewrite = seqres_rewrites.get(chain_id)
        if rewrite is None:
            declarations.append(line)
            continue
        if chain_id not in emitted_seqres_chains:
            declarations.extend(rewrite)
            emitted_seqres_chains.add(chain_id)
    return declarations


def normalize_csh_parent_span(
    structure: ProteinStructure,
) -> tuple[ProteinStructure, ModifiedResidueNormalizationCollection]:
    """Expand each exact CSH component into its SER-HIS-GLY parents."""
    records = _single_model_records(structure)
    coordinate_records = [
        record for record in records if record is not None
    ]
    csh_groups: dict[tuple[str, str, str], list[_AtomRecord]] = {}
    for record in coordinate_records:
        if record.residue_name == "CSH":
            csh_groups.setdefault(record.residue_identity, []).append(record)
    if not csh_groups:
        raise ValueError("structure contains no CSH component to normalize")
    for identity in csh_groups:
        positions = [
            index
            for index, record in enumerate(records)
            if record is not None
            and record.residue_identity == identity
            and record.residue_name == "CSH"
        ]
        if positions != list(range(positions[0], positions[-1] + 1)):
            raise ValueError("CSH component coordinate records are noncontiguous")

    occupied = {
        record.residue_identity
        for record in coordinate_records
        if record.residue_name != "CSH"
    }
    replacements: dict[
        tuple[str, str, str],
        tuple[list[tuple[_AtomRecord, str, int, str]], ModifiedResidueNormalization],
    ] = {}
    expected_source_atoms = {
        source_atom
        for _, _, atoms in _CSH_PARENT_ATOMS
        for source_atom, _ in atoms
    }
    for identity, component_records in csh_groups.items():
        representative = component_records[0]
        if representative.insertion_code:
            raise ValueError(
                "CSH normalization does not accept insertion-coded components"
            )
        try:
            observed_number = int(representative.residue_number)
        except ValueError as error:
            raise ValueError("CSH residue number must be an integer") from error
        by_atom: dict[str, _AtomRecord] = {}
        for record in component_records:
            if record.record != "HETATM" or record.altloc != " ":
                raise ValueError(
                    "CSH normalization requires unambiguous HETATM records"
                )
            if record.atom_name in by_atom:
                raise ValueError(
                    f"CSH {record.public_residue_id} has duplicate atom "
                    f"{record.atom_name}"
                )
            by_atom[record.atom_name] = record
        if set(by_atom) != expected_source_atoms:
            missing = sorted(expected_source_atoms - set(by_atom))
            unexpected = sorted(set(by_atom) - expected_source_atoms)
            raise ValueError(
                "CSH atom inventory does not match the exact parent mapping; "
                f"missing={missing}, unexpected={unexpected}"
            )

        parent_ids = tuple(
            f"{representative.chain_id}:{observed_number + offset}"
            for offset in (-1, 0, 1)
        )
        collisions = [
            parent_id
            for parent_id, offset in zip(parent_ids, (-1, 0, 1), strict=True)
            if (
                representative.chain_id,
                str(observed_number + offset),
                "",
            ) in occupied
        ]
        if collisions:
            raise ValueError(
                "CSH parent residues collide with existing coordinates: "
                + ", ".join(collisions)
            )

        output_atoms: list[tuple[_AtomRecord, str, int, str]] = []
        atom_mappings: list[ModifiedResidueAtomMapping] = []
        for parent_index, (residue_name, _, atom_pairs) in enumerate(
            _CSH_PARENT_ATOMS
        ):
            parent_number = observed_number + parent_index - 1
            parent_id = parent_ids[parent_index]
            for source_atom, parent_atom in atom_pairs:
                output_atoms.append(
                    (
                        by_atom[source_atom],
                        residue_name,
                        parent_number,
                        parent_atom,
                    )
                )
                atom_mappings.append(
                    ModifiedResidueAtomMapping(
                        source_atom_name=source_atom,
                        parent_residue_id=parent_id,
                        parent_atom_name=parent_atom,
                    )
                )
        replacements[identity] = (
            output_atoms,
            ModifiedResidueNormalization(
                component_id="CSH",
                observed_residue_id=representative.public_residue_id,
                parent_residue_ids=parent_ids,
                parent_sequence="SHG",
                atom_mappings=tuple(atom_mappings),
            ),
        )

    output_lines = _normalized_csh_polymer_declarations(
        structure,
        set(replacements),
    )
    normalizations: list[ModifiedResidueNormalization] = []
    emitted: set[tuple[str, str, str]] = set()
    serial = 1
    for record_index, record in enumerate(records):
        if record is None:
            previous = records[record_index - 1]
            following = records[record_index + 1]
            assert previous is not None and following is not None
            previous_number = int(previous.residue_number)
            following_number = int(following.residue_number)
            following_is_replaced = following.residue_identity in replacements
            previous_is_replaced = previous.residue_identity in replacements
            bridges_parent_span = (
                previous.chain_id == following.chain_id
                and not previous.insertion_code
                and not following.insertion_code
                and (
                    (
                        following_is_replaced
                        and previous.record == "ATOM  "
                        and previous_number == following_number - 2
                    )
                    or (
                        previous_is_replaced
                        and following.record == "ATOM  "
                        and following_number == previous_number + 2
                    )
                )
            )
            if bridges_parent_span:
                continue
            if output_lines and output_lines[-1] != "TER":
                output_lines.append("TER")
            continue
        replacement = replacements.get(record.residue_identity)
        if replacement is None:
            output_lines.append(_renumbered_atom_line(record, serial))
            serial += 1
            continue
        if record.residue_identity in emitted:
            continue
        emitted.add(record.residue_identity)
        output_atoms, normalization = replacement
        for source, residue_name, residue_number, atom_name in output_atoms:
            output_lines.append(
                _parent_atom_line(
                    source,
                    serial=serial,
                    residue_name=residue_name,
                    residue_number=residue_number,
                    atom_name=atom_name,
                )
            )
            serial += 1
        normalizations.append(normalization)
    output_lines.append("END")
    return (
        ProteinStructure(
            pdb_string="\n".join(output_lines) + "\n",
        ),
        ModifiedResidueNormalizationCollection(entries=normalizations),
    )

class NormalizeCshParentSpanImplementation:
    """Normalize admitted CSH structure components and emit typed provenance."""

    def __init__(self, run_resources: OperationResources) -> None:
        self._run_resources = run_resources

    def execute(self, call: OperationCall) -> dict[str, object]:
        with self._run_resources.engine_invocation():
            normalized, normalizations = normalize_csh_parent_span(
                call.inputs["structure"].value
            )
            return {
                "structure": normalized,
                "modified_residue_normalizations": normalizations,
            }
