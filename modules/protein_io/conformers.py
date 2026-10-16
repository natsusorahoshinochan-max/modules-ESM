"""Source model discovery and selection without rewriting authored atom identities."""
from typing import TypedDict
from datatypes.structure import ProteinStructure
from datatypes.structure_format import read_mmcif_atoms
from .errors import ProteinInputError


class StructureModel(TypedDict):
    model_index: int
    model_id: str
    chain_ids: list[str]


def structure_models(structure: ProteinStructure) -> list[StructureModel]:
    models: list[StructureModel] = []
    if structure.format == 'mmcif':
        by_id: dict[str, StructureModel] = {}
        for atom in read_mmcif_atoms(structure.text):
            if atom.model not in by_id:
                model = StructureModel(model_index=len(models) + 1, model_id=atom.model, chain_ids=[])
                models.append(model)
                by_id[atom.model] = model
            chains = by_id[atom.model]['chain_ids']
            if atom.chain_id not in chains:
                chains.append(atom.chain_id)
        return models
    current: StructureModel | None = None
    for line in structure.text.splitlines():
        if line.startswith('MODEL '):
            current = StructureModel(model_index=len(models) + 1, model_id=line[10:14].strip(), chain_ids=[])
            models.append(current)
        elif line.startswith(('ATOM  ', 'HETATM')):
            if current is None:
                current = StructureModel(model_index=1, model_id='1', chain_ids=[])
                models.append(current)
            if line[21] not in current['chain_ids']:
                current['chain_ids'].append(line[21])
    return models


def select_model(structure: ProteinStructure, model_index: int | None) -> tuple[ProteinStructure, StructureModel]:
    models = structure_models(structure)
    if model_index is None:
        if len(models) != 1:
            raise ProteinInputError('Choose one model explicitly, or import the selected models as separate Candidates')
        model_index = 1
    if not 1 <= model_index <= len(models):
        raise ProteinInputError(f'Model index {model_index} is not present in the source structure')
    model = models[model_index - 1]
    if len(models) == 1:
        return structure, model
    if structure.format == 'mmcif':
        from datatypes.structure_format import mmcif_dictionary, write_mmcif_dictionary
        data = mmcif_dictionary(structure.text)
        indices = [i for i, atom in enumerate(read_mmcif_atoms(structure.text)) if atom.model == model['model_id']]
        for key, values in tuple(data.items()):
            if key.startswith('_atom_site.'):
                data[key] = [values[i] for i in indices]
        if "_atom_site_anisotrop.id" in data:
            atom_ids = set(data["_atom_site.id"])
            anisotrop_models = data.get("_atom_site_anisotrop.pdbx_PDB_model_num")
            anisotrop_indices = [
                i for i, atom_id in enumerate(data["_atom_site_anisotrop.id"])
                if atom_id in atom_ids and (anisotrop_models is None or anisotrop_models[i] == model["model_id"])
            ]
            for key, values in tuple(data.items()):
                if key.startswith("_atom_site_anisotrop."):
                    if anisotrop_indices:
                        data[key] = [values[i] for i in anisotrop_indices]
                    else:
                        del data[key]
        text = write_mmcif_dictionary(data)
    else:
        lines: list[str] = []
        current = 0
        inside = False
        for line in structure.text.splitlines():
            if line.startswith('MODEL '):
                current += 1
                inside = True
            if not inside or current == model_index:
                # Counts describe the original ensemble, not the extracted structure.
                if not line.startswith(('NUMMDL', 'MASTER')):
                    lines.append(line)
            if line.startswith('ENDMDL'):
                inside = False
        text = '\n'.join(lines) + '\n'
    return ProteinStructure(text=text, format=structure.format), model
