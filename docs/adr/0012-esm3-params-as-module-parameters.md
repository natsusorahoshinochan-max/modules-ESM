---
status: superseded by ADR-0027
---

# ESM3 generation parameters are module-level parameters

The text below records the v1 decision. Its still-valid rationale is that
generation configuration does not belong to `ProteinPrompt`; ADR-0027 replaces
the blanket ModuleDefinition ownership rule with classification by scientific
meaning and execution scope.

ESM3 generation settings (track, schedule, strategy, num_steps, temperature,
top_p) are declared as module parameters in each ESM3 module's
ModuleDefinition, not attached to ProteinPrompt.

Rationale: Generate Sequence and Generate Structure may need different
settings (e.g., fewer steps for sequence, more for structure). Attaching
generation config to ProteinPrompt would also pollute a shared type that
non-ESM3 modules (ProteinMPNN, scoring, selection) consume. Module parameters
are the established pattern for node-specific configuration.

For v2, only settings whose scientific
meaning is stable across every Execution Binding remain Node parameters.
Method- or Adapter-specific settings belong to the Binding, while Environment
Configuration is not a Workflow parameter.
