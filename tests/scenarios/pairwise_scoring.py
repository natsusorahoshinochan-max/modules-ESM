"""Independent pairwise scoring contracts shared by scoring owner tests."""

from __future__ import annotations

from datetime import datetime, timezone
from core.catalog.builtins import builtin_frozen_catalog
from datatypes.exact_reference import ExactContractReference
from core.catalog.model import CatalogContract, FrozenCatalog
from core.scoring.selection import PairwiseContextSelector, context_selector_canonical
from tests.support.catalog import catalog_contract, install_runtime
from datatypes.exact_reference import ExactContractReference


def _contract(
    kind: str,
    contract_id: str,
    descriptor: dict,
) -> CatalogContract:
    return catalog_contract(
        kind,
        contract_id,
        {
            "schema_namespace": "protein-workbench-contract/v2",
            "contract_kind": kind,
            "contract_id": contract_id,
            **descriptor,
        },
    )


def _pairwise_catalog() -> tuple[FrozenCatalog, dict[str, CatalogContract]]:
    builtin = builtin_frozen_catalog()
    metric = _contract(
        "metric",
        "structure.tm_score",
        {
            "value_shape": "scalar",
            "canonical_range": {"minimum": 0, "maximum": 1},
            "validation_contract": {"finite": True},
        },
    )
    method = _contract("method", "tm-align", {})
    pairwise_node = _contract(
        "node_type",
        "score.test.pairwise",
        {
            "inputs": [
                {
                    "name": name,
                    "port_type": builtin.require_port_type(
                        "candidate.relation"
                        if name == "pairings"
                        else "score.collection"
                        if name in {"left", "right", "source"}
                        else "candidate.collection").reference(),
                    "required": False,
                    "multiplicity": "one",
                }
                for name in (
                    "subjects",
                    "counterparts",
                    "pairings",
                    "left",
                    "right",
                    "source",
                )
            ],
            "outputs": [
                {
                    "name": "scores",
                    "port_type": builtin.require_port_type(
                        "score.collection").reference(),
                    "required": True,
                    "multiplicity": "one",
                }
            ],
            "node_parameters": {},
        },
    )
    selector_profile = context_selector_canonical(
        PairwiseContextSelector(
            pairing_mode="fixed_reference",
            normalization="tm-score/reference-length",
        )
    )
    fixed_utility = _contract(
        "utility_transform",
        "tm-score.fixed",
        {
            "compatible_input_contract": {
                "metric": metric.reference(),
                "method": method.reference(),
                "context_profile": selector_profile,
            },
            "parameters": {},
        },
    )
    paired_utility = _contract(
        "utility_transform",
        "tm-score.paired",
        {
            "compatible_input_contract": {
                "metric": metric.reference(),
                "method": method.reference(),
                "context_profile": context_selector_canonical(
                    PairwiseContextSelector(
                        pairing_mode="explicit_relation",
                        normalization="tm-score/reference-length",
                    )
                ),
            },
            "parameters": {},
        },
    )
    contracts = {
        item.contract_id: item
        for item in (
            metric,
            method,
            pairwise_node,
            fixed_utility,
            paired_utility,
        )
    }
    contracts["score.tm.pairwise"] = _pairwise_binding(contracts)
    return (
        FrozenCatalog(
            builtin.port_types,
            contracts=install_runtime(
                tuple(contracts.values()),
                utility_transforms={
                    "tm-score.fixed": (
                        lambda value, _: float(value)
                    ),
                    "tm-score.paired": (
                        lambda value, _: float(value)
                    ),
                },
            ),
            availability=(),
            availability_observed_at=datetime(
                2026,
                7,
                29,
                tzinfo=timezone.utc,
            ),
        ),
        contracts,
    )


def _reference_from_contract(
    contract: CatalogContract,
) -> ExactContractReference:
    value = contract.reference()
    return ExactContractReference(
        contract_kind=value["contract_kind"],
        contract_id=value["contract_id"])


def _pairwise_binding(
    contracts: dict[str, CatalogContract],
) -> CatalogContract:
    return _contract(
        "binding",
        "score.tm.pairwise",
        {
            "node_type": contracts["score.test.pairwise"].reference(),
            "method": contracts["tm-align"].reference(),
            "produced_observations": [
                {
                    "output_port": "scores",
                    "output_partition": "per-subject",
                    "metric": contracts["structure.tm_score"].reference(),
                    "context_profile": context_selector_canonical(
                        PairwiseContextSelector(
                            pairing_mode="explicit_relation",
                            normalization="tm-score/reference-length",
                        )
                    ),
                    "subject_grain": "candidate",
                    "source_role": "subject",
                    "subject_direction": "input",
                    "subject_port": "subjects",
                    "reference_direction": "input",
                    "reference_port": "counterparts",
                    "pairing_direction": "input",
                    "pairing_port": "pairings",
                    "guaranteed_multiplicity": "one",
                }
            ],
            "observation_propagation": None,
        },
    )
