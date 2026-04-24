# Monolith Template Creator Design

Date: 2026-04-24

## Goal

Build a new monolith template creator for local browser automation at `http://localhost:9001`.

The existing templating application is not the target experience. The new v1 should rebuild the UI and runtime architecture around a clean n8n-like workflow creator:

- Create a new automation template from the web UI.
- Start browser recording from the UI.
- Convert recording output into a clean flow with no redundant steps.
- Replay the template so it produces the same sequence and inputs as the original recording.
- Capture typed values exactly, including username and password, as fixed values for this phase.

## Non-Goals For v1

- No branch, loop, or conditional execution.
- No cloud sync.
- No credential vault or encryption layer yet.
- No multi-user collaboration.
- No attempt to preserve the current UI layout.

## Product Shape

The application is a single local service on port `9001`.

The user opens `http://localhost:9001` and sees a workflow builder similar in structure to n8n:

- Left sidebar: template list, create template, import/export.
- Center canvas: linear flow graph with connected nodes.
- Top action bar: start recording, stop recording, replay, save.
- Right inspector: selected step details, selector fallback, captured value, replay behavior, dedupe notes.
- Bottom/live panel: raw agent events, clean committed steps, replay logs.

The UI should make a clear distinction between raw captured browser events and committed template steps. Raw events can be noisy. The saved template must only contain clean steps.

## Architecture

Use a monolith runtime with modular internals:

- `server`: one local HTTP server listening on port `9001`.
- `ui`: rebuilt React editor served by the same server.
- `api`: REST endpoints for templates, recording control, replay, import/export.
- `ws`: WebSocket stream for recording preview, agent status, replay logs.
- `recorder`: Playwright Chromium recorder.
- `normalizer`: converts raw browser events into clean flow steps.
- `runner`: replays saved templates in strict order.
- `template-store`: reads/writes JSON templates on disk.
- `flow-schema`: shared schema and validation package remains the contract boundary.

The server can reuse existing local-agent code where useful, but the public developer experience should become one command and one port.

## Recording Pipeline

The recording pipeline must prevent redundant templates by design.

Raw browser events are not directly saved. They pass through this pipeline:

1. Capture raw event from the browser.
2. Compute a stable event fingerprint using event kind, selector, url, value, key, and relevant fallback data.
3. Drop exact duplicate fingerprints within the same recording window.
4. Coalesce input events for the same selector so typing `admin` becomes one final `type` step with value `admin`, not one step per character.
5. Coalesce password input the same way, but preserve the exact final value as a fixed captured value.
6. Drop no-op changes where the value did not materially change.
7. Drop repeated navigation events for the same final URL.
8. Commit one clean step per user intent.

Idle time must not create flow steps. If the user does nothing after an event completes, no extra action should appear.

## Step Semantics

Supported v1 clean step types:

- `openPage`
- `click`
- `type`
- `select`
- `check`
- `uncheck`
- `pressKey`
- `waitForNavigation`

Each step should include:

- Stable `id`
- Human label
- Step type
- Primary selector when applicable
- Selector fallback when available
- Fixed value when applicable
- Timeout
- Continue-on-error flag
- Metadata with source URL and recording notes

For this phase, username and password are stored as fixed values. This intentionally prioritizes exact replay over credential safety because the user explicitly wants replay to be the same as the recording.

## Replay Behavior

Replay runs the saved clean flow in strict order.

Rules:

- `openPage` starts from the stored entry URL.
- `type` clears/fills the field to the recorded final value.
- `click`, `select`, `check`, and `uncheck` execute against primary selector first, fallback second if supported.
- `pressKey` sends the recorded key.
- `waitForNavigation` waits for page state or matching URL when available.
- Failures report the failed step and reason.

The target outcome is deterministic replay, not best-effort guessing.

## UI Rebuild Direction

The old UI may be replaced. The new design should feel like an automation builder, not a generic template form.

Required UI states:

- Empty state: create first template or start recording.
- Recording state: browser is open, raw events are streaming, clean steps are previewed.
- Template editing state: selected flow can be inspected and adjusted.
- Replay state: progress and logs show exactly which step is running.
- Error state: failed agent connection, invalid selector, invalid template, replay failure.

Visual priority:

- The flow canvas is the main working area.
- The inspector explains why a step exists and whether it was deduped/coalesced.
- The raw event log is secondary and should not dominate the UI.

## API Surface

Initial monolith endpoints:

- `GET /` serves the React UI.
- `GET /api/templates` lists saved templates.
- `GET /api/templates/:id` loads one template.
- `POST /api/templates` creates or saves a template.
- `POST /api/templates/import` imports JSON.
- `GET /api/templates/:id/export` exports JSON.
- `POST /api/recordings` starts recording with entry URL.
- `POST /api/recordings/:sessionId/stop` stops recording and saves a clean template.
- `POST /api/runs` replays a template or draft flow.
- `GET /api/health` reports server, recorder, and browser availability.
- `GET /ws` streams events.

## Testing

Required tests:

- Normalizer drops duplicate navigation.
- Normalizer coalesces multiple input events for one selector into one final `type` step.
- Normalizer preserves username/password fixed values exactly.
- Normalizer does not create steps from idle/no-op behavior.
- Template schema validates saved clean flow.
- Runner executes a minimal login-like flow in the expected order.
- UI can render empty, recording preview, and template loaded states.

## Acceptance Criteria

The work is acceptable when:

- One command starts the app on `http://localhost:9001`.
- The rebuilt UI has a n8n-like builder layout.
- Starting recording opens Chromium and streams progress back to the UI.
- Typing into username/password produces one clean step per field with exact final value.
- Waiting/idling after an event does not add steps.
- Repeated same navigation/click/input noise does not create duplicate template steps.
- Stopping recording saves one clean template JSON.
- Replay uses the saved fixed values and repeats the recorded flow order.

## Risks

- Saving password as fixed plaintext is intentionally unsafe for shared machines. This is accepted for v1 because exact replay is the current priority.
- Browser selector stability can still fail on dynamic pages. Fallback selectors and clear error reporting are required.
- Full n8n parity is out of scope. The goal is n8n-like workflow creation, not a full automation platform.

