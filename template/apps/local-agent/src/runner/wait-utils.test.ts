import { describe, it, expect, vi } from "vitest";
import { retryWithBackoff } from "./wait-utils.js";

describe("retryWithBackoff", () => {
  it("succeeds on first attempt when fn succeeds", async () => {
    const result = await retryWithBackoff(() => Promise.resolve("success"));
    expect(result).toBe("success");
  });

  it("retries on failure and eventually succeeds", async () => {
    let attempts = 0;
    const result = await retryWithBackoff(
      () => {
        attempts++;
        if (attempts < 3) throw new Error("fail");
        return Promise.resolve("success");
      },
      { maxAttempts: 5, baseDelayMs: 10 }
    );
    expect(result).toBe("success");
    expect(attempts).toBe(3);
  });

  it("throws after max attempts exceeded", async () => {
    await expect(
      retryWithBackoff(
        () => Promise.reject(new Error("always fail")),
        { maxAttempts: 3, baseDelayMs: 10 }
      )
    ).rejects.toThrow("always fail");
  });

  it("retries with correct delay progression", async () => {
    let attempts = 0;
    const startTime = Date.now();

    await retryWithBackoff(
      () => {
        attempts++;
        if (attempts < 3) throw new Error("fail");
        return Promise.resolve("done");
      },
      { maxAttempts: 3, baseDelayMs: 50, maxDelayMs: 500, backoffMultiplier: 2 }
    );

    expect(attempts).toBe(3);
    const elapsed = Date.now() - startTime;
    expect(elapsed).toBeGreaterThanOrEqual(50);
  });
});