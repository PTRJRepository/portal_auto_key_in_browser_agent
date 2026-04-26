import { describe, expect, it } from "vitest";

import { getRuntimeConfig } from "./server.js";

describe("monolith server config", () => {
  it("defaults to port 9001 and /api namespace", () => {
    const config = getRuntimeConfig({});

    expect(config.port).toBe(9001);
    expect(config.apiPrefix).toBe("/api");
    expect(config.wsPath).toBe("/ws");
  });

  it("allows PORT override for test environments", () => {
    const config = getRuntimeConfig({ PORT: "9100" });

    expect(config.port).toBe(9100);
  });
});
