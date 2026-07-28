---
status: superseded by ADR-0018
---

# Two-phase module registration: register() function + discover_modules()

ADR-0018 replaces this per-subpackage registration contract with a unified
Module Package registration boundary. The text below is retained as the
historical v1 decision.

Each module subpackage (modules/esm3/, modules/proteinmpnn/, etc.) exposes a
register(registry) function in its __init__.py that explicitly registers all
modules that subpackage provides. The top-level discover_modules() function
imports every subpackage under modules/ and calls its register().

The registry is fully populated at startup and never modified at runtime. No
dynamic loading or hot-reloading. This pattern keeps discovery transparent
(one import per subpackage) while letting each subpackage control exactly what
it exposes.

Rejected alternatives: pure auto-discovery (fragile filename conventions),
pure explicit registration (easy to forget a module at the top level).
