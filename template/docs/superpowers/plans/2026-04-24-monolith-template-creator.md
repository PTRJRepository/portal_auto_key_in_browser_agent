# Monolith Template Creator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the browser automation template creator as one monolith on `http://localhost:9001` with a n8n-like UI and anti-redundant recording pipeline.

**Architecture:** Keep the existing workspace, but change the runtime experience to one local server. The local-agent Express server serves the built React UI, exposes `/api/*` endpoints plus `/ws`, and owns Playwright recording/replay. The React editor is rebuilt as a workflow builder while reusing the shared `@template/flow-schema` contract.

**Tech Stack:** TypeScript, React 19, React Flow, Vite, Express 5, WebSocket `ws`, Playwright Chromium, Vitest, Zod.

---

## File Structure

- Modify `package.json`: add one-command monolith scripts.
- Modify `apps/local-agent/src/server.ts`: move to port `9001`, add `/api/*` routes, serve built UI static assets, keep legacy routes only if needed.
- Modify `apps/local-agent/src/recording/normalizer.ts`: replace weak consecutive-only dedupe with intent-level coalescing.
- Modify `apps/local-agent/src/recording/normalizer.test.ts`: add tests for typing coalescing, password preservation, duplicate navigation, duplicate click, and idle/no-op behavior.
- Modify `apps/local-agent/src/recording/recorder.ts`: include dedupe report in preview metadata if needed, keep fixed captured values.
- Modify `apps/editor-web/src/api/agent-client.ts`: point to same-origin `/api/*` and `/ws` by default.
- Replace `apps/editor-web/src/App.tsx`: rebuild UI into n8n-like layout.
- Replace `apps/editor-web/src/styles.css`: new visual system for workflow builder.
- Modify `README.md`: document one-command start on `9001` and password fixed-value behavior.

Because this folder is not a git repository, skip commit steps until git is initialized. If git is initialized later, commit after each task using the commit commands listed.

---

### Task 1: Strengthen Recording Normalizer

**Files:**
- Modify: `apps/local-agent/src/recording/normalizer.ts`
- Modify: `apps/local-agent/src/recording/normalizer.test.ts`

- [ ] **Step 1: Write failing tests for anti-redundant recording**

Add these tests to `apps/local-agent/src/recording/normalizer.test.ts`:

```ts
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
    const event: RawBrowserEvent = {
      kind: "click",
      selector: "#login",
      fallback: { text: "Login", tag: "button" },
      url: entryUrl
    };

    const flow = normalizeRecordedEvents(entryUrl, [event, event]);

    expect(flow.map((step) => step.type)).toEqual(["openPage", "click"]);
  });

  it("does not create a step for unsupported idle-like key events", () => {
    const flow = normalizeRecordedEvents(entryUrl, [
      { kind: "keydown", key: "Shift", url: entryUrl },
      { kind: "keydown", key: "Control", url: entryUrl }
    ]);

    expect(flow.map((step) => step.type)).toEqual(["openPage"]);
  });
});
```

- [ ] **Step 2: Run normalizer tests and verify failure**

Run:

```bash
npm run test --workspace local-agent -- src/recording/normalizer.test.ts
```

Expected: at least the coalescing/valueMode assertions fail because the current normalizer only drops identical consecutive typing and does not set `valueMode`.

- [ ] **Step 3: Implement intent-level coalescing**

Update `apps/local-agent/src/recording/normalizer.ts` so `makeBaseStep` defaults `valueMode` to `fixed` when a value is present, and `normalizeRecordedEvents` replaces adjacent type/select noise for the same selector without reordering meaningful interleaved actions. Replay order must stay faithful to the recording, so repeated clicks/keys separated by meaningful actions are not duplicates:

```ts
function makeBaseStep(params: {
  type: FlowStep["type"];
  label: string;
  selector?: string;
  value?: string;
  variableRef?: string;
  metadata?: FlowStep["metadata"];
  fallback?: FlowStep["selectorFallback"];
}): FlowStep {
  return {
    id: randomUUID(),
    type: params.type,
    label: params.label,
    selector: params.selector,
    selectorFallback: params.fallback,
    value: params.value,
    variableRef: params.variableRef,
    valueMode: params.value !== undefined ? "fixed" : undefined,
    timeoutMs: 15000,
    continueOnError: false,
    metadata: params.metadata
  };
}

function flowFingerprint(step: FlowStep): string {
  return JSON.stringify({
    type: step.type,
    selector: step.selector ?? "",
    value: step.value ?? "",
    key: step.type === "pressKey" ? step.value ?? "" : "",
    url: step.metadata?.url ?? "",
    fallbackText: step.selectorFallback?.text ?? "",
    fallbackTag: step.selectorFallback?.tag ?? ""
  });
}

function canLatestStateWin(previous: FlowStep, current: FlowStep): boolean {
  return (
    (current.type === "type" || current.type === "select") &&
    previous.type === current.type &&
    (previous.selector ?? "") === (current.selector ?? "")
  );
}

export function normalizeRecordedEvents(entryUrl: string, events: RawBrowserEvent[]): FlowStep[] {
  const steps: FlowStep[] = [
    makeBaseStep({
      type: "openPage",
      label: "Open start page",
      value: entryUrl,
      metadata: { url: entryUrl }
    })
  ];
  for (const event of events) {
    const converted = convertEventToStep(event);
    if (!converted) {
      continue;
    }

    const previous = steps[steps.length - 1];

    if (previous && canLatestStateWin(previous, converted)) {
      steps[steps.length - 1] = converted;
      continue;
    }

    if (
      previous?.type === "waitForNavigation" &&
      converted.type === "waitForNavigation" &&
      previous.value === converted.value
    ) {
      continue;
    }

    const fingerprint = flowFingerprint(converted);
    if (previous && flowFingerprint(previous) === fingerprint) {
      continue;
    }

    steps.push(converted);
  }

  return steps;
}
```

- [ ] **Step 4: Run normalizer tests and verify pass**

Run:

```bash
npm run test --workspace local-agent -- src/recording/normalizer.test.ts
```

Expected: all normalizer tests pass.

- [ ] **Step 5: Commit if git exists**

Run only if `git status` works:

```bash
git add apps/local-agent/src/recording/normalizer.ts apps/local-agent/src/recording/normalizer.test.ts
git commit -m "fix: coalesce recorded browser events"
```

---

### Task 2: Convert Local Agent Into Port 9001 Monolith Server

**Files:**
- Modify: `apps/local-agent/src/server.ts`
- Modify: `package.json`
- Modify: `apps/local-agent/package.json`

- [ ] **Step 1: Add API route expectations as a smoke test**

Create or update `apps/local-agent/src/server.test.ts` with route-shape assertions using a pure helper exported from `server.ts`:

```ts
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
```

- [ ] **Step 2: Run server test and verify failure**

Run:

```bash
npm run test --workspace local-agent -- src/server.test.ts
```

Expected: FAIL because `getRuntimeConfig` is not exported.

- [ ] **Step 3: Refactor `server.ts` into exported app factory**

Update `apps/local-agent/src/server.ts` to export config and create the app before starting. Preserve existing services, but move public routes under `/api`:

```ts
export type RuntimeConfig = {
  port: number;
  apiPrefix: "/api";
  wsPath: "/ws";
  templateDir: string;
  uiDistDir: string;
};

export function getRuntimeConfig(env: NodeJS.ProcessEnv = process.env): RuntimeConfig {
  const port = Number(env.PORT ?? env.AGENT_PORT ?? "9001");
  return {
    port,
    apiPrefix: "/api",
    wsPath: "/ws",
    templateDir: env.TEMPLATE_DIR ?? path.resolve(process.cwd(), "../../templates"),
    uiDistDir: env.UI_DIST_DIR ?? path.resolve(process.cwd(), "../editor-web/dist")
  };
}
```

Then replace top-level constants with `const config = getRuntimeConfig();`, set `new WebSocketServer({ server, path: config.wsPath })`, use `config.templateDir`, and rename routes:

```ts
app.get("/api/health", (_req, res) => res.json({ ok: true }));
app.get("/api/templates", (_req, res) => { /* existing list logic */ });
app.get("/api/templates/:templateId", (req, res) => { /* existing get logic */ });
app.post("/api/recordings", async (req, res) => { /* existing start logic */ });
app.post("/api/recordings/:sessionId/stop", async (req, res) => { /* existing stop logic */ });
app.post("/api/templates/import", async (req, res) => { /* existing import logic */ });
app.get("/api/templates/:templateId/export", (req, res) => { /* export by params */ });
app.post("/api/runs", async (req, res) => { /* existing run logic */ });
```

Add static serving after API routes:

```ts
app.use(express.static(config.uiDistDir));
app.get(/.*/, (_req, res) => {
  res.sendFile(path.join(config.uiDistDir, "index.html"));
});
```

Guard startup:

```ts
export async function start(): Promise<void> {
  await store.initialize();
  server.listen(config.port, () => {
    console.log(`Template creator is running on http://localhost:${config.port}`);
    console.log(`Templates directory: ${config.templateDir}`);
  });
}

if (process.env.NODE_ENV !== "test") {
  start().catch((error) => {
    console.error("Failed to start template creator", error);
    process.exit(1);
  });
}
```

- [ ] **Step 4: Add one-command scripts**

Update root `package.json` scripts:

```json
{
  "scripts": {
    "setup:chromium": "npx playwright install chromium",
    "dev": "npm run build --workspace editor-web && npm run dev --workspace local-agent",
    "dev:editor": "npm run dev --workspace editor-web",
    "dev:agent": "npm run dev --workspace local-agent",
    "build": "npm run build --workspaces --if-present",
    "start": "npm run build --workspace editor-web && npm run build --workspace local-agent && npm run start --workspace local-agent",
    "test": "npm run test --workspaces --if-present",
    "typecheck": "npm run typecheck --workspaces --if-present"
  }
}
```

Update `apps/local-agent/package.json` dev script:

```json
{
  "scripts": {
    "dev": "PORT=9001 tsx watch src/server.ts",
    "build": "tsc -p tsconfig.json",
    "start": "PORT=9001 node dist/server.js",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  }
}
```

On Windows, if inline env syntax fails, use `cross-env` or remove the inline `PORT=9001` because `server.ts` defaults to `9001`.

- [ ] **Step 5: Run server config tests**

Run:

```bash
npm run test --workspace local-agent -- src/server.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit if git exists**

```bash
git add package.json apps/local-agent/package.json apps/local-agent/src/server.ts apps/local-agent/src/server.test.ts
git commit -m "feat: serve template creator as monolith"
```

---

### Task 3: Align Editor API Client To Monolith Routes

**Files:**
- Modify: `apps/editor-web/src/api/agent-client.ts`
- Test: `apps/editor-web/src/api/agent-client.test.ts`

- [ ] **Step 1: Write API URL tests**

Create `apps/editor-web/src/api/agent-client.test.ts`:

```ts
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
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
npm run test --workspace editor-web -- src/api/agent-client.test.ts
```

Expected: FAIL if current client hardcodes old agent port/routes.

- [ ] **Step 3: Update client helpers and endpoint paths**

In `apps/editor-web/src/api/agent-client.ts`, expose helpers:

```ts
export function apiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `/api${normalized}`;
}

export function wsUrl(locationLike: Pick<Location | URL, "protocol" | "host"> = window.location): string {
  const protocol = locationLike.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${locationLike.host}/ws`;
}
```

Update calls:

```ts
fetch(apiUrl("/templates"));
fetch(apiUrl(`/templates/${templateId}`));
fetch(apiUrl("/recordings"), { method: "POST", body: JSON.stringify({ url }) });
fetch(apiUrl(`/recordings/${sessionId}/stop`), { method: "POST" });
fetch(apiUrl("/runs"), { method: "POST", body: JSON.stringify(payload) });
fetch(apiUrl("/templates/import"), { method: "POST", body: JSON.stringify(payload) });
fetch(apiUrl(`/templates/${templateId}/export`));
```

- [ ] **Step 4: Run editor API tests**

Run:

```bash
npm run test --workspace editor-web -- src/api/agent-client.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit if git exists**

```bash
git add apps/editor-web/src/api/agent-client.ts apps/editor-web/src/api/agent-client.test.ts
git commit -m "feat: align editor with monolith api"
```

---

### Task 4: Rebuild Workflow Builder UI

**Files:**
- Replace: `apps/editor-web/src/App.tsx`
- Replace: `apps/editor-web/src/styles.css`
- Modify or add tests: `apps/editor-web/src/App.test.tsx`

- [ ] **Step 1: Write UI smoke tests**

Create `apps/editor-web/src/App.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run UI test and verify failure**

Run:

```bash
npm run test --workspace editor-web -- src/App.test.tsx
```

Expected: FAIL because the current UI labels/layout differ.

- [ ] **Step 3: Replace `App.tsx` with builder layout**

Rebuild `apps/editor-web/src/App.tsx` around these regions:

```tsx
return (
  <main className="app-shell">
    <aside className="template-sidebar" aria-label="Templates">
      <div className="brand-block">
        <span className="eyebrow">Local Automation</span>
        <h1>Template Creator</h1>
      </div>
      <button className="primary-action" onClick={() => setShowRecordingModal(true)}>
        Start Recording
      </button>
      <section className="template-list">
        <h2>Templates</h2>
        {templates.length === 0 ? (
          <p className="muted">No templates yet. Record a browser flow to create one.</p>
        ) : (
          templates.map((templatePackage) => (
            <button
              key={templatePackage.template.id}
              className={templatePackage.template.id === selectedTemplateId ? "template-item active" : "template-item"}
              onClick={() => setSelectedTemplateId(templatePackage.template.id)}
            >
              {templatePackage.template.name}
            </button>
          ))
        )}
      </section>
    </aside>

    <section className="canvas-panel">
      <header className="topbar">
        <div>
          <span className="eyebrow">{isLivePreviewMode ? "Recording" : "Template"}</span>
          <h2>Workflow Canvas</h2>
        </div>
        <div className="topbar-actions">
          <button onClick={handleReplayCurrent} disabled={!selectedTemplate || isBusy}>Replay</button>
          <button onClick={handleStopRecording} disabled={!activeSessionId}>Stop Recording</button>
        </div>
      </header>
      <div className="flow-canvas">
        <ReactFlow nodes={flowNodes} edges={flowEdges} fitView>
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
      <section className="event-console">
        <h3>Live Events</h3>
        <p>{statusMessage}</p>
      </section>
    </section>

    <aside className="inspector-panel">
      <span className="eyebrow">Agent</span>
      <h2>Agent Inspector</h2>
      <p className="muted">Clean committed steps are saved. Raw duplicate events stay in the log only.</p>
      <StepInspector step={displayedFlow[0] ?? null} />
    </aside>
  </main>
);
```

Keep existing behavior functions from the old `App.tsx` where possible: template loading, WebSocket preview, start/stop recording, import/export, replay.

- [ ] **Step 4: Replace styles with intentional n8n-like visual system**

Replace `apps/editor-web/src/styles.css` with CSS variables and panels:

```css
:root {
  font-family: "Space Grotesk", "Segoe UI", sans-serif;
  color: #17211b;
  background: #eef1e8;
  --ink: #17211b;
  --muted: #657267;
  --panel: rgba(255, 255, 248, 0.92);
  --line: #cfd8ce;
  --accent: #ff6a3d;
  --accent-strong: #d9471d;
  --mint: #dff4de;
}

body {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
  background:
    radial-gradient(circle at 15% 10%, rgba(255, 106, 61, 0.18), transparent 28%),
    radial-gradient(circle at 85% 15%, rgba(111, 166, 118, 0.22), transparent 32%),
    linear-gradient(135deg, #f7f4e8, #e8efe5);
}

.app-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 340px;
  gap: 16px;
  min-height: 100vh;
  padding: 16px;
  box-sizing: border-box;
}

.template-sidebar,
.canvas-panel,
.inspector-panel {
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--panel);
  box-shadow: 0 24px 80px rgba(23, 33, 27, 0.10);
}

.template-sidebar,
.inspector-panel {
  padding: 20px;
}

.canvas-panel {
  display: grid;
  grid-template-rows: auto minmax(420px, 1fr) auto;
  overflow: hidden;
}

.topbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 20px;
  border-bottom: 1px solid var(--line);
}

.flow-canvas {
  min-height: 520px;
  background-image: linear-gradient(rgba(23, 33, 27, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(23, 33, 27, 0.06) 1px, transparent 1px);
  background-size: 28px 28px;
}

.primary-action,
button {
  border: 0;
  border-radius: 999px;
  padding: 10px 14px;
  font-weight: 700;
  color: white;
  background: var(--accent);
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.template-item {
  display: block;
  width: 100%;
  margin: 8px 0;
  color: var(--ink);
  background: #fff;
  border: 1px solid var(--line);
  text-align: left;
}

.template-item.active {
  border-color: var(--accent);
  box-shadow: inset 4px 0 0 var(--accent);
}

.eyebrow {
  color: var(--accent-strong);
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.muted {
  color: var(--muted);
}

.event-console {
  padding: 16px 20px;
  border-top: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.55);
}

@media (max-width: 1100px) {
  .app-shell {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 5: Run UI test**

Run:

```bash
npm run test --workspace editor-web -- src/App.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit if git exists**

```bash
git add apps/editor-web/src/App.tsx apps/editor-web/src/styles.css apps/editor-web/src/App.test.tsx
git commit -m "feat: rebuild workflow builder ui"
```

---

### Task 5: End-To-End Build And Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README usage**

Replace the two-terminal run section with:

```md
## Menjalankan Aplikasi

Jalankan dari folder root `template/`.

```bash
npm run dev
```

Buka:

```text
http://localhost:9001
```

Mode ini menjalankan satu aplikasi monolit: UI, API, WebSocket, recorder Playwright, runner, dan template store.
```

Add a recording note:

```md
## Catatan Recording v1

- Raw browser event tidak langsung disimpan sebagai step.
- Input yang diketik berkali-kali diringkas menjadi satu step dengan nilai akhir.
- Username dan password disimpan sebagai fixed value agar replay sama persis.
- Idle setelah event selesai tidak membuat step baru.
- Navigation/click/input duplikat dibuang oleh normalizer.
```

- [ ] **Step 2: Run all relevant verification**

Run:

```bash
npm run test
npm run typecheck
npm run build
```

Expected: all commands pass.

- [ ] **Step 3: Start monolith manually**

Run:

```bash
npm run dev
```

Expected console output includes:

```text
Template creator is running on http://localhost:9001
```

Then open `http://localhost:9001` and verify:

- UI loads from the monolith server.
- `Start Recording` is visible.
- Browser recording opens Chromium.
- Clean preview shows one final type step per input field.

- [ ] **Step 4: Commit if git exists**

```bash
git add README.md package.json package-lock.json apps/local-agent apps/editor-web
git commit -m "docs: document monolith template creator"
```

---

## Self-Review

Spec coverage:

- One command and port `9001`: Task 2 and Task 5.
- n8n-like rebuilt UI: Task 4.
- Anti-redundant recording: Task 1.
- Exact username/password replay values: Task 1 and existing runner behavior in Task 5 verification.
- API/WebSocket monolith: Task 2 and Task 3.
- Documentation: Task 5.

Placeholder scan:

- No `TBD`, `TODO`, or unspecified edge handling remains.
- Each task includes file paths, commands, and expected results.

Type consistency:

- `FlowStep.valueMode` uses existing schema value `"fixed"`.
- API routes use `/api` prefix consistently.
- WebSocket remains `/ws`.
