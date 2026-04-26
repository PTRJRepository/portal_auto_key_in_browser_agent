import { describe, it, expect } from "vitest";
import { buildSelectorCandidates } from "./selector-resolver.js";
import type { FlowStep } from "@template/flow-schema";

describe("buildSelectorCandidates", () => {
  it("returns primary selector with highest weight", () => {
    const step: FlowStep = {
      id: "test",
      type: "click",
      label: "Test",
      selector: "#btnSubmit",
      timeoutMs: 15000
    };

    const candidates = buildSelectorCandidates(step);
    expect(candidates[0].selector).toBe("#btnSubmit");
    expect(candidates[0].weight).toBe(100);
    expect(candidates[0].type).toBe("css");
  });

  it("includes ID extracted from CSS selector fallback", () => {
    const step: FlowStep = {
      id: "test",
      type: "click",
      label: "Test",
      selectorFallback: {
        css: "#MainContent_btnOkay"
      },
      timeoutMs: 15000
    };

    const candidates = buildSelectorCandidates(step);
    const idCandidate = candidates.find(c => c.type === "id");
    expect(idCandidate).toBeDefined();
    expect(idCandidate?.selector).toBe("#MainContent_btnOkay");
    expect(idCandidate?.weight).toBe(95);
  });

  it("includes text fallback", () => {
    const step: FlowStep = {
      id: "test",
      type: "click",
      label: "Test",
      selectorFallback: {
        text: "ESTATE PARIT GUNUNG 1B"
      },
      timeoutMs: 15000
    };

    const candidates = buildSelectorCandidates(step);
    const textCandidate = candidates.find(c => c.type === "text");
    expect(textCandidate).toBeDefined();
    expect(textCandidate?.selector).toBe("text=ESTATE PARIT GUNUNG 1B");
    expect(textCandidate?.weight).toBe(80);
  });

  it("includes role fallback", () => {
    const step: FlowStep = {
      id: "test",
      type: "click",
      label: "Test",
      selectorFallback: {
        role: "button"
      },
      timeoutMs: 15000
    };

    const candidates = buildSelectorCandidates(step);
    const roleCandidate = candidates.find(c => c.type === "role");
    expect(roleCandidate).toBeDefined();
    expect(roleCandidate?.selector).toBe('[role="button"]');
    expect(roleCandidate?.weight).toBe(70);
  });

  it("includes tag fallback", () => {
    const step: FlowStep = {
      id: "test",
      type: "click",
      label: "Test",
      selectorFallback: {
        tag: "input"
      },
      timeoutMs: 15000
    };

    const candidates = buildSelectorCandidates(step);
    const tagCandidate = candidates.find(c => c.type === "tag");
    expect(tagCandidate).toBeDefined();
    expect(tagCandidate?.selector).toBe("input");
    expect(tagCandidate?.weight).toBe(40);
  });

  it("sorts candidates by weight descending", () => {
    const step: FlowStep = {
      id: "test",
      type: "click",
      label: "Test",
      selector: "#primary",
      selectorFallback: {
        css: ".secondary",
        text: "text fallback",
        role: "button",
        tag: "div"
      },
      timeoutMs: 15000
    };

    const candidates = buildSelectorCandidates(step);
    const weights = candidates.map(c => c.weight);

    for (let i = 1; i < weights.length; i++) {
      expect(weights[i - 1]).toBeGreaterThanOrEqual(weights[i]);
    }
  });
});