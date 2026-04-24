import { describe, expect, it } from "vitest";

import {
  createTemplatePackage,
  FLOW_SCHEMA_VERSION,
  optimizeTemplatePackage,
  serializeTemplatePackage,
  validateTemplatePackage
} from "./index.js";

describe("flow schema", () => {
  it("validates a canonical template package", () => {
    const templatePackage = createTemplatePackage({
      id: "tpl_1",
      name: "Record Login",
      entryUrl: "https://example.com/login",
      flow: [
        {
          id: "step_open",
          type: "openPage",
          label: "Open Login Page",
          value: "https://example.com/login",
          timeoutMs: 15000,
          continueOnError: false
        },
        {
          id: "step_type",
          type: "type",
          label: "Type username",
          selector: "#username",
          value: "john",
          timeoutMs: 15000,
          continueOnError: false
        }
      ],
      variables: [{ name: "username", label: "Username" }]
    });

    expect(templatePackage.schemaVersion).toBe(FLOW_SCHEMA_VERSION);
    expect(templatePackage.flow).toHaveLength(2);
  });

  it("rejects click step without selector", () => {
    expect(() =>
      validateTemplatePackage({
        schemaVersion: FLOW_SCHEMA_VERSION,
        template: {
          id: "tpl_2",
          name: "Bad template",
          description: "",
          version: "1.0.0",
          createdAt: new Date().toISOString()
        },
        entry: { url: "https://example.com" },
        variables: [],
        flow: [
          {
            id: "step_click",
            type: "click",
            label: "Click submit",
            timeoutMs: 1000,
            continueOnError: false
          }
        ],
        runtime: {
          defaultTimeoutMs: 1000,
          sessionMode: "fresh"
        }
      })
    ).toThrowError(/selector is required/i);
  });

  it("serializes package to readable JSON", () => {
    const templatePackage = createTemplatePackage({
      id: "tpl_3",
      name: "Serialize test",
      entryUrl: "https://example.com",
      flow: [
        {
          id: "step_open",
          type: "openPage",
          label: "Open",
          value: "https://example.com",
          timeoutMs: 15000,
          continueOnError: false
        }
      ]
    });

    const serialized = serializeTemplatePackage(templatePackage);
    expect(serialized).toContain('"template"');
    expect(serialized).toContain('"flow"');
  });

  it("optimizes duplicated consecutive and noisy input steps", () => {
    const templatePackage = createTemplatePackage({
      id: "tpl_opt",
      name: "Optimize me",
      entryUrl: "https://example.com/form",
      flow: [
        {
          id: "step_open",
          type: "openPage",
          label: "Open",
          value: "https://example.com/form",
          timeoutMs: 15000,
          continueOnError: false
        },
        {
          id: "step_type_1",
          type: "type",
          label: "Type name",
          selector: "#name",
          value: "A",
          timeoutMs: 15000,
          continueOnError: false
        },
        {
          id: "step_type_2",
          type: "type",
          label: "Type name",
          selector: "#name",
          value: "Alice",
          timeoutMs: 15000,
          continueOnError: false
        },
        {
          id: "step_click_1",
          type: "click",
          label: "Click submit",
          selector: "#submit",
          timeoutMs: 15000,
          continueOnError: false
        },
        {
          id: "step_click_2",
          type: "click",
          label: "Click submit",
          selector: "#submit",
          timeoutMs: 15000,
          continueOnError: false
        }
      ]
    });

    const optimized = optimizeTemplatePackage(templatePackage);
    expect(optimized.report.removedSteps).toBe(2);
    expect(optimized.templatePackage.flow).toHaveLength(3);
    expect(optimized.templatePackage.flow[1].value).toBe("Alice");
  });
});
