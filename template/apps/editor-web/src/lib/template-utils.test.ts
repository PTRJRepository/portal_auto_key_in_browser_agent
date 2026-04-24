import { describe, expect, it } from "vitest";

import type { TemplatePackage } from "@template/flow-schema";

import { convertStepValueToVariable, reorderSteps, updateStep } from "./template-utils";

const fixture: TemplatePackage = {
  schemaVersion: "1.0.0",
  template: {
    id: "tpl_01",
    name: "Fixture",
    description: "",
    version: "1.0.0",
    createdAt: new Date().toISOString()
  },
  entry: {
    url: "https://example.com"
  },
  variables: [],
  flow: [
    {
      id: "step_1",
      type: "openPage",
      label: "Open",
      value: "https://example.com",
      timeoutMs: 1000,
      continueOnError: false
    },
    {
      id: "step_2",
      type: "type",
      label: "Input Name",
      selector: "#name",
      value: "Alice",
      timeoutMs: 1000,
      continueOnError: false
    }
  ],
  runtime: {
    defaultTimeoutMs: 1000,
    sessionMode: "fresh"
  }
};

describe("template-utils", () => {
  it("reorders steps", () => {
    const reordered = reorderSteps(fixture.flow, 1, 0);
    expect(reordered[0].id).toBe("step_2");
  });

  it("updates step fields", () => {
    const updated = updateStep(fixture, "step_2", { label: "Type customer name" });
    expect(updated.flow[1].label).toBe("Type customer name");
  });

  it("converts fixed value into template variable", () => {
    const updated = convertStepValueToVariable(fixture, "step_2");
    expect(updated.variables).toHaveLength(1);
    expect(updated.flow[1].variableRef).toBe(updated.variables[0].name);
    expect(updated.variables[0].defaultValue).toBe("Alice");
  });
});

