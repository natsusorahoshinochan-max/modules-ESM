from protein_workbench_public.module_api import Module, Tool


def create(settings):
    raise AssertionError('Install a test external generator')


def module():
    return Module('lab.esm3', 'External ESM3 tool', tools=(Tool('lab.esm3', 'External generator', 'workbench.esm3.generate', create),))
