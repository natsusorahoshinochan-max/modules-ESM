"""Public SimpleFold existing-geometry caller; requires structure_confidence.contract."""
import json
from pathlib import Path
import sys
from protein_workbench_public.worker_process import run_worker
from modules.structure_confidence.contract import ConfidenceResult


def validate_geometry(content, encoding):
    """Reject inputs that the protein tokenizer would silently alter or omit."""
    from modules.structure_io import parse
    structure = parse(content, encoding)
    if len(structure) != 1:
        raise ValueError('SimpleFold confidence requires one conformation')
    canonical = {'ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY', 'HIS', 'ILE', 'LEU', 'LYS', 'MET', 'PHE', 'PRO', 'SER', 'THR', 'TRP', 'TYR', 'VAL'}
    for chain in structure[0]:
        for residue in chain:
            if residue.name not in canonical or residue.het_flag != 'A':
                raise ValueError(f'SimpleFold confidence cannot project noncanonical protein or other component {chain.name}:{residue.seqid} {residue.name}')
            names = [atom.name for atom in residue]
            if len(names) != len(set(names)) or any(atom.altloc.strip('\x00 ') for atom in residue):
                raise ValueError(f'SimpleFold confidence requires unambiguous atom correspondence at {chain.name}:{residue.seqid}')
    return structure


def create(settings):
    def evaluate(request, parameters, runtime):
        if parameters:
            raise ValueError('SimpleFold existing-geometry confidence has no sampling parameters')
        validate_geometry(Path(request.structure_path).read_bytes(), request.structure_format)
        python = Path(settings.get('python', sys.executable)).absolute()
        if not python.is_file():
            raise ValueError('Configure an existing SimpleFold Python executable')
        paths = {}
        for key in ('model_path', 'esm2_source', 'esm2_checkpoint', 'ccd_path'):
            if not settings.get(key) or not Path(settings[key]).exists():
                raise ValueError(f'Configure existing SimpleFold {key}')
            paths[key] = str(Path(settings[key]).resolve())
        for path in (Path(paths['model_path']) / 'simplefold_1.6B.ckpt', Path(paths['model_path']) / 'plddt.ckpt', Path(paths['esm2_checkpoint']).with_name(Path(paths['esm2_checkpoint']).stem + '-contact-regression.pt')):
            if not path.is_file():
                raise ValueError(f'SimpleFold confidence requires existing resource: {path}')
        if runtime.cancelled:
            raise ValueError('Confidence evaluation cancelled')
        config = runtime.workdir / 'simplefold-confidence-request.json'
        config.write_text(json.dumps({'settings': paths, 'structure_path': request.structure_path, 'structure_format': request.structure_format, 'positions': request.positions, 'workdir': str(runtime.workdir)}))
        run_worker([str(python), '-m', 'modules.simplefold.confidence_worker', str(config)], cwd=Path(__file__).resolve().parents[2], log_path=runtime.workdir / 'simplefold-confidence.log', cancelled=lambda: runtime.cancelled, label='SimpleFold confidence')
        result = json.loads((runtime.workdir / 'simplefold-confidence.json').read_text())
        return ConfidenceResult(tuple(result['positions']), tuple(result['plddt']), context={'coordinate_preprocessing': 'resolved atom centroid translation and tool padding', 'coordinate_scale': 16.0, 'reference_scale': 5.0, 'time': 1.0, 'latent_model': 'simplefold_1.6B', 'head': 'plddt.ckpt', 'sequence_features': 'ESM2-3B', **result.get('context', {})})
    return evaluate
