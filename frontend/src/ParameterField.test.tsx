// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ParameterField from "./ParameterField";

describe("scientific parameter editing", () => {
  it("applies array and object parameters as typed JSON values", () => {
    const arrayChanged = vi.fn();
    const objectChanged = vi.fn();
    const { rerender } = render(
      <ParameterField
        parameter={{
          name: "regions",
          type: "array",
          default: [],
          display_name: "regions",
          description: "Residue regions.",
          required: true,
        }}
        value={[]}
        onChange={arrayChanged}
      />,
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: '[{"start":1,"end":8}]' },
    });
    fireEvent.blur(screen.getByRole("textbox"));
    expect(arrayChanged).toHaveBeenCalledWith([{ start: 1, end: 8 }]);

    rerender(
      <ParameterField
        parameter={{
          name: "annotation",
          type: "object",
          default: {},
          display_name: "annotation",
          description: "Function annotation.",
          required: true,
        }}
        value={{}}
        onChange={objectChanged}
      />,
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: '{"label":"binding"}' },
    });
    fireEvent.blur(screen.getByRole("textbox"));
    expect(objectChanged).toHaveBeenCalledWith({ label: "binding" });
  });
});
