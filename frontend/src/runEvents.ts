export interface RunEventEnvelope {
  event: { type: string };
}

interface NodeAttemptStarted {
  type: "node_attempt_started";
  node_id: string;
}

interface NodeDisposition {
  type: "node_disposition";
  disposition: { node_id: string; outcome: string };
}

export function nodeStateFromRunEvent(
  envelope: RunEventEnvelope,
): { nodeId: string; state: string } | null {
  const event = envelope.event;
  if (event.type === "node_attempt_started") {
    const started = event as NodeAttemptStarted;
    return { nodeId: started.node_id, state: "running" };
  }
  if (event.type === "node_disposition") {
    const terminal = event as NodeDisposition;
    return {
      nodeId: terminal.disposition.node_id,
      state:
        terminal.disposition.outcome === "succeeded"
          ? "completed"
          : terminal.disposition.outcome,
    };
  }
  return null;
}
