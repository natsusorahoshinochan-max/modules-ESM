"""Public-interface constructors for direct Scientific Operation tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any, cast

from datatypes.i_json import admit_i_json
from core.catalog.declarations import ExecutionBindingDefinition
from core.catalog.model import (
    FrozenCatalog,
)
from core.operation import (
    AdmittedPort,
    AdmittedValue,
    BindingEnvironment,
    OperationCall,
    OperationContext,
)
from tests.support.output_admission import admit_fixture_port
from core.scoring.selection import (
    ObservationSelector,
    ResolvedSelectionObjective,
    ResolvedUtilityTransform,
    rank_candidates_by_weighted_utility,
    resolve_candidate_utilities_from_facts,
    SelectionResult,
    SelectionInput,
    SelectionObjective,
)
from core.parameters.contract import admit_values
from datatypes.candidate import (
    CandidateCollection,
    CandidateDataReference,
)
from datatypes.exact_reference import (
    ExactContractReference,
    ResidueAxisReference,
)
from datatypes.observation import ScoreCollection


def _resolved_objective(
    objective: SelectionObjective,
    catalog: FrozenCatalog,
    effective_weight: float,
) -> ResolvedSelectionObjective:
    utility_contract = catalog.require_contract(
        "utility_transform",
        objective.utility_transform.contract_id,
    )
    return ResolvedSelectionObjective(
        objective_id=objective.objective_id,
        candidate_input=objective.candidate_input,
        score_collection_input=objective.score_collection_input,
        source_partition=objective.source_partition,
        metric=objective.metric,
        method=objective.method,
        context_selector=objective.context_selector,
        utility=ResolvedUtilityTransform(
            reference=objective.utility_transform,
            parameters=admit_values(
                utility_contract.definition.parameter_contract,
                admit_i_json(objective.utility_parameters),
            ),
            apply=utility_contract.definition.transform,
        ),
        declared_weight=objective.weight,
        effective_weight=effective_weight,
        match_cardinality=objective.match_cardinality,
        missing_policy=objective.missing_policy,
    )


def _resolved_objectives(
    objectives: Sequence[SelectionObjective],
    catalog: FrozenCatalog,
) -> tuple[ResolvedSelectionObjective, ...]:
    declared_total = math.fsum(objective.weight for objective in objectives)
    return tuple(
        _resolved_objective(
            objective,
            catalog,
            objective.weight / declared_total,
        )
        for objective in objectives
    )


def select_admitted_candidates(
    *,
    candidate_inputs: Mapping[SelectionInput, CandidateCollection],
    score_collection_inputs: Mapping[SelectionInput, ScoreCollection],
    objectives: Sequence[SelectionObjective],
    catalog: FrozenCatalog,
    limit: int,
) -> SelectionResult:
    """Exercise Utility selection from Port-admitted facts in focused tests."""
    port_types = {
        definition.type_id: definition for definition in catalog.port_types
    }
    candidate_port_type = catalog.require_port_type(
        "candidate.collection",
    )
    admitted_candidates = {
        reference: admit_fixture_port(
            port_type=candidate_port_type,
            multiplicity="one",
            values=(collection,),
            candidate_data_port_types=port_types,
        )
        for reference, collection in candidate_inputs.items()
    }
    score_port_type = catalog.require_port_type("score.collection")
    admitted_scores = {
        reference: admit_fixture_port(
            port_type=score_port_type,
            multiplicity="one",
            values=(collection,),
            candidate_data_port_types=port_types,
        ).value
        for reference, collection in score_collection_inputs.items()
    }
    resolved = _resolved_objectives(objectives, catalog)
    candidate_reference = resolved[0].candidate_input
    admitted_candidate_input = admitted_candidates[candidate_reference]
    profile = resolve_candidate_utilities_from_facts(
        candidate_inputs={
            reference: admitted.value
            for reference, admitted in admitted_candidates.items()
        },
        score_collection_inputs=admitted_scores,
        objectives=resolved,
        candidate_data_references={
            reference.candidate_id: reference
            for reference in admitted_candidate_input.candidate_data
        },
    )
    ranked = rank_candidates_by_weighted_utility(profile)
    return SelectionResult(
        CandidateCollection(
            collection_id=f"{profile.candidates.collection_id}.selected",
            item_type=profile.candidates.item_type,
            items=ranked[:limit],
        ),
        profile.provenance,
    )


def operation_context(
    catalog: FrozenCatalog,
    binding_id: str,
    resources: Any,
    *,
    environment: Mapping[str, Any] | None = None,
    selection_objectives: Sequence[SelectionObjective] = (),
    observation_selectors: Sequence[ObservationSelector] = (),
) -> OperationContext:
    """Resolve one exact Binding into the public factory input contract."""
    plan = catalog.produced_observation_plan(binding_id)

    return OperationContext(
        method=plan.binding_method,
        produced_observations=plan.observations,
        selection_objectives=_resolved_objectives(
            selection_objectives,
            catalog,
        ),
        observation_selectors=tuple(observation_selectors),
        environment=BindingEnvironment(
            {} if environment is None else environment
        ),
        resources=resources,
    )


def operation_call(
    *,
    catalog: FrozenCatalog | None = None,
    binding_id: str | None = None,
    inputs: Mapping[str, Any] | None = None,
    node_parameters: Mapping[str, Any] | None = None,
    binding_parameters: Mapping[str, Any] | None = None,
    effective_randomness: Mapping[str, Any] | None = None,
) -> OperationCall:
    """Construct the exact immutable call admitted by the runtime boundary."""
    supplied_inputs = {} if inputs is None else inputs
    admitted_inputs = {}
    if supplied_inputs:
        if catalog is None or binding_id is None:
            raise AssertionError(
                "non-empty direct calls require an exact Catalog Binding"
            )
        binding = catalog.require_contract(
            "binding",
            binding_id,
        )
        node_reference = binding.descriptor["node_type"]
        node_type = catalog.require_contract(
            node_reference["contract_kind"],
            node_reference["contract_id"],
        )
        declarations = {
            declaration["name"]: declaration
            for declaration in node_type.descriptor.get("inputs", ())
        }
        candidate_data_port_types = {
            definition.type_id: definition
            for definition in catalog.port_types
        }
        for port_name, supplied in supplied_inputs.items():
            declaration = declarations[port_name]
            port_reference = declaration["port_type"]
            port_type = catalog.require_port_type(
                port_reference["contract_id"],
            )
            values = (
                tuple(supplied)
                if declaration["multiplicity"] == "many"
                else (supplied,)
            )

            admitted_inputs[port_name] = admit_fixture_port(
                port_type=port_type,
                multiplicity=declaration["multiplicity"],
                values=values,
                candidate_data_port_types=candidate_data_port_types,
            )
    return OperationCall(
        inputs=admitted_inputs,
        node_parameters=admit_i_json({} if node_parameters is None else node_parameters),
        binding_parameters=admit_i_json(
            {} if binding_parameters is None else binding_parameters
        ),
        effective_randomness=admit_i_json(
            {} if effective_randomness is None else effective_randomness
        ),
    )


def admitted_port_fixture(
    value: Any,
    *,
    port_type_id: str,
    value_content_digests: tuple[str, ...],
    candidate_data: tuple[CandidateDataReference, ...] = (),
    scientific_axes: tuple[ResidueAxisReference, ...] = (),
    observation_methods: tuple[ExactContractReference, ...] = (),
    multiplicity: str = "one",
) -> AdmittedPort:
    """Build an explicitly pre-admitted record for operation boundary tests."""
    values = tuple(value) if multiplicity == "many" else (value,)
    if len(values) != len(value_content_digests):
        raise AssertionError(
            "pre-admitted fixture values and content digests must align"
        )
    admitted_values = tuple(
        AdmittedValue(
            value=item,
            canonical_bytes=("fixture:" + digest).encode("ascii"),
            content_digest=digest,
            candidate_data=candidate_data if index == 0 else (),
            scientific_axes=scientific_axes if index == 0 else (),
            observation_methods=(
                observation_methods if index == 0 else ()
            ),
        )
        for index, (item, digest) in enumerate(
            zip(values, value_content_digests, strict=True)
        )
    )
    return AdmittedPort(
        port_type=ExactContractReference(
            "port_type",
            port_type_id,
        ),
        multiplicity=multiplicity,
        values=admitted_values,
        content_digest=(
            admitted_values[0].content_digest
            if len(admitted_values) == 1
            else "sha256:" + ("f" * 64)
        ),
    )


def build_operation(
    catalog: FrozenCatalog,
    binding_id: str,
    resources: Any,
    *,
    environment: Mapping[str, Any] | None = None,
    selection_objectives: Sequence[SelectionObjective] = (),
    observation_selectors: Sequence[ObservationSelector] = (),
) -> Any:
    """Build an operation from the admitted Binding definition."""
    context = operation_context(
        catalog,
        binding_id,
        resources,
        environment=environment,
        selection_objectives=selection_objectives,
        observation_selectors=observation_selectors,
    )
    binding = catalog.require_contract(
        "binding",
        binding_id,
    )
    definition = cast(ExecutionBindingDefinition, binding.definition)
    return definition.factory.build(context)
