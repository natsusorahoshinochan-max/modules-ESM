import { useEffect, useState } from "react";
import TypedOutputValueSelector from "./TypedOutputValueSelector";
import type {
  RetrievedTypedValue,
  TypedOutputDescriptor,
} from "./typedOutputs";

interface TypedOutputExplorerProps {
  activeProjectId: string | null;
}

interface RunProjection {
  outputs: TypedOutputDescriptor[];
}

interface LoadedRun {
  projectId: string;
  runId: string;
  outputs: TypedOutputDescriptor[];
}

export default function TypedOutputExplorer({
  activeProjectId,
}: TypedOutputExplorerProps) {
  const [projectId, setProjectId] = useState(activeProjectId ?? "");
  const [runId, setRunId] = useState("");
  const [loadedRun, setLoadedRun] = useState<LoadedRun | null>(null);
  const [outputIndex, setOutputIndex] = useState(0);
  const [retrieved, setRetrieved] = useState<RetrievedTypedValue | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (activeProjectId !== null) {
      setProjectId(activeProjectId);
      setLoadedRun(null);
      setRetrieved(null);
    }
  }, [activeProjectId]);

  const loadProjection = async () => {
    setLoading(true);
    setError(null);
    setRetrieved(null);
    const requestedProjectId = projectId;
    const requestedRunId = runId;
    try {
      const response = await fetch(
        `/api/v2/projects/${encodeURIComponent(requestedProjectId)}/runs/` +
          encodeURIComponent(requestedRunId),
      );
      if (!response.ok) {
        setLoadedRun(null);
        setError(`Run Projection retrieval failed (${response.status})`);
        return;
      }
      const projection = (await response.json()) as RunProjection;
      setLoadedRun({
        projectId: requestedProjectId,
        runId: requestedRunId,
        outputs: projection.outputs,
      });
      setOutputIndex(0);
    } finally {
      setLoading(false);
    }
  };

  const output = loadedRun?.outputs[outputIndex];
  return (
    <div className="viewer-panel">
      <h3>Typed Output Values</h3>
      <label>
        Project
        <input
          value={projectId}
          disabled={loading}
          onChange={(event) => {
            setProjectId(event.target.value);
            setLoadedRun(null);
            setRetrieved(null);
          }}
        />
      </label>
      <label>
        Run
        <input
          value={runId}
          disabled={loading}
          onChange={(event) => {
            setRunId(event.target.value);
            setLoadedRun(null);
            setRetrieved(null);
          }}
        />
      </label>
      <button
        type="button"
        disabled={loading || projectId === "" || runId === ""}
        onClick={loadProjection}
      >
        {loading ? "Loading…" : "Load outputs"}
      </button>
      {error && <p role="alert">{error}</p>}
      {loadedRun !== null && output !== undefined && (
        <>
          <label>
            Output
            <select
              value={outputIndex}
              onChange={(event) => {
                setOutputIndex(Number(event.target.value));
                setRetrieved(null);
              }}
            >
              {loadedRun.outputs.map((item, index) => (
                <option
                  key={`${item.node_id}:${item.output_port}`}
                  value={index}
                >
                  {item.node_id}.{item.output_port}
                </option>
              ))}
            </select>
          </label>
          <TypedOutputValueSelector
            projectId={loadedRun.projectId}
            runId={loadedRun.runId}
            output={output}
            onRetrieved={setRetrieved}
          />
        </>
      )}
      {retrieved && (
        <pre>{new TextDecoder().decode(retrieved.canonicalBytes)}</pre>
      )}
    </div>
  );
}
