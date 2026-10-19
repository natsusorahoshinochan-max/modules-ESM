from protein_workbench_public.module_api import Module, Tool


def create(settings):
    raise ValueError('Test must supply the external ProteinMPNN tool')


def module():
    return Module('lab.mpnn', 'External MPNN test tool', tools=(Tool('lab.mpnn', 'External MPNN', 'workbench.proteinmpnn.call', create),))
