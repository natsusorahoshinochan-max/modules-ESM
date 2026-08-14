import { useEffect, useState, type ReactNode } from "react";
import type { NodeParameterView } from "./currentProtocol";

export default function ParameterField({
  parameter,
  value,
  onChange,
}: {
  parameter: NodeParameterView;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const structured = parameter.type === "array" || parameter.type === "object";
  const [structuredText, setStructuredText] = useState("");
  const [structuredError, setStructuredError] = useState<string | null>(null);

  useEffect(() => {
    if (structured) {
      setStructuredText(
        JSON.stringify(value ?? parameter.default, null, 2) ?? "",
      );
      setStructuredError(null);
    }
  }, [parameter.default, parameter.name, structured, value]);

  let input: ReactNode;
  if (structured) {
    input = (
      <>
        <textarea
          value={structuredText}
          required={parameter.required}
          onChange={(event) => setStructuredText(event.target.value)}
          onBlur={() => {
            try {
              const parsed = JSON.parse(structuredText) as unknown;
              const shapeMatches =
                parameter.type === "array"
                  ? Array.isArray(parsed)
                  : typeof parsed === "object" &&
                    parsed !== null &&
                    !Array.isArray(parsed);
              if (!shapeMatches) {
                setStructuredError(
                  `${parameter.display_name} must be a JSON ${parameter.type}`,
                );
                return;
              }
              setStructuredError(null);
              onChange(parsed);
            } catch (failure) {
              if (!(failure instanceof SyntaxError)) throw failure;
              setStructuredError(
                `${parameter.display_name} must contain valid JSON`,
              );
            }
          }}
        />
        {structuredError && <p role="alert">{structuredError}</p>}
      </>
    );
  } else if (parameter.options) {
    input = (
      <select
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
      >
        {parameter.options.map((option) => (
          <option key={String(option)} value={String(option)}>
            {String(option)}
          </option>
        ))}
      </select>
    );
  } else if (parameter.type === "boolean") {
    input = (
      <input
        type="checkbox"
        checked={Boolean(value)}
        onChange={(event) => onChange(event.target.checked)}
      />
    );
  } else if (parameter.type === "integer" || parameter.type === "number") {
    input = (
      <input
        type="number"
        value={String(value ?? "")}
        min={parameter.min}
        max={parameter.max}
        step={parameter.type === "integer" ? 1 : "any"}
        onChange={(event) =>
          onChange(
            parameter.type === "integer"
              ? Number.parseInt(event.target.value, 10)
              : Number.parseFloat(event.target.value),
          )
        }
      />
    );
  } else {
    input = (
      <input
        type="text"
        value={String(value ?? "")}
        required={parameter.required}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  return (
    <div className="param-field">
      <label>
        {parameter.display_name}
        {parameter.description && (
          <span className="param-desc-hint"> — {parameter.description}</span>
        )}
      </label>
      {input}
    </div>
  );
}
