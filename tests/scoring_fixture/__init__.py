"""A deterministic external module for public scoring-choice scenarios."""

from core.catalog.declarations import MethodDefinition, ModulePackageRegistration, UtilityTransformDefinition
from core.catalog.definition_resource import DefinitionResource
from core.catalog.port_contract import BehaviorReference
from datatypes.exact_reference import ExactContractReference as Ref


def registration():
    return ModulePackageRegistration(
        package_id="scoring_fixture", package_module=__name__,
        metric_definitions=(DefinitionResource("success_fraction.yaml"),),
        methods=(MethodDefinition("scoring_fixture.trials", {"name": "Fixed trial success fraction"}, {}, {}, {}),),
        utility_transforms=(UtilityTransformDefinition(
            transform_id="scoring_fixture.success_fraction.native",
            title="成功试验比例（原始尺度）",
            meaning="评分等于已记录的成功试验比例；1 表示本组试验全部成功，0 表示全部失败。",
            applicability="仅用于本模块相同试验定义下的 intrinsic 成功比例。",
            limitations=("不同试验设计的成功比例不能视为已经校准。",),
            compatible_input_contract={
                "metric": Ref("metric", "scoring_fixture.success_fraction"),
                "method": Ref("method", "scoring_fixture.trials"),
                "context_profile": {"kind": "intrinsic"},
            },
            parameters={}, behavior=BehaviorReference("scoring_fixture/native", {"mapping": "identity"}),
            transform=lambda value, parameters: float(value),
        ),),
    )
