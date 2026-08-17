# 06 — Node failure origins（历史，已简化）

**Status:** completed historical ticket; superseded by ADR-0039

The retained current contract distinguishes pre-Operation Binding failure,
scientific Operation failure, and Node Outcome Publication failure. The former
Result Identity conflict origin was removed: Result Identity is a scientific
Cache key, not a cross-Run authority. Historical matrix results below the
former design are not current requirements. Do not restore conflict checks,
`security-failure`, or `provider-isolation` gates from this ticket.
