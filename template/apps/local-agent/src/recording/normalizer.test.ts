import { describe, expect, it } from "vitest";

import { normalizeRecordedEvents } from "./normalizer.js";
import type { RawBrowserEvent } from "../types.js";

const entryUrl = "https://example.com/login";

function input(selector: string, value: string, inputType = "text"): RawBrowserEvent {
  return {
    kind: "input",
    selector,
    value,
    inputType,
    url: entryUrl
  };
}

describe("normalizeRecordedEvents", () => {
  it("creates canonical openPage step and maps interactions", () => {
    const steps = normalizeRecordedEvents("https://example.com/form", [
      {
        kind: "click",
        selector: "#start",
        url: "https://example.com/form"
      },
      {
        kind: "input",
        selector: "#name",
        value: "Alice",
        inputType: "text",
        url: "https://example.com/form"
      },
      {
        kind: "keydown",
        key: "Enter",
        url: "https://example.com/form"
      }
    ]);

    expect(steps[0].type).toBe("openPage");
    expect(steps[1].type).toBe("click");
    expect(steps[2].type).toBe("type");
    expect(steps[3].type).toBe("pressKey");
  });

  it("drops duplicate navigation noise", () => {
    const steps = normalizeRecordedEvents("https://example.com/a", [
      { kind: "navigation", url: "https://example.com/b" },
      { kind: "navigation", url: "https://example.com/b" }
    ]);

    const navigationSteps = steps.filter((step) => step.type === "waitForNavigation");
    expect(navigationSteps).toHaveLength(1);
  });

  it("coalesces typing noise into one final type step", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      input("#username", "a"),
      input("#username", "ad"),
      input("#username", "adm"),
      input("#username", "admin")
    ]);

    expect(flow.map((step) => step.type)).toEqual(["openPage", "type"]);
    expect(flow[1]).toMatchObject({
      type: "type",
      selector: "#username",
      value: "admin",
      valueMode: "fixed"
    });
  });

  it("does not coalesce adjacent same-selector typing across different urls", () => {
    const firstUrl = "https://example.com/login";
    const secondUrl = "https://example.com/profile";
    const flow = normalizeRecordedEvents(entryUrl, [
      {
        kind: "input",
        selector: "#username",
        value: "admin",
        inputType: "text",
        url: firstUrl
      },
      {
        kind: "input",
        selector: "#username",
        value: "new-admin",
        inputType: "text",
        url: secondUrl
      }
    ]);

    expect(flow.map((step) => step.type)).toEqual(["openPage", "type", "type"]);
    expect(flow[1]).toMatchObject({
      type: "type",
      selector: "#username",
      value: "admin",
      metadata: {
        url: firstUrl
      }
    });
    expect(flow[2]).toMatchObject({
      type: "type",
      selector: "#username",
      value: "new-admin",
      metadata: {
        url: secondUrl
      }
    });
  });

  it("coalesces adjacent same-url select noise into one final select step", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      {
        kind: "change",
        selector: "#role",
        value: "editor",
        inputType: "select",
        url: entryUrl
      },
      {
        kind: "change",
        selector: "#role",
        value: "admin",
        inputType: "select",
        url: entryUrl
      }
    ]);

    expect(flow.map((step) => step.type)).toEqual(["openPage", "select"]);
    expect(flow[1]).toMatchObject({
      type: "select",
      selector: "#role",
      value: "admin",
      valueMode: "fixed",
      metadata: {
        url: entryUrl,
        inputType: "select"
      }
    });
  });

  it("ignores text input change events because input events already capture final text", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      input("#username", "adm075"),
      {
        kind: "change",
        selector: "#username",
        value: "adm075",
        inputType: "text",
        url: entryUrl
      }
    ]);

    expect(flow.map((step) => step.type)).toEqual(["openPage", "type"]);
    expect(flow[1]).toMatchObject({
      type: "type",
      selector: "#username",
      value: "adm075"
    });
  });

  it("converts radio change events to check steps instead of select steps", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      {
        kind: "change",
        selector: "#location_8",
        value: "P1B",
        inputType: "radio",
        checked: true,
        url: entryUrl
      }
    ]);

    expect(flow.map((step) => step.type)).toEqual(["openPage", "check"]);
    expect(flow[1]).toMatchObject({
      type: "check",
      selector: "#location_8",
      metadata: {
        inputType: "radio"
      }
    });
  });

  it("ignores radio input events because change events capture checked state", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      input("#location_8", "P1B", "radio")
    ]);

    expect(flow.map((step) => step.type)).toEqual(["openPage"]);
  });

  it("preserves interleaved same-selector typing around meaningful actions", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      input("#username", "a"),
      {
        kind: "click",
        selector: "#help",
        url: entryUrl
      },
      input("#username", "admin")
    ]);

    expect(flow.map((step) => step.type)).toEqual(["openPage", "type", "click", "type"]);
    expect(flow[1]).toMatchObject({
      type: "type",
      selector: "#username",
      value: "a",
      valueMode: "fixed"
    });
    expect(flow[3]).toMatchObject({
      type: "type",
      selector: "#username",
      value: "admin",
      valueMode: "fixed"
    });
  });

  it("preserves password final value exactly as a fixed captured value", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      input("#password", "s", "password"),
      input("#password", "se", "password"),
      input("#password", "secret-123", "password")
    ]);

    expect(flow).toHaveLength(2);
    expect(flow[1]).toMatchObject({
      type: "type",
      selector: "#password",
      value: "secret-123",
      valueMode: "fixed",
      metadata: {
        url: entryUrl,
        inputType: "password"
      }
    });
  });

  it("drops duplicate navigation to the same url", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      { kind: "navigation", url: "https://example.com/dashboard" },
      { kind: "navigation", url: "https://example.com/dashboard" }
    ]);

    expect(flow.map((step) => step.type)).toEqual(["openPage", "waitForNavigation"]);
    expect(flow[1].value).toBe("https://example.com/dashboard");
  });

  it("drops exact duplicate clicks for the same selector and url", () => {
    const firstClick: RawBrowserEvent = {
      kind: "click",
      selector: "#login",
      fallback: { text: "Login", tag: "button" },
      url: entryUrl
    };
    const secondClick: RawBrowserEvent = {
      kind: "click",
      selector: "#login",
      fallback: { text: "Login", tag: "button" },
      url: entryUrl
    };

    const flow = normalizeRecordedEvents(entryUrl, [firstClick, secondClick]);

    expect(flow.map((step) => step.type)).toEqual(["openPage", "click"]);
  });

  it("omits empty fallback text so recorded clicks remain schema-valid", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      {
        kind: "click",
        selector: "#icon-only",
        fallback: {
          text: "",
          tag: "button"
        },
        url: entryUrl
      }
    ]);

    expect(flow[1]).toMatchObject({
      type: "click",
      selector: "#icon-only",
      selectorFallback: {
        tag: "button"
      }
    });
    expect(flow[1].selectorFallback).not.toHaveProperty("text");
  });

  it("preserves repeated clicks separated by meaningful input", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      {
        kind: "click",
        selector: "#add",
        url: entryUrl
      },
      input("#name", "Alice"),
      {
        kind: "click",
        selector: "#add",
        url: entryUrl
      }
    ]);

    expect(flow.map((step) => step.type)).toEqual(["openPage", "click", "type", "click"]);
    expect(flow.filter((step) => step.type === "click")).toHaveLength(2);
  });

  it("does not create a step for unsupported idle-like key events", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      { kind: "keydown", key: "Shift", url: entryUrl },
      { kind: "keydown", key: "Control", url: entryUrl }
    ]);

    expect(flow.map((step) => step.type)).toEqual(["openPage"]);
  });
});
