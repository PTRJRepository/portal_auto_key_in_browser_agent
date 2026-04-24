import { describe, expect, it } from "vitest";

import { normalizeStartUrl } from "./url-utils.js";

describe("normalizeStartUrl", () => {
  it("adds https protocol when missing", () => {
    const result = normalizeStartUrl("example.com/login");
    expect(result).toBe("https://example.com/login");
  });

  it("keeps valid absolute URL", () => {
    const result = normalizeStartUrl("https://example.com/a?x=1");
    expect(result).toBe("https://example.com/a?x=1");
  });

  it("throws on invalid URL", () => {
    expect(() => normalizeStartUrl("http://")).toThrowError(/URL tidak valid/i);
  });
});

