import { describe, expect, it } from "vitest";

import { validateTemplatePackage } from "@template/flow-schema";

import { buildTemplateFromRecordedEvents } from "./recorder.js";

describe("buildTemplateFromRecordedEvents", () => {
  it("returns valid template package from recorded interactions", () => {
    const result = buildTemplateFromRecordedEvents("https://example.com", [
      {
        kind: "click",
        selector: "#sign-in",
        url: "https://example.com"
      },
      {
        kind: "input",
        selector: "#username",
        value: "agent-user",
        inputType: "text",
        url: "https://example.com"
      }
    ]);

    const parsed = validateTemplatePackage(result);
    expect(parsed.flow[0].type).toBe("openPage");
    expect(parsed.flow[1].type).toBe("click");
    expect(parsed.flow[2].type).toBe("type");
  });
});

