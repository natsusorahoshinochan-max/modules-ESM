# Ticket 10 — Keep the object store simple

Status: superseded and simplified on 2026-08-17

Automatic immutable-object garbage collection is removed. The object store
writes admitted bytes once and reads them by retained content reference. A
single-user development project can clear generated project state explicitly
when space reclamation is needed.

There is no object graph traversal, writer registry, staging recovery, symlink
scan, or GC failure channel.
