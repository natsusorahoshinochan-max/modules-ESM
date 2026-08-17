# 19c — Frontend execution resilience

> **Status: superseded historical v1; do not implement.** The v1 runtime was removed. This file is retained only as historical planning evidence and creates no current compatibility requirement.

**What to build:** The Run button provides feedback during long executions and recovers gracefully from failures. An execution timeout (default 5 minutes) resets the UI if the server stops sending updates. WebSocket disconnection during execution is detected and shown to the user. Node-level failure details from the server are displayed inline on the canvas.

**Blocked by:** 19b — needs non-blocking execution on the server to test timeout and failure behavior.

**Status:** superseded

- [ ] Execution timeout: configurable limit (default 300s), UI resets from "Running..." to idle with a timeout notification if exceeded
- [ ] WebSocket disconnect detection during execution: auto-reset running state, show reconnection toast
- [ ] Failed nodes display red border with error details visible in the parameter panel on click
- [ ] The `runWorkflow` payload correctly serializes edge handles even when ReactFlow hasn't visually connected edges
- [ ] Seed workflow opens and runs to completion (with valid API keys) or shows clear per-node failure reasons
