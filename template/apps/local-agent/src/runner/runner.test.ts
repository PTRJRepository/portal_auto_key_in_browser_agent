import { describe, expect, it } from "vitest";

import { runnerInternals } from "./runner.js";

describe("runnerInternals.resolveStepValue", () => {
  it("uses bound variable if variableRef exists", () => {
    const value = runnerInternals.resolveStepValue(
      {
        id: "step_1",
        type: "type",
        label: "Type full name",
        selector: "#full_name",
        value: "fallback",
        variableRef: "full_name",
        timeoutMs: 2000,
        continueOnError: false
      },
      { full_name: "Budi Santoso" }
    );

    expect(value).toBe("Budi Santoso");
  });

  it("falls back to static value when variable is missing", () => {
    const value = runnerInternals.resolveStepValue(
      {
        id: "step_2",
        type: "type",
        label: "Type city",
        selector: "#city",
        value: "Jakarta",
        variableRef: "city",
        timeoutMs: 2000,
        continueOnError: false
      },
      {}
    );

    expect(value).toBe("Jakarta");
  });

  it("generates dynamic value from valueMode", () => {
    const timestamp = runnerInternals.resolveStepValue(
      {
        id: "step_3",
        type: "type",
        label: "Type timestamp",
        selector: "#created_at",
        valueMode: "generatedTimestamp",
        timeoutMs: 2000,
        continueOnError: false
      },
      {}
    );

    const uuid = runnerInternals.resolveStepValue(
      {
        id: "step_4",
        type: "type",
        label: "Type UUID",
        selector: "#uuid",
        valueMode: "generatedUuid",
        timeoutMs: 2000,
        continueOnError: false
      },
      {}
    );

    expect(timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(uuid).toMatch(/^[0-9a-f-]{36}$/i);
  });
});

describe("runnerInternals.calculateFidelity", () => {
  it("returns 100% when all expected steps succeed", () => {
    const fidelity = runnerInternals.calculateFidelity(
      3,
      [
        { stepId: "a", type: "openPage", status: "success" },
        { stepId: "b", type: "click", status: "success" },
        { stepId: "c", type: "type", status: "success" }
      ],
      "strict"
    );

    expect(fidelity.scorePercent).toBe(100);
    expect(fidelity.exactMatch).toBe(true);
  });

  it("returns below 100% when some steps fail or skipped", () => {
    const fidelity = runnerInternals.calculateFidelity(
      4,
      [
        { stepId: "a", type: "openPage", status: "success" },
        { stepId: "b", type: "click", status: "failed", message: "not found" },
        { stepId: "c", type: "type", status: "skipped" }
      ],
      "strict"
    );

    expect(fidelity.scorePercent).toBeLessThan(100);
    expect(fidelity.exactMatch).toBe(false);
  });
});

describe("runnerInternals.coerceLegacyInputStep", () => {
  it("replays legacy select-on-text-input as a type step", () => {
    const coerced = runnerInternals.coerceLegacyInputStep({
      id: "legacy_username_change",
      type: "select",
      label: "Select: #txtUsername",
      selector: "#txtUsername",
      value: "adm075",
      timeoutMs: 15000,
      continueOnError: false,
      metadata: {
        inputType: "text"
      }
    });

    expect(coerced.type).toBe("type");
  });

  it("replays legacy type/select-on-radio as a check step", () => {
    const typeCoerced = runnerInternals.coerceLegacyInputStep({
      id: "legacy_radio_input",
      type: "type",
      label: "Type: #location_8",
      selector: "#location_8",
      value: "P1B",
      timeoutMs: 15000,
      continueOnError: false,
      metadata: {
        inputType: "radio"
      }
    });

    const selectCoerced = runnerInternals.coerceLegacyInputStep({
      id: "legacy_radio_change",
      type: "select",
      label: "Select: #location_8",
      selector: "#location_8",
      value: "P1B",
      timeoutMs: 15000,
      continueOnError: false,
      metadata: {
        inputType: "radio"
      }
    });

    expect(typeCoerced.type).toBe("check");
    expect(selectCoerced.type).toBe("check");
  });
});
