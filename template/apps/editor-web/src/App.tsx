import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Edge,
  type Node
} from "reactflow";
import {
  optimizeTemplatePackage,
  serializeTemplatePackage,
  validateTemplatePackage,
  type FlowStep,
  type StepValueMode,
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
import {
  convertStepValueToVariable,
  reorderSteps,
  toDownloadFilename,
  updateStep
} from "./lib/template-utils";

function downloadJson(filename: string, content: string): void {
  const blob = new Blob([content], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function normalizeRecordingUrl(rawUrl: string): string {
  const trimmed = rawUrl.trim();
  if (!trimmed) {
    return "";
  }
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

function resolveValueMode(step: FlowStep): StepValueMode {
  if (step.valueMode) {
    return step.valueMode;
  }
  return step.variableRef ? "variable" : "fixed";
}

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
  if (!isObject(value) || value.type !== "recording.flowPreview" || !isObject(value.payload)) {
    return false;
  }
  return (
    typeof value.payload.sessionId === "string" &&
    typeof value.payload.entryUrl === "string" &&
    isFlowStepArray(value.payload.flow)
  );
}

function isRecordingStoppedEvent(value: unknown): value is Extract<AgentWsEvent, { type: "recording.stopped" }> {
  if (!isObject(value) || value.type !== "recording.stopped" || !isObject(value.payload)) {
    return false;
  }
  return typeof value.payload.sessionId === "string" && typeof value.payload.templateId === "string";
}

function App() {
  const [templates, setTemplates] = useState<TemplatePackage[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [recordingUrl, setRecordingUrl] = useState("https://example.com");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [showRecordingModal, setShowRecordingModal] = useState(false);
  const [recordingPreview, setRecordingPreview] = useState<RecordingFlowPreview | null>(null);
  const [runValues, setRunValues] = useState<Record<string, string>>({});
  const [activityLog, setActivityLog] = useState<string[]>([]);
  const [statusMessage, setStatusMessage] = useState<string>("Ready");
  const [lastRunResult, setLastRunResult] = useState<RunResult | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);
  const activeSessionRef = useRef<string | null>(null);

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
  }, [isLivePreviewMode, recordingPreview, activeSessionId, selectedTemplate]);

  const flowNodes = useMemo<Node[]>(
    () =>
      displayedFlow.map((step, index) => ({
        id: step.id,
        type: "default",
        position: {
          x: index * 230,
          y: index % 2 === 0 ? 80 : 220
        },
        data: {
          label: `${index + 1}. ${step.label}`
        },
        style: {
          borderRadius: 12,
          border: "1px solid #20444f",
          width: 220,
          color: "#09212a",
          background:
            step.type === "openPage"
              ? "linear-gradient(120deg, #dff5de, #f7fff5)"
              : "linear-gradient(120deg, #e5f6ff, #f7fdff)"
        }
      })),
    [displayedFlow]
  );

  const flowEdges = useMemo<Edge[]>(
    () =>
      displayedFlow
        .slice(1)
        .map((step, index) => ({
          id: `${displayedFlow[index].id}-${step.id}`,
          source: displayedFlow[index].id,
          target: step.id,
          animated: true,
          style: {
            stroke: "#1e6979",
            strokeWidth: 2
          }
        })),
    [displayedFlow]
  );

  useEffect(() => {
    activeSessionRef.current = activeSessionId;
  }, [activeSessionId]);

  async function loadTemplatesFromAgent(): Promise<void> {
    try {
      const summaries = await listTemplates();
      const loaded = await Promise.all(summaries.map((summary) => getTemplate(summary.id)));
      setTemplates(loaded);
      if (loaded.length > 0) {
        setSelectedTemplateId((previous) => previous ?? loaded[0].template.id);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to fetch templates";
      setStatusMessage(message);
    }
  }

  useEffect(() => {
    loadTemplatesFromAgent().catch(() => {
      // already reflected in status state
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
          if (activeSessionRef.current === parsed.payload.sessionId) {
            setStatusMessage(`Recording live: ${parsed.payload.flow.length} step(s) captured`);
          }
        }

        if (isRecordingStoppedEvent(parsed) && activeSessionRef.current === parsed.payload.sessionId) {
          setRecordingPreview(null);
        }
      } catch {
        // Keep raw log only when payload is not JSON.
      }
    };

    socket.onerror = () => {
      setStatusMessage("WebSocket disconnected. Start local-agent first.");
    };

    return () => {
      socket.close();
    };
  }, []);

  useEffect(() => {
    if (!selectedTemplate) {
      return;
    }
    setRunValues(() =>
      Object.fromEntries(
        selectedTemplate.variables.map((variable) => [variable.name, variable.defaultValue ?? ""])
      )
    );
  }, [selectedTemplateId, selectedTemplate?.variables]);

  const upsertTemplate = (templatePackage: TemplatePackage): void => {
    setTemplates((current) => {
      const existingIndex = current.findIndex((item) => item.template.id === templatePackage.template.id);
      if (existingIndex === -1) {
        return [templatePackage, ...current];
      }
      const next = [...current];
      next[existingIndex] = templatePackage;
      return next;
    });
  };

  const applyStepPatch = (stepId: string, patch: Parameters<typeof updateStep>[2]) => {
    if (!selectedTemplate) {
      return;
    }
    const updated = updateStep(selectedTemplate, stepId, patch);
    upsertTemplate(updated);
  };

  const moveStep = (index: number, direction: "up" | "down") => {
    if (!selectedTemplate) {
      return;
    }
    const targetIndex = direction === "up" ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= selectedTemplate.flow.length) {
      return;
    }
    const updated = {
      ...selectedTemplate,
      flow: reorderSteps(selectedTemplate.flow, index, targetIndex)
    };
    upsertTemplate(updated);
  };

  const onStartRecording = async () => {
    const normalizedUrl = normalizeRecordingUrl(recordingUrl);
    if (!normalizedUrl) {
      setStatusMessage("Isi URL tujuan terlebih dulu.");
      return;
    }

    setIsBusy(true);
    try {
      const session = await startRecording(normalizedUrl);
      setRecordingUrl(normalizedUrl);
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
            timeoutMs: 15000,
            continueOnError: false,
            metadata: {
              url: session.url
            }
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
  };

  const onStopRecording = async () => {
    if (!activeSessionId) {
      return;
    }
    setIsBusy(true);
    try {
      const templatePackage = await stopRecording(activeSessionId);
      upsertTemplate(templatePackage);
      setSelectedTemplateId(templatePackage.template.id);
      setActiveSessionId(null);
      setRecordingPreview(null);
      setStatusMessage(`Recording converted to flow: ${templatePackage.template.name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to stop recording";
      setStatusMessage(message);
    } finally {
      setIsBusy(false);
    }
  };

  const onImportTemplate = async (event: ChangeEvent<HTMLInputElement>) => {
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
      const removed = result.optimization.removedSteps;
      setStatusMessage(
        removed > 0
          ? `Template imported + optimized: ${result.templatePackage.template.name} (${removed} step dihapus)`
          : `Template imported: ${result.templatePackage.template.name}`
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Invalid template JSON";
      setStatusMessage(message);
    } finally {
      event.target.value = "";
    }
  };

  const onExportTemplate = async () => {
    if (!selectedTemplate) {
      return;
    }
    try {
      const exported = await exportTemplate(selectedTemplate.template.id).catch(() => selectedTemplate);
      const content = serializeTemplatePackage(exported);
      downloadJson(toDownloadFilename(exported), content);
      setStatusMessage(`Template exported: ${exported.template.name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to export template";
      setStatusMessage(message);
    }
  };

  const onRunTemplate = async () => {
    if (!selectedTemplate) {
      return;
    }
    setIsBusy(true);
    try {
      const result = await runTemplate({
        template: selectedTemplate,
        variables: runValues,
        strictFidelity: true,
        recallFromSaved: false
      });
      setLastRunResult(result);
      const fidelityPercent = result.fidelity?.scorePercent ?? 0;
      setStatusMessage(result.status === "success"
        ? `Start selesai dengan fidelity ${fidelityPercent}%`
        : `Start gagal di step ${result.failedStepId ?? "-"} (fidelity ${fidelityPercent}%)`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Run failed";
      setStatusMessage(message);
    } finally {
      setIsBusy(false);
    }
  };

  const onRecallTemplate = async () => {
    if (!selectedTemplate) {
      return;
    }
    setIsBusy(true);
    try {
      const result = await runTemplate({
        templateId: selectedTemplate.template.id,
        variables: runValues,
        strictFidelity: true,
        recallFromSaved: true
      });
      setLastRunResult(result);
      const fidelityPercent = result.fidelity?.scorePercent ?? 0;
      setStatusMessage(result.status === "success"
        ? `Recall sukses 100% sesuai template tersimpan`
        : `Recall gagal. Fidelity ${fidelityPercent}% (target 100%)`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Recall failed";
      setStatusMessage(message);
    } finally {
      setIsBusy(false);
    }
  };

  const onSyncTemplate = async () => {
    if (!selectedTemplate) {
      return;
    }
    try {
      await importTemplate(serializeTemplatePackage(selectedTemplate), { optimize: false });
      setStatusMessage(`Template synced: ${selectedTemplate.template.name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Sync failed";
      setStatusMessage(message);
    }
  };

  const onOptimizeSelectedTemplate = async () => {
    if (!selectedTemplate) {
      return;
    }

    const optimized = optimizeTemplatePackage(selectedTemplate);
    upsertTemplate(optimized.templatePackage);

    try {
      await importTemplate(serializeTemplatePackage(optimized.templatePackage), { optimize: false });
      const removed = optimized.report.removedSteps;
      setStatusMessage(
        removed > 0
          ? `Flow optimized: ${removed} step berulang dihapus`
          : "Flow sudah optimal, tidak ada step berulang yang dihapus"
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to sync optimized template";
      setStatusMessage(message);
    }
  };

  return (
    <div className="layout">
      <header className="page-header">
        <div>
          <h1>Browser Flow Template Creator</h1>
          <p>Record browser actions, edit as a linear flow, then replay with variable input.</p>
        </div>
        <div className="header-actions">
          <button onClick={() => setShowRecordingModal(true)} disabled={isBusy || activeSessionId !== null}>
            Start Recording
          </button>
          <button onClick={onStopRecording} disabled={isBusy || activeSessionId === null}>
            Stop Recording
          </button>
          <button onClick={() => importInputRef.current?.click()} disabled={isBusy}>
            Import JSON
          </button>
          <button onClick={onExportTemplate} disabled={isBusy || !selectedTemplate}>
            Export JSON
          </button>
          <button onClick={onOptimizeSelectedTemplate} disabled={!selectedTemplate || isLivePreviewMode}>
            Optimize Flow
          </button>
          <button onClick={onSyncTemplate} disabled={!selectedTemplate}>
            Sync Template
          </button>
        </div>
      </header>

      <input
        ref={importInputRef}
        type="file"
        accept=".json,application/json"
        className="hidden-input"
        onChange={onImportTemplate}
      />

      <main className="content-grid">
        <section className="panel panel-templates">
          <h2>Templates</h2>
          <ul>
            {templates.map((item) => (
              <li key={item.template.id}>
                <button
                  className={item.template.id === selectedTemplateId ? "selected" : ""}
                  onClick={() => setSelectedTemplateId(item.template.id)}
                >
                  <span>{item.template.name}</span>
                  <small>{item.template.id}</small>
                </button>
              </li>
            ))}
          </ul>
          {templates.length === 0 && <p className="empty-text">No templates yet. Start a recording first.</p>}

          <div className="guide-card">
            <h3>How to Start</h3>
            <ol className="guide-list">
              <li>Jalankan `npm run dev:agent` di terminal 1.</li>
              <li>Jalankan `npm run dev:editor` di terminal 2.</li>
              <li>Klik `Start Recording`, isi URL awal, lalu mulai interaksi.</li>
              <li>Klik `Stop Recording` untuk ubah rekaman jadi flow.</li>
              <li>Edit step/variable lalu klik `Run Template`.</li>
            </ol>
          </div>
        </section>

        <section className="panel panel-flow">
          <h2>
            Linear Flow Canvas {isLivePreviewMode ? `(LIVE ${displayedFlow.length} step)` : ""}
          </h2>
          <div className="flow-canvas">
            <ReactFlow
              nodes={flowNodes}
              edges={flowEdges}
              fitView
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable={false}
            >
              <MiniMap />
              <Controls />
              <Background gap={16} />
            </ReactFlow>
          </div>
        </section>

        <section className="panel panel-steps">
          <h2>{isLivePreviewMode ? "Live Step Stream" : "Step Editor"}</h2>
          {displayedFlow.map((step, index) => (
            <article key={step.id} className="step-card">
              <header>
                <strong>
                  {index + 1}. {step.type}
                </strong>
                {!isLivePreviewMode && (
                  <div className="row-actions">
                    <button onClick={() => moveStep(index, "up")}>Up</button>
                    <button onClick={() => moveStep(index, "down")}>Down</button>
                  </div>
                )}
              </header>
              {isLivePreviewMode ? (
                <div className="live-step-readonly">
                  <p>
                    <strong>Label:</strong> {step.label}
                  </p>
                  {step.selector ? (
                    <p>
                      <strong>Selector:</strong> {step.selector}
                    </p>
                  ) : null}
                  {step.value ? (
                    <p>
                      <strong>Value:</strong> {step.value}
                    </p>
                  ) : null}
                </div>
              ) : (
                <>
                  <label>
                    Label
                    <input
                      value={step.label}
                      onChange={(event) => applyStepPatch(step.id, { label: event.target.value })}
                    />
                  </label>
                  {"selector" in step && (
                    <label>
                      Selector
                      <input
                        value={step.selector ?? ""}
                        onChange={(event) => applyStepPatch(step.id, { selector: event.target.value })}
                      />
                    </label>
                  )}
                  {"value" in step && (
                    <>
                      <label>
                        Data Mode
                        <select
                          value={resolveValueMode(step)}
                          onChange={(event) => {
                            const nextMode = event.target.value as StepValueMode;
                            applyStepPatch(step.id, { valueMode: nextMode });
                          }}
                        >
                          <option value="fixed">Fixed Value</option>
                          <option value="variable">Variable</option>
                          <option value="generatedTimestamp">Generated: Timestamp</option>
                          <option value="generatedRandomNumber">Generated: Random Number</option>
                          <option value="generatedUuid">Generated: UUID</option>
                        </select>
                      </label>
                      <label>
                        Value
                        <input
                          value={step.value ?? ""}
                          disabled={resolveValueMode(step) !== "fixed" && resolveValueMode(step) !== "variable"}
                          onChange={(event) => applyStepPatch(step.id, { value: event.target.value })}
                        />
                      </label>
                    </>
                  )}
                  {resolveValueMode(step) === "variable" && !step.variableRef && (
                    <p className="empty-text">
                      Mode variable aktif. Klik tombol di bawah untuk membuat variable dari value saat ini.
                    </p>
                  )}
                  {step.value && (
                    <button
                      className="secondary"
                      onClick={() => {
                        if (!selectedTemplate) {
                          return;
                        }
                        const updated = convertStepValueToVariable(selectedTemplate, step.id);
                        upsertTemplate(updated);
                      }}
                    >
                      Convert Value to Variable
                    </button>
                  )}
                </>
              )}
            </article>
          ))}
          {displayedFlow.length === 0 && (
            <p className="empty-text">
              {isLivePreviewMode
                ? "Menunggu event interaksi pertama dari browser..."
                : "Select a template to edit its steps."}
            </p>
          )}
        </section>

        <section className="panel panel-variables">
          <h2>Variables</h2>
          {isLivePreviewMode && (
            <p className="empty-text">Live recording aktif. Stop recording dulu untuk edit variable dan run.</p>
          )}
          {selectedTemplate?.variables.length ? (
            <div className="variable-list">
              {selectedTemplate.variables.map((variable) => (
                <label key={variable.name}>
                  {variable.label} ({variable.name})
                  <input
                    value={runValues[variable.name] ?? ""}
                    onChange={(event) =>
                      setRunValues((current) => ({
                        ...current,
                        [variable.name]: event.target.value
                      }))
                    }
                  />
                </label>
              ))}
            </div>
          ) : (
            <p className="empty-text">No variables yet. Convert step values into placeholders.</p>
          )}

          <div className="row-actions">
            <button onClick={onRunTemplate} disabled={isBusy || !selectedTemplate || isLivePreviewMode}>
              Start (Strict)
            </button>
            <button className="secondary" onClick={onRecallTemplate} disabled={isBusy || !selectedTemplate || isLivePreviewMode}>
              Recall Saved (100%)
            </button>
          </div>

          {lastRunResult && (
            <div className="run-result">
              <strong>Latest Run: {lastRunResult.status.toUpperCase()}</strong>
              <p>
                Steps executed: {lastRunResult.steps.length}
                {lastRunResult.failedStepId ? `, failed step: ${lastRunResult.failedStepId}` : ""}
              </p>
              {lastRunResult.fidelity ? (
                <p>
                  Fidelity: {lastRunResult.fidelity.scorePercent}% ({lastRunResult.fidelity.mode}){" "}
                  {lastRunResult.fidelity.exactMatch ? "exact match" : "not exact"}
                </p>
              ) : null}
            </div>
          )}
        </section>

        <section className="panel panel-events">
          <h2>Live Events</h2>
          <p className="status">{statusMessage}</p>
          <div className="event-list">
            {activityLog.length ? (
              activityLog.map((entry, index) => <code key={`${entry}-${index}`}>{entry}</code>)
            ) : (
              <p className="empty-text">No events yet. Start recording or run a template.</p>
            )}
          </div>
        </section>
      </main>

      {showRecordingModal && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3>Start Recording</h3>
            <p>Where should the browser start before recording all interactions?</p>
            <p className="hint-text">Tip: boleh isi `example.com` tanpa `https://`, nanti dinormalisasi otomatis.</p>
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
    </div>
  );
}

export default App;
