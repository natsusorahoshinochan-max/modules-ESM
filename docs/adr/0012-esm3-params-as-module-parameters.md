# ESM3 generation parameters are module-level parameters

ESM3 generation settings (track, schedule, strategy, num_steps, temperature,
top_p) are declared as module parameters in each ESM3 module's
ModuleDefinition, not attached to ProteinPrompt.

Rationale: Generate Sequence and Generate Structure may need different
settings (e.g., fewer steps for sequence, more for structure). Attaching
generation config to ProteinPrompt would also pollute a shared type that
non-ESM3 modules (ProteinMPNN, scoring, selection) consume. Module parameters
are the established pattern for node-specific configuration.
