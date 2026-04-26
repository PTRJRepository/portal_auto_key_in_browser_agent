import { describe, expect, it } from "vitest";

import { apiUrl, wsUrl } from "./agent-client";

describe("agent-client urls", () => {
  it("uses same-origin /api routes by default", () => {
    expect(apiUrl("/templates")).toBe("/api/templates");
  });

  it("builds websocket path from current location", () => {
    expect(wsUrl(new URL("http://localhost:9001/"))).toBe("ws://localhost:9001/ws");
  });
});
