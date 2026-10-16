"""External input inspector and draft preview using the public module contract."""
from core.catalog.authoring_actions import AuthoringActionDefinition
from core.catalog.declarations import ModulePackageRegistration


def inspect(context, request):
    descriptor, content = context.read_input(request['project_input_ref'])
    return {'filename': descriptor.filename, 'reading': float(content)}


def preview(context, request):
    _, content = context.read_input(request['project_input_ref'])
    return {'reading': float(content) + request['offset'], 'adopted': False}


MODULE_PACKAGE = ModulePackageRegistration(
    package_id='authoring_demo', package_module=__name__,
    authoring_actions=(
        AuthoringActionDefinition('authoring_demo.inspect', inspect),
        AuthoringActionDefinition('authoring_demo.preview', preview),
    ),
)
