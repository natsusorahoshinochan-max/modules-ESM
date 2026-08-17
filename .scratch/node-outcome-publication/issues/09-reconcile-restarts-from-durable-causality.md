# Ticket 09 — Honest lightweight restart

Status: superseded and simplified on 2026-08-17

Terminal Runs reload from their Ledger. A Run that was still running when the
process ended receives one `run_terminal` with status `interrupted`.

Restart does not infer or synthesize missing Engine Invocation, Operation
Attempt, Node Attempt, Node disposition, or Selection conclusions. There is no
restart audit fact or reconciliation state machine.
