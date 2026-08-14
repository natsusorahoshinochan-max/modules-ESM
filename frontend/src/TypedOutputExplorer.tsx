import { useEffect, useState } from "react";
import TypedOutputValueSelector from "./TypedOutputValueSelector";
import type {
  RetrievedTypedValue,
  TypedOutputDescriptor,
} from "./typedOutputs";

interface TypedOutputExplorerProps {
  activeProjectId: string | null;
  activeRunId: string | null;
}

interface RunProjection {
  outputs: TypedOutputDescriptor[];
  artifact_index: ArtifactDescriptor[];
}

interface ArtifactDescriptor {
  artifact_reference: string;
  node_id: string;
  output_port: string;
  filename: string;
  media_type: string;
  size: number;
  content_digest: string;
}

interface LoadedRun {
  projectId: string;
  runId: string;
  outputs: TypedOutputDescriptor[];
  artifacts: ArtifactDescriptor[];
}

export default function TypedOutputExplorer({
  activeProjectId,
  activeRunId,
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

  useEffect(() => {
    if (activeRunId !== null) {
      setRunId(activeRunId);
      setLoadedRun(null);
      setRetrieved(null);
    }
  }, [activeRunId]);

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
        artifacts: projection.artifact_index,
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
          <dl className="typed-output-metadata">
            <dt>Port Type</dt>
            <dd>
              {output.port_type.contract_id}@{output.port_type.contract_version}
            </dd>
            <dt>Port digest</dt>
            <dd><code>{output.content_digest}</code></dd>
            <dt>Value count</dt>
            <dd>{output.value_count}</dd>
            <dt>Result Identity</dt>
            <dd><code>{output.result_identity}</code></dd>
            <dt>Materialization</dt>
            <dd>
              {output.materialization.resolution} in {output.materialization.run_id}
            </dd>
            <dt>Producer</dt>
            <dd>
              {output.producer_provenance.producer_run_id} /{" "}
              {output.producer_provenance.output_port} /{" "}
              <code>
                {output.producer_provenance.producer_result_identity}
              </code>
            </dd>
          </dl>
        </>
      )}
      {loadedRun !== null && loadedRun.artifacts.length > 0 && (
        <section>
          <h4>Artifacts</h4>
          <ul className="artifact-list">
            {loadedRun.artifacts.map((artifact) => (
              <li key={artifact.artifact_reference}>
                <a
                  href={
                    `/api/v2/projects/${encodeURIComponent(loadedRun.projectId)}` +
                    `/runs/${encodeURIComponent(loadedRun.runId)}/artifacts/` +
                    encodeURIComponent(artifact.artifact_reference)
                  }
                >
                  {artifact.filename}
                </a>
                <small>
                  {artifact.node_id}.{artifact.output_port} · {artifact.media_type} ·{" "}
                  {artifact.size} bytes · {artifact.content_digest}
                </small>
              </li>
            ))}
          </ul>
        </section>
      )}
      {retrieved && (
        <pre>{new TextDecoder().decode(retrieved.canonicalBytes)}</pre>
      )}
    </div>
  );
}
