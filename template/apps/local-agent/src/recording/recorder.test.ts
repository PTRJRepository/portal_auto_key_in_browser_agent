import { describe, expect, it } from "vitest";

import { validateTemplatePackage } from "@template/flow-schema";

import { buildTemplateFromRecordedEvents, RecorderService } from "./recorder.js";

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

describe("RecorderService", () => {
  it("stops and returns a template even when browser resources are already closed", async () => {
    const publishedEvents: unknown[] = [];
    const recorder = new RecorderService((event) => publishedEvents.push(event));
    const sessions = (
      recorder as unknown as {
        sessions: Map<string, unknown>;
      }
    ).sessions;

    sessions.set("closed-browser-session", {
      sessionId: "closed-browser-session",
      url: "https://example.com",
      startedAt: new Date().toISOString(),
      browser: {
        close: async () => {
          throw new Error("Browser has been closed");
        }
      },
      context: {
        close: async () => {
          throw new Error("Context has been closed");
        }
      },
      page: {},
      events: [
        {
          kind: "input",
          selector: "#username",
          value: "agent-user",
          inputType: "text",
          url: "https://example.com"
        }
      ]
    });

    const template = await recorder.stopRecording("closed-browser-session");

    expect(validateTemplatePackage(template).flow.at(-1)).toMatchObject({
      type: "type",
      selector: "#username",
      value: "agent-user"
    });
    expect(sessions.has("closed-browser-session")).toBe(false);
    expect(publishedEvents).toContainEqual({
      type: "recording.stopped",
      payload: {
        sessionId: "closed-browser-session",
        templateId: template.template.id
      }
    });
  });
});
