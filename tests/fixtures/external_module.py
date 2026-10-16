"""Build a standalone, dependency-free extension wheel outside the checkout."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from zipfile import ZipFile

REGISTRATION = '''from core.catalog.declarations import AvailabilityDeclaration, AvailabilityResult, ExecutionBindingDefinition, MethodDefinition, ModulePackageRegistration, ScientificOperationFactory
from core.catalog.definition_resource import DefinitionResource
from core.catalog.port_contract import BehaviorReference, PortTypeDefinition
from core.operation import OperationCall, OperationContext
from datatypes.exact_reference import ExactContractReference

class Echo:
    def execute(self, call: OperationCall) -> dict[str, str]:
        return {"note": "installed external value"}

def factory(context: OperationContext) -> Echo:
    return Echo()

def validate(value: object) -> None:
    if not isinstance(value, str):
        raise ValueError("external.note requires text")

MODULE_PACKAGE = ModulePackageRegistration(
    package_id="external_echo", package_module=__package__,
    node_definitions=(DefinitionResource("echo.yaml"),),
    methods=(MethodDefinition("external.echo", {"name":"external identity"}, {"kind":"none"}, {"kind":"none"}, {"kind":"identity"}),),
    port_types=(PortTypeDefinition(
        type_id="external.note",
        validator=BehaviorReference("external.note/validate", {}),
        codec=BehaviorReference("external.note/codec", {}),
        content_identity=BehaviorReference("external.note/content", {}),
        runtime_validator=validate, runtime_to_wire=lambda value:value,
        runtime_from_wire=lambda value:value,
    ),),
    bindings=(ExecutionBindingDefinition(
        binding_id="external.echo.direct",
        node_type=ExactContractReference("node_type","external.echo"),
        method=ExactContractReference("method","external.echo"), binding_parameters={},
        execution_route="direct", deterministic=True, cacheable=False,
        factory=ScientificOperationFactory(BehaviorReference("external.echo/factory", {}),factory),
        availability=AvailabilityDeclaration(BehaviorReference("external.echo/availability",{}),{},AvailabilityResult.available),
    ),),
)
'''
NODE = '''node_type_id: external.echo
title: External Echo
summary: Emits a value through the independently installed extension.
category: external
inputs: []
outputs:
  - name: note
    port_type_id: external.note
    required: true
    multiplicity: one
    scientific_meaning: The installed extension's text.
parameter_groups: []
node_parameters: {}
'''


def build_external_module_wheel(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    metadata = "workbench_external_echo-1.0.0.dist-info"
    payloads = {
        "external_echo/__init__.py": b"",
        "external_echo/package.py": REGISTRATION.encode(),
        "external_echo/echo.yaml": NODE.encode(),
        f"{metadata}/METADATA": b"Metadata-Version: 2.1\nName: workbench-external-echo\nVersion: 1.0.0\n",
        f"{metadata}/WHEEL": b"Wheel-Version: 1.0\nGenerator: workbench-extension-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{metadata}/entry_points.txt": b"[protein_workbench.modules]\nexternal_echo = external_echo.package:MODULE_PACKAGE\n",
    }
    records = [f"{name},sha256={base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip('=')},{len(payload)}" for name, payload in payloads.items()]
    payloads[f"{metadata}/RECORD"] = ("\n".join([*records, f"{metadata}/RECORD,,"]) + "\n").encode()
    wheel = directory / "workbench_external_echo-1.0.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        for name, payload in payloads.items():
            archive.writestr(name, payload)
    return wheel


if __name__ == "__main__":
    import sys
    print(build_external_module_wheel(Path(sys.argv[1])))
