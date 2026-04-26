import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import ReactFlow, { Background, Controls, MiniMap, type Edge, type Node } from "reactflow";
import {
  serializeTemplatePackage,
  validateTemplatePackage,
  type FlowStep,
  type RunResult,
  type TemplatePackage
} from "@template/flow-schema";

import {
  exportTemplate,
  getTemplate,
  importTemplate,
  listTemplates,
  runTemplate,
  startRecording,
  stopRecording,
  wsUrl
} from "./api/agent-client";
import { toDownloadFilename } from "./lib/template-utils";

type RecordingFlowPreview = {
  sessionId: string;
  entryUrl: string;
  flow: FlowStep[];
};

type AgentWsEvent =
  | {
      type: "recording.flowPreview";
      payload: RecordingFlowPreview;
    }
  | {
      type: "recording.stopped";
      payload: {
        sessionId: string;
        templateId: string;
      };
    }
  | {
      type: "recording.browserClosed";
      payload: {
        sessionId: string;
      };
    }
  | {
      type: string;
      payload?: unknown;
    };

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isFlowStepArray(value: unknown): value is FlowStep[] {
  return Array.isArray(value) && value.every((item) => isObject(item) && typeof item.id === "string");
}

function isRecordingFlowPreviewEvent(value: unknown): value is Extract<AgentWsEvent, { type: "recording.flowPreview" }> {
  return (
    isObject(value) &&
    value.type === "recording.flowPreview" &&
    isObject(value.payload) &&
    typeof value.payload.sessionId === "string" &&
    typeof value.payload.entryUrl === "string" &&
    isFlowStepArray(value.payload.flow)
  );
}

function isRecordingStoppedEvent(value: unknown): value is Extract<AgentWsEvent, { type: "recording.stopped" }> {
  return (
    isObject(value) &&
    value.type === "recording.stopped" &&
    isObject(value.payload) &&
    typeof value.payload.sessionId === "string" &&
    typeof value.payload.templateId === "string"
  );
}

function isRecordingBrowserClosedEvent(value: unknown): value is Extract<AgentWsEvent, { type: "recording.browserClosed" }> {
  return (
    isObject(value) &&
    value.type === "recording.browserClosed" &&
    isObject(value.payload) &&
    typeof value.payload.sessionId === "string"
  );
}

function normalizeRecordingUrl(rawUrl: string): string {
  const trimmed = rawUrl.trim();
  if (!trimmed) {
    return "";
  }
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

function downloadJson(filename: string, content: string): void {
  const blob = new Blob([content], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function sanitizeStepForDraft(step: FlowStep): FlowStep {
  const selectorFallback = step.selectorFallback
    ? Object.fromEntries(
        Object.entries(step.selectorFallback).filter(([, value]) => typeof value === "string" && value.trim().length > 0)
      )
    : undefined;

  return {
    ...step,
    selectorFallback: selectorFallback && Object.keys(selectorFallback).length > 0 ? selectorFallback : undefined
  };
}

function StepInspector({ step }: { step: FlowStep | null }) {
  if (!step) {
    return (
      <div className="inspector-empty">
        <strong>No step selected</strong>
        <p>Record a new flow or select a template to inspect its committed steps.</p>
      </div>
    );
  }

  return (
    <article className="inspector-card">
      <span className="node-type">{step.type}</span>
      <h3>{step.label}</h3>
      <dl>
        <div>
          <dt>Selector</dt>
          <dd>{step.selector ?? step.selectorFallback?.css ?? "Not required"}</dd>
        </div>
        <div>
          <dt>Captured value</dt>
          <dd>{step.value ?? "None"}</dd>
        </div>
        <div>
          <dt>Source URL</dt>
          <dd>{step.metadata?.url ?? "Unknown"}</dd>
        </div>
        <div>
          <dt>Replay mode</dt>
          <dd>{step.value ? "Fixed exact value" : "Action only"}</dd>
        </div>
      </dl>
    </article>
  );
}

function App() {
  const [templates, setTemplates] = useState<TemplatePackage[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [recordingUrl, setRecordingUrl] = useState("https://example.com");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [showRecordingModal, setShowRecordingModal] = useState(false);
  const [recordingPreview, setRecordingPreview] = useState<RecordingFlowPreview | null>(null);
  const [runValues] = useState<Record<string, string>>({});
  const [activityLog, setActivityLog] = useState<string[]>([]);
  const [statusMessage, setStatusMessage] = useState("Ready");
  const [lastRunResult, setLastRunResult] = useState<RunResult | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);
  const activeSessionRef = useRef<string | null>(null);
  const recordingPreviewRef = useRef<RecordingFlowPreview | null>(null);
  const stopInFlightRef = useRef(false);

  const selectedTemplate = useMemo(
    () => templates.find((item) => item.template.id === selectedTemplateId) ?? null,
    [templates, selectedTemplateId]
  );

  const isLivePreviewMode = activeSessionId !== null;
  const displayedFlow = useMemo<FlowStep[]>(() => {
    if (isLivePreviewMode && recordingPreview?.sessionId === activeSessionId) {
      return recordingPreview.flow;
    }
    return selectedTemplate?.flow ?? [];
  }, [activeSessionId, isLivePreviewMode, recordingPreview, selectedTemplate]);

  const selectedStep = useMemo(
    () => displayedFlow.find((step) => step.id === selectedStepId) ?? displayedFlow[0] ?? null,
    [displayedFlow, selectedStepId]
  );

  const flowNodes = useMemo<Node[]>(
    () =>
      displayedFlow.map((step, index) => ({
        id: step.id,
        position: {
          x: index * 260,
          y: index % 2 === 0 ? 90 : 230
        },
        data: {
          label: `${index + 1}. ${step.label}`
        },
        style: {
          borderRadius: 18,
          border: step.id === selectedStep?.id ? "2px solid #ff6a3d" : "1px solid #b9c6bb",
          width: 230,
          color: "#17211b",
          background: step.type === "openPage" ? "#e0f3d9" : "#fffdf6",
          boxShadow: "0 14px 34px rgba(23, 33, 27, 0.12)"
        }
      })),
    [displayedFlow, selectedStep?.id]
  );

  const flowEdges = useMemo<Edge[]>(
    () =>
      displayedFlow.slice(1).map((step, index) => ({
        id: `${displayedFlow[index].id}-${step.id}`,
        source: displayedFlow[index].id,
        target: step.id,
        animated: isLivePreviewMode,
        style: {
          stroke: "#ff6a3d",
          strokeWidth: 2
        }
      })),
    [displayedFlow, isLivePreviewMode]
  );

  useEffect(() => {
    activeSessionRef.current = activeSessionId;
  }, [activeSessionId]);

  useEffect(() => {
    recordingPreviewRef.current = recordingPreview;
  }, [recordingPreview]);

  useEffect(() => {
    listTemplates()
      .then((summaries) => Promise.all(summaries.map((summary) => getTemplate(summary.id))))
      .then((loaded) => {
        setTemplates(loaded);
        setSelectedTemplateId((previous) => previous ?? loaded[0]?.template.id ?? null);
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : "Failed to fetch templates";
        setStatusMessage(message);
      });
  }, []);

  useEffect(() => {
    const socket = new WebSocket(wsUrl());
    socket.onmessage = (event) => {
      const raw = event.data.toString();
      setActivityLog((current) => [raw, ...current].slice(0, 40));

      try {
        const parsed = JSON.parse(raw) as unknown;
        if (isRecordingFlowPreviewEvent(parsed)) {
          setRecordingPreview(parsed.payload);
          setStatusMessage(`Recording live: ${parsed.payload.flow.length} clean step(s)`);
        }

        if (isRecordingStoppedEvent(parsed) && activeSessionRef.current === parsed.payload.sessionId) {
          setRecordingPreview(null);
        }

        if (
          isRecordingBrowserClosedEvent(parsed) &&
          activeSessionRef.current === parsed.payload.sessionId &&
          !stopInFlightRef.current
        ) {
          setStatusMessage("Browser recording closed. Finalizing captured flow...");
          void finalizeRecording(parsed.payload.sessionId);
        }
      } catch {
        // Raw log remains available for malformed or non-JSON agent output.
      }
    };
    socket.onerror = () => setStatusMessage("WebSocket disconnected. Start the monolith server first.");
    return () => socket.close();
  }, []);

  function upsertTemplate(templatePackage: TemplatePackage): void {
    setTemplates((current) => {
      const existingIndex = current.findIndex((item) => item.template.id === templatePackage.template.id);
      if (existingIndex === -1) {
        return [templatePackage, ...current];
      }
      const next = [...current];
      next[existingIndex] = templatePackage;
      return next;
    });
  }

  function buildDraftTemplateFromPreview(preview: RecordingFlowPreview): TemplatePackage {
    return validateTemplatePackage({
      schemaVersion: "1.0.0",
      template: {
        id: `recovered-${preview.sessionId}`,
        name: `Recovered Recording ${new Date().toISOString()}`,
        description: "Recovered locally from live recording preview.",
        version: "1.0.0",
        createdAt: new Date().toISOString()
      },
      entry: {
        url: preview.entryUrl
      },
      variables: [],
      flow: preview.flow.map(sanitizeStepForDraft),
      runtime: {
        defaultTimeoutMs: 15000,
        sessionMode: "fresh"
      }
    });
  }

  async function onStartRecording(): Promise<void> {
    const normalizedUrl = normalizeRecordingUrl(recordingUrl);
    if (!normalizedUrl) {
      setStatusMessage("Isi URL tujuan terlebih dulu.");
      return;
    }

    setIsBusy(true);
    try {
      const session = await startRecording(normalizedUrl);
      setActiveSessionId(session.sessionId);
      setRecordingPreview({
        sessionId: session.sessionId,
        entryUrl: session.url,
        flow: [
          {
            id: `live-open-${session.sessionId}`,
            type: "openPage",
            label: "Open start page",
            value: session.url,
            valueMode: "fixed",
            timeoutMs: 15000,
            continueOnError: false,
            metadata: { url: session.url }
          }
        ]
      });
      setShowRecordingModal(false);
      setStatusMessage(`Recording started: ${session.sessionId}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to start recording";
      setStatusMessage(message);
    } finally {
      setIsBusy(false);
    }
  }

  async function finalizeRecording(sessionId: string): Promise<void> {
    if (stopInFlightRef.current) {
      return;
    }
    stopInFlightRef.current = true;
    setIsBusy(true);
    try {
      const templatePackage = await stopRecording(sessionId);
      upsertTemplate(templatePackage);
      setSelectedTemplateId(templatePackage.template.id);
      setSelectedStepId(templatePackage.flow[0]?.id ?? null);
      setActiveSessionId(null);
      setRecordingPreview(null);
      setStatusMessage(`Recording saved as clean template: ${templatePackage.template.name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to stop recording";
      const preview = recordingPreviewRef.current;
      if (preview?.sessionId === sessionId && preview.flow.length > 0) {
        const recoveredTemplate = buildDraftTemplateFromPreview(preview);
        upsertTemplate(recoveredTemplate);
        setSelectedTemplateId(recoveredTemplate.template.id);
        setSelectedStepId(recoveredTemplate.flow[0]?.id ?? null);
        setActiveSessionId(null);
        setRecordingPreview(null);
        setStatusMessage(`Stop failed on server (${message}). Draft recovered locally for export/replay.`);
      } else {
        setStatusMessage(message);
      }
    } finally {
      setIsBusy(false);
      stopInFlightRef.current = false;
    }
  }

  async function onStopRecording(): Promise<void> {
    if (!activeSessionId) {
      return;
    }
    await finalizeRecording(activeSessionId);
  }

  async function onImportTemplate(event: ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    try {
      const text = await file.text();
      validateTemplatePackage(JSON.parse(text));
      const result = await importTemplate(text, { optimize: true });
      upsertTemplate(result.templatePackage);
      setSelectedTemplateId(result.templatePackage.template.id);
      setSelectedStepId(result.templatePackage.flow[0]?.id ?? null);
      setStatusMessage(`Template imported: ${result.templatePackage.template.name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Invalid template JSON";
      setStatusMessage(message);
    } finally {
      event.target.value = "";
    }
  }

  async function onExportTemplate(): Promise<void> {
    if (!selectedTemplate) {
      return;
    }
    const exported = await exportTemplate(selectedTemplate.template.id).catch(() => selectedTemplate);
    downloadJson(toDownloadFilename(exported), serializeTemplatePackage(exported));
    setStatusMessage(`Template exported: ${exported.template.name}`);
  }

  async function onReplay(recallFromSaved: boolean): Promise<void> {
    if (!selectedTemplate) {
      return;
    }

    setIsBusy(true);
    try {
      const result = await runTemplate({
        templateId: recallFromSaved ? selectedTemplate.template.id : undefined,
        template: recallFromSaved ? undefined : selectedTemplate,
        variables: runValues,
        strictFidelity: true,
        recallFromSaved
      });
      setLastRunResult(result);
      const fidelityPercent = result.fidelity?.scorePercent ?? 0;
      setStatusMessage(`${recallFromSaved ? "Recall" : "Replay"} ${result.status}: ${fidelityPercent}% fidelity`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Replay failed";
      setStatusMessage(message);
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <aside className="template-sidebar" aria-label="Templates">
        <div className="brand-block">
          <span className="eyebrow">Local Automation</span>
          <h1>Template Creator</h1>
          <p>Record once, clean the noise, replay the exact same flow.</p>
        </div>

        <button className="primary-action" onClick={() => setShowRecordingModal(true)} disabled={isBusy || isLivePreviewMode}>
          Start Recording
        </button>

        <div className="sidebar-actions">
          <button onClick={() => importInputRef.current?.click()} disabled={isBusy}>
            Import
          </button>
          <button onClick={onExportTemplate} disabled={isBusy || !selectedTemplate}>
            Export
          </button>
        </div>

        <input
          ref={importInputRef}
          type="file"
          accept=".json,application/json"
          className="hidden-input"
          onChange={onImportTemplate}
        />

        <section className="template-list">
          <h2>Templates</h2>
          {templates.length === 0 ? (
            <p className="muted">No templates yet. Start a browser recording to create one.</p>
          ) : (
            templates.map((templatePackage) => (
              <button
                key={templatePackage.template.id}
                className={templatePackage.template.id === selectedTemplateId ? "template-item active" : "template-item"}
                onClick={() => {
                  setSelectedTemplateId(templatePackage.template.id);
                  setSelectedStepId(templatePackage.flow[0]?.id ?? null);
                }}
              >
                <strong>{templatePackage.template.name}</strong>
                <span>{templatePackage.flow.length} step(s)</span>
              </button>
            ))
          )}
        </section>
      </aside>

      <section className="canvas-panel">
        <header className="topbar">
          <div>
            <span className="eyebrow">{isLivePreviewMode ? "Recording Preview" : "Template Flow"}</span>
            <h2>Workflow Canvas</h2>
          </div>
          <div className="topbar-actions">
            <button onClick={() => onReplay(false)} disabled={!selectedTemplate || isBusy || isLivePreviewMode}>
              Replay Draft
            </button>
            <button onClick={() => onReplay(true)} disabled={!selectedTemplate || isBusy || isLivePreviewMode}>
              Recall Saved
            </button>
            <button onClick={onStopRecording} disabled={!activeSessionId || isBusy}>
              Stop Recording
            </button>
          </div>
        </header>

        <div className="flow-canvas">
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            fitView
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            onNodeClick={(_event, node) => setSelectedStepId(node.id)}
          >
            <Background gap={28} color="#c9d0c9" />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </div>

        <section className="event-console">
          <div>
            <h3>Live Events</h3>
            <p>{statusMessage}</p>
          </div>
          <div className="event-stream">
            {activityLog.slice(0, 4).map((entry, index) => (
              <code key={`${entry}-${index}`}>{entry}</code>
            ))}
            {activityLog.length === 0 ? <span className="muted">Waiting for agent events.</span> : null}
          </div>
        </section>
      </section>

      <aside className="inspector-panel">
        <span className="eyebrow">Agent</span>
        <h2>Agent Inspector</h2>
        <p className="muted">Only committed clean steps are saved. Raw duplicate events stay in the log.</p>
        <StepInspector step={selectedStep} />
        {lastRunResult ? (
          <section className="run-summary">
            <h3>Latest Run</h3>
            <strong>{lastRunResult.status.toUpperCase()}</strong>
            <p>{lastRunResult.steps.length} step(s) executed</p>
          </section>
        ) : null}
      </aside>

      {showRecordingModal && (
        <div className="modal-backdrop">
          <div className="modal">
            <span className="eyebrow">New Recording</span>
            <h3>Start from URL</h3>
            <p>Chromium will open locally. Username and password values are captured exactly for replay.</p>
            <input value={recordingUrl} onChange={(event) => setRecordingUrl(event.target.value)} />
            <div className="row-actions">
              <button className="secondary" onClick={() => setShowRecordingModal(false)}>
                Cancel
              </button>
              <button onClick={onStartRecording} disabled={!recordingUrl || isBusy}>
                Start
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

export default App;
