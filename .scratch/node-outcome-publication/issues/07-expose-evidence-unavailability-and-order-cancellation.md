# 07 — Evidence 与 cancellation（历史，已简化）

**Status:** completed historical ticket; superseded by the trusted-core redesign

The current runtime keeps the single Node publication seam and ordinary
cancellation ordering needed by the public Run contract. It no longer claims
fsync/durability confirmation, final-name ambiguity recovery, or a filesystem
fault matrix. Owner-written records are trusted after publication; ordinary
I/O failure fails fast without a recovery state machine.
