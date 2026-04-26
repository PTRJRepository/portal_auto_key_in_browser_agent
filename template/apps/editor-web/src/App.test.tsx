import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import App from "./App";

vi.mock("./api/agent-client", () => ({
  exportTemplate: vi.fn(),
  getTemplate: vi.fn(),
  importTemplate: vi.fn(),
  listTemplates: vi.fn().mockResolvedValue([]),
  runTemplate: vi.fn(),
  startRecording: vi.fn(),
  stopRecording: vi.fn(),
  wsUrl: vi.fn(() => "ws://localhost:9001/ws")
}));

describe("App", () => {
  it("renders the rebuilt workflow builder shell", async () => {
    render(<App />);

    expect(await screen.findByText("Template Creator")).toBeInTheDocument();
    expect(screen.getByText("Workflow Canvas")).toBeInTheDocument();
    expect(screen.getByText("Agent Inspector")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start Recording/i })).toBeInTheDocument();
  });
});
