# 19b — Non-blocking subprocess execution

**What to build:** The executor supports async module execution. Modules that call external binaries (starting with `compute.dssp`) use `asyncio.create_subprocess_exec` instead of synchronous `subprocess.run`. The executor `await`s each node's result, allowing the event loop to process WebSocket messages and other tasks during external process waits. Nodes that fail due to subprocess errors report clean failures through the existing WebSocket state-change channel.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `WorkflowModule` gains an optional `async run_async()` method; executor calls `run_async()` if defined, falls back to `run()` in a thread pool
- [ ] `compute.dssp` module uses `asyncio.create_subprocess_exec` via `run_async()`
- [ ] Subprocess timeout parameter on `compute.dssp` (default 30s), timeout produces clean failure
- [ ] mkdssp not installed → clear error message through WebSocket, node marked failed, downstream blocked
- [ ] Existing synchronous modules (`run()`) continue to work unchanged via thread-pool execution
- [ ] Unit tests: mock subprocess success/failure/timeout paths
- [ ] Integration test: seed workflow execution with mocked DSSP completes without hanging
