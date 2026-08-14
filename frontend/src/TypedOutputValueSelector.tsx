import { useEffect, useState } from "react";
import {
  fetchTypedOutputValue,
  type RetrievedTypedValue,
  type TypedOutputDescriptor,
} from "./typedOutputs";

interface TypedOutputValueSelectorProps {
  projectId: string;
  runId: string;
  output: TypedOutputDescriptor;
  onRetrieved: (value: RetrievedTypedValue) => void;
}

export default function TypedOutputValueSelector({
  projectId,
  runId,
  output,
  onRetrieved,
}: TypedOutputValueSelectorProps) {
  const [valueIndex, setValueIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValueIndex(0);
    setError(null);
  }, [output]);

  const retrieve = async () => {
    setLoading(true);
    setError(null);
    try {
      onRetrieved(
        await fetchTypedOutputValue(projectId, runId, output, valueIndex),
      );
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <label>
        Value
        <select
          disabled={output.value_count === 0}
          value={valueIndex}
          onChange={(event) => setValueIndex(Number(event.target.value))}
        >
          {Array.from({ length: output.value_count }, (_, index) => (
            <option key={index} value={index}>
              {index + 1} / {output.value_count}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        disabled={loading || output.value_count === 0}
        onClick={retrieve}
      >
        {loading ? "Loading…" : "Retrieve value"}
      </button>
      {output.value_count === 0 && <p>This output contains no values.</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
