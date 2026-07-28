"""Deterministic backend whose trusted readiness resolver fails closed."""

from __future__ import annotations

from core.provider_readiness import ProviderReadinessFact
from core.server import create_app
from tests.fixtures.deterministic_backend import (
    ALLOWED_RUNTIME_MODULE_IDS,
    DETERMINISTIC_MODULE_OVERRIDES,
    PROVIDER_ALIASES,
    deterministic_readiness_resolver,
)


def unavailable_readiness_resolver(requirements):
    facts = list(deterministic_readiness_resolver(requirements))
    facts = [
        fact
        for fact in facts
        if fact.provider not in {
            "biohub",
            "local_open",
            "controlled-proteinmpnn",
        }
    ]
    biohub = next(
        requirement
        for requirement in requirements
        if requirement.provider == "biohub"
    )
    del biohub
    facts.extend([
        ProviderReadinessFact(
            provider="biohub",
            status="ready",
            provider_identity={"fixture": "first"},
            details={},
        ),
        ProviderReadinessFact(
            provider="biohub",
            status="ready",
            provider_identity={"fixture": "second"},
            details={},
        ),
        ProviderReadinessFact(
            provider="controlled-proteinmpnn",
            status="failed",
            provider_identity={"fixture": "controlled-proteinmpnn"},
            details={
                "reason": "fixture_probe_failed",
                "credential": "fixture-secret-must-not-leak",
            },
        ),
    ])
    return tuple(facts)


app = create_app(
    module_factory_overrides=DETERMINISTIC_MODULE_OVERRIDES,
    runtime_module_allowlist=ALLOWED_RUNTIME_MODULE_IDS,
    provider_readiness_resolver=unavailable_readiness_resolver,
    provider_aliases=PROVIDER_ALIASES,
)
