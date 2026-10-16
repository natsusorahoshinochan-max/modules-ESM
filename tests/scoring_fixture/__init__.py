"""A deterministic external module for public scoring-choice scenarios."""

from core.catalog.declarations import (AvailabilityDeclaration, AvailabilityResult,
    ExecutionBindingDefinition, MethodDefinition, ModulePackageRegistration,
    ScientificOperationFactory, UtilityTransformDefinition)
from core.catalog.definition_resource import DefinitionResource
from core.catalog.observation import ProducedObservation
from core.catalog.port_contract import BehaviorReference
from datatypes.candidate import Candidate, CandidateCollection
from datatypes.exact_reference import ExactContractReference as Ref
from datatypes.observation import (IntrinsicContextProfile, IntrinsicObservationContext,
    ScoreCollection, ScoreObservation)
from datatypes.sequence import ProteinSequence


class TrialData:
    def __init__(self, operation):
        self.operation = operation

    def execute(self, call):
        if self.operation == "population":
            return {"candidates": CandidateCollection("trials", "protein.sequence", tuple(
                Candidate(name, ProteinSequence(sequence), metadata={"display_name": name})
                for name, sequence in (("zeta", "AA"), ("alpha", "AC"), ("last", "AD"))))}
        return {"scores": ScoreCollection("trials", tuple(ScoreObservation(
            subject=subject, metric=Ref("metric", "scoring_fixture.success_fraction"),
            method=Ref("method", "scoring_fixture.trials"), context=IntrinsicObservationContext(),
            source_partition="trials", value=value,
        ) for subject, value in zip(call.inputs["candidates"].candidate_data,
                                    call.node_parameters["values"], strict=True) if value is not None))}


def registration():
    return ModulePackageRegistration(
        package_id="scoring_fixture", package_module=__name__,
        node_definitions=tuple(DefinitionResource(name + ".yaml") for name in ("population", "measurements")),
        bindings=tuple(ExecutionBindingDefinition(
            binding_id=f"scoring_fixture.{name}.direct", node_type=Ref("node_type", f"scoring_fixture.{name}"),
            method=Ref("method", "scoring_fixture.trials"), binding_parameters={}, execution_route="direct",
            factory=ScientificOperationFactory(BehaviorReference(f"scoring_fixture/{name}"),
                lambda context, operation=name: TrialData(operation)),
            availability=AvailabilityDeclaration(BehaviorReference(f"scoring_fixture/{name}/available"), {}, AvailabilityResult.available),
            deterministic=True, cacheable=True,
            produced_observations=(() if name == "population" else (ProducedObservation(
                output_port="scores", output_partition="trials", metric=Ref("metric", "scoring_fixture.success_fraction"),
                context_profile=IntrinsicContextProfile(), subject_input="candidates", guaranteed_multiplicity="zero_or_more"),)),
        ) for name in ("population", "measurements")),
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
