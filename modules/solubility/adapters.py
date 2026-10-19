"""Actual CLI adapters for the maintained SoluProt port and official Protein-Sol."""
import csv
import io
import json
import math
import os
from pathlib import Path
import shutil

from protein_workbench_public.module_api import Tool
from protein_workbench_public.worker_process import run_worker
from .contract import SolubilityResult

PROTEIN_SOL_FILES = ('fasta_seq_reformat_export.pl', 'multiple_prediction_wrapper_export.sh', 'profiles_gather_export.pl', 'seq_compositions_perc_pipeline_export.pl', 'seq_props_ALL_export.pl', 'seq_reference_data.txt', 'server_prediction_seq_export.pl', 'ss_propensities.txt')
SLOT = 'workbench.evaluate.sequence_solubility'
DRIVER = '''set -e
provider_root=$1
perl_executable=$2
input_fasta=$3
export MEMBRANE_EXCLUDE=$4
export his_charged=$5
unset motifneutral extra_output
unset WHOLE_SEQ_OUT
perl() {
    provider_script=$1
    shift
    "$perl_executable" "$provider_root/$provider_script" "$@"
}
. "$provider_root/multiple_prediction_wrapper_export.sh" "$input_fasta"
'''


def path_setting(settings, key, *, directory=False, executable=False):
    value = settings.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f'Configure {key} in solubility module deployment settings')
    path = Path(value).expanduser().absolute()
    if not (path.is_dir() if directory else path.is_file()) or (executable and not os.access(path, os.X_OK)):
        raise ValueError(f'Configured {key} is unavailable: {path}')
    return path


def metric(value, unit, meaning):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Tool returned a non-finite evaluation value')
    return {'value': number, 'unit': unit, 'meaning': meaning}


def _stage(request, runtime, minimum):
    if runtime.cancelled:
        raise ValueError('Solubility evaluation cancelled')
    if not request.sequences or any(not isinstance(sequence, str) or len(sequence) < minimum or any(aa not in 'ACDEFGHIKLMNPQRSTVWY' for aa in sequence) for sequence in request.sequences):
        raise ValueError(f'Tool requires canonical protein sequences of at least {minimum} residues')
    directory = runtime.workdir / 'solubility-tool'
    directory.mkdir()
    (directory / 'input.fasta').write_text(''.join(f'>item{index}\n{sequence}\n' for index, sequence in enumerate(request.sequences)))
    return directory


def _ordered(rows, count):
    values = {}
    for identity, metrics in rows:
        if identity not in {f'item{i}' for i in range(count)} or identity in values:
            raise ValueError('Tool returned an unknown or repeated staged sequence identifier')
        values[identity] = metrics
    if len(values) != count:
        raise ValueError('Tool did not return an evaluation for every supplied sequence')
    return tuple(values[f'item{i}'] for i in range(count))


def create_protein_sol(settings):
    def evaluate(request, parameters, runtime):
        defaults = {'membrane_exclude': False, 'histidine_charged': False}
        if set(parameters) - defaults.keys() or any(type(value) is not bool for value in parameters.values()):
            raise ValueError('Protein-Sol supports only boolean membrane_exclude and histidine_charged parameters')
        effective = {**defaults, **parameters}
        root = path_setting(settings, 'protein_sol_source', directory=True)
        for name in PROTEIN_SOL_FILES:
            if not (root / name).is_file():
                raise ValueError(f'Protein-Sol source is missing {name}')
        bash = path_setting(settings, 'bash', executable=True)
        perl = path_setting(settings, 'perl', executable=True)
        directory = _stage(request, runtime, 21)
        for name in ('seq_reference_data.txt', 'ss_propensities.txt'):
            shutil.copyfile(root / name, directory / name)
        command = [str(bash), '-c', DRIVER, 'protein-sol', str(root), str(perl), 'input.fasta', 'YES' if effective['membrane_exclude'] else 'NO', 'yes' if effective['histidine_charged'] else 'no']
        run_worker(command, cwd=directory, log_path=directory / 'worker.log', cancelled=lambda: runtime.cancelled, label='Protein-Sol')
        rows = []
        populations = []
        for row in csv.reader(io.StringIO((directory / 'seq_prediction.txt').read_text())):
            if not row or row[0] != 'SEQUENCE PREDICTIONS':
                continue
            if len(row) != 6 or not row[1].startswith('>'):
                raise ValueError('Protein-Sol returned a malformed prediction row')
            _, identity, percent, scaled, population, pi = row
            rows.append((identity[1:], {
                'percent_solubility': metric(percent, 'percent', 'Predicted soluble fraction on the Niwa cell-free expression percentage scale'),
                'scaled_solubility': metric(scaled, 'dimensionless', 'Prediction scaled between the training low and top solubility groups'),
                'isoelectric_point': metric(pi, 'pH', 'Protein-Sol calculated sequence isoelectric point'),
            }))
            populations.append(metric(population, 'dimensionless', 'Training population soluble fraction on the same scaled-solubility scale')['value'])
        values = _ordered(rows, len(request.sequences))
        if len(set(populations)) != 1:
            raise ValueError('Protein-Sol population calibration is missing or inconsistent')
        return SolubilityResult('Protein-Sol October 2017 sequence prediction', effective, values, 'solubility-tool/seq_prediction.txt', {'population_scaled_solubility': populations[0], 'feature_windows': [21, 51]})
    return evaluate


def create_soluprot(settings, *, mode):
    if mode not in ('full', 'no_tm'):
        raise ValueError('Choose SoluProt full or no_tm explicitly')
    def evaluate(request, parameters, runtime):
        if set(parameters) - {'threads'} or type(parameters.get('threads', 1)) is not int or parameters.get('threads', 1) < 1:
            raise ValueError('SoluProt supports only a positive integer threads parameter')
        effective = {'threads': parameters.get('threads', 1)}
        root = path_setting(settings, 'soluprot_source', directory=True)
        python = path_setting(settings, 'soluprot_python', executable=True)
        usearch = path_setting(settings, 'usearch', executable=True)
        model_key = 'soluprot_full_model' if mode == 'full' else 'soluprot_no_tm_model'
        model = path_setting(settings, model_key)
        database = path_setting(settings, 'soluprot_database')
        metadata = json.loads(model.read_text())
        if len(metadata.get('classes', [])) != 2 or metadata.get('soluble_class') not in metadata['classes']:
            raise ValueError('SoluProt model must explicitly map soluble_class to its binary classes')
        if not (model.parent / metadata['arrays']).is_file():
            raise ValueError('SoluProt model arrays are missing')
        if not (root / 'soluprot_core/cli.py').is_file():
            raise ValueError('SoluProt source is missing soluprot_core/cli.py')
        tmhmm = path_setting(settings, 'tmhmm', executable=True) if mode == 'full' else None
        perl = path_setting(settings, 'perl', executable=True) if mode == 'full' else None
        directory = _stage(request, runtime, 20)
        scratch = directory / 'scratch'
        scratch.mkdir()
        driver = 'import sys;sys.path.insert(0,sys.argv.pop(1));from soluprot_core.cli import main;raise SystemExit(main())'
        command = [str(python), '-I', '-B', '-c', driver, str(root), '--i_fa', str(directory / 'input.fasta'), '--o_csv', str(directory / 'output.csv'), '--tmp_dir', str(scratch), '--model', str(model), '--usearch', str(usearch), '--pdb', str(database), '--check_unknown', '--no_proc', str(effective['threads'])]
        if mode == 'full':
            # The official TMHMM launcher invokes perl via PATH. A private wrapper
            # binds that command to the configured executable without editing it.
            (directory / 'perl').symlink_to(perl)
            launcher = directory / 'launch.py'
            launcher.write_text('import os,sys\nos.environ["PATH"]=sys.argv[1]+os.pathsep+os.environ.get("PATH", "")\nos.execv(sys.argv[2],sys.argv[2:])\n')
            command.extend(['--tmhmm', str(tmhmm)])
            command = [str(python), '-I', '-B', str(launcher), str(directory), *command]
        else:
            command.append('--no_tmhmm')
        run_worker(command, cwd=directory, log_path=directory / 'worker.log', cancelled=lambda: runtime.cancelled, label=f'SoluProt {mode}')
        reader = csv.DictReader(io.StringIO((directory / 'output.csv').read_text()))
        rows = []
        for row in reader:
            value = metric(row['soluble'], 'probability 0-1', 'SoluProt model probability of soluble expression in Escherichia coli')
            if not 0 <= value['value'] <= 1:
                raise ValueError('SoluProt probability is outside 0–1')
            rows.append((row['fa_id'], {'soluble_probability': value}))
        values = _ordered(rows, len(request.sequences))
        return SolubilityResult(f'SoluProt maintained port · {mode}', effective, values, 'solubility-tool/output.csv', {'mode': mode, 'model': metadata.get('name', model.parent.name), 'classes': metadata['classes'], 'soluble_class': metadata['soluble_class']})
    return evaluate


def tools():
    return (
        Tool('workbench.soluprot.full', 'SoluProt · full with TMHMM', SLOT, lambda settings: create_soluprot(settings, mode='full'), parameters={'defaults': {'threads': 1}}, capabilities={'minimum_length': 20, 'region': 'complete sequence'}),
        Tool('workbench.soluprot.no_tm', 'SoluProt · no-TM model', SLOT, lambda settings: create_soluprot(settings, mode='no_tm'), parameters={'defaults': {'threads': 1}}, capabilities={'minimum_length': 20, 'region': 'complete sequence'}),
        Tool('workbench.protein_sol', 'Protein-Sol · October 2017', SLOT, create_protein_sol, parameters={'defaults': {'membrane_exclude': False, 'histidine_charged': False}}, capabilities={'minimum_length': 21, 'region': 'complete sequence'}),
    )
