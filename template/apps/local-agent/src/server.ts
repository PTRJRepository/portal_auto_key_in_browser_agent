import path from "node:path";

import cors from "cors";
import express from "express";
import { createServer } from "http";
import { WebSocketServer } from "ws";
import {
  optimizeTemplatePackage,
  summarizeTemplate,
  validateTemplatePackage,
  type FlowOptimizationReport,
  type RecordingSession,
  type RunResult,
  type TemplatePackage
} from "@template/flow-schema";

import { RecorderService } from "./recording/recorder.js";
import { TemplateRunner } from "./runner/runner.js";
import { TemplateStore } from "./template-store.js";
import { WebsocketHub } from "./websocket-hub.js";
import { normalizeStartUrl } from "./lib/url-utils.js";

type StartRecordingRequest = {
  url?: string;
};

type RunTemplateRequest = {
  templateId?: string;
  template?: TemplatePackage;
  variables?: Record<string, string>;
  strictFidelity?: boolean;
  recallFromSaved?: boolean;
};

type ImportTemplateRequest = {
  packageJson?: string;
  optimize?: boolean;
};

const agentPort = Number(process.env.AGENT_PORT ?? "4100");
const templateDir = process.env.TEMPLATE_DIR ?? path.resolve(process.cwd(), "../../templates");

const app = express();
const server = createServer(app);
const wsServer = new WebSocketServer({ server, path: "/ws" });
const hub = new WebsocketHub(wsServer);
const store = new TemplateStore(templateDir);
const recorder = new RecorderService((event) => hub.broadcast(event));
const runner = new TemplateRunner((event) => hub.broadcast(event));

const recordingSessions = new Map<string, RecordingSession>();

app.use(cors());
app.use(express.json({ limit: "5mb" }));

app.get("/health", (_req, res) => {
  res.json({ ok: true });
});

app.get("/templates", (_req, res) => {
  const templates = store.list();
  res.json({ templates });
});

app.get("/templates/:templateId", (req, res) => {
  const templatePackage = store.get(req.params.templateId);
  if (!templatePackage) {
    res.status(404).json({ error: "Template not found" });
    return;
  }
  res.json(templatePackage);
});

app.post("/recordings/start", async (req, res) => {
  const body = req.body as StartRecordingRequest;
  if (!body.url?.trim()) {
    res.status(400).json({ error: "url is required" });
    return;
  }

  try {
    const normalizedUrl = normalizeStartUrl(body.url);
    const session = await recorder.startRecording(normalizedUrl);
    recordingSessions.set(session.sessionId, session);
    res.json(session);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to start recording";
    res.status(500).json({ error: message });
  }
});

app.post("/recordings/:sessionId/stop", async (req, res) => {
  const { sessionId } = req.params;
  if (!recordingSessions.has(sessionId)) {
    res.status(404).json({ error: "Recording session not found" });
    return;
  }

  try {
    const templatePackage = await recorder.stopRecording(sessionId);
    await store.save(templatePackage);
    recordingSessions.delete(sessionId);
    res.json(templatePackage);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to stop recording";
    res.status(500).json({ error: message });
  }
});

app.post("/templates/import", async (req, res) => {
  const body = req.body as ImportTemplateRequest;
  if (!body.packageJson) {
    res.status(400).json({ error: "packageJson is required" });
    return;
  }

  try {
    const parsed = validateTemplatePackage(JSON.parse(body.packageJson));
    const shouldOptimize = body.optimize !== false;
    const optimizationResult = shouldOptimize
      ? optimizeTemplatePackage(parsed)
      : {
          templatePackage: parsed,
          report: {
            originalSteps: parsed.flow.length,
            optimizedSteps: parsed.flow.length,
            removedSteps: 0,
            reasons: {
              duplicateConsecutiveStep: 0,
              latestInputStateWins: 0
            }
          } satisfies FlowOptimizationReport
        };

    await store.save(optimizationResult.templatePackage);
    res.json({
      template: summarizeTemplate(optimizationResult.templatePackage),
      templatePackage: optimizationResult.templatePackage,
      optimization: optimizationResult.report
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to import template";
    res.status(400).json({ error: message });
  }
});

app.post("/templates/export", async (req, res) => {
  const templateId = (req.body?.templateId as string | undefined)?.trim();
  if (!templateId) {
    res.status(400).json({ error: "templateId is required" });
    return;
  }

  const templatePackage = store.get(templateId);
  if (!templatePackage) {
    res.status(404).json({ error: "Template not found" });
    return;
  }

  res.json(templatePackage);
});

app.post("/templates/run", async (req, res) => {
  const body = req.body as RunTemplateRequest;
  const variables = body.variables ?? {};
  const strictFidelity = body.strictFidelity !== false;

  try {
    let templatePackage: TemplatePackage | undefined;

    if (body.recallFromSaved) {
      if (!body.templateId) {
        res.status(400).json({ error: "templateId is required for recallFromSaved" });
        return;
      }
      templatePackage = store.get(body.templateId);
    } else if (body.template) {
      templatePackage = validateTemplatePackage(body.template);
      await store.save(templatePackage);
    } else if (body.templateId) {
      templatePackage = store.get(body.templateId);
    }

    if (!templatePackage) {
      res.status(404).json({ error: "Template not found" });
      return;
    }

    const result: RunResult = await runner.runTemplate(templatePackage, variables, {
      strictFidelity
    });
    res.json(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to run template";
    res.status(400).json({ error: message });
  }
});

async function start(): Promise<void> {
  await store.initialize();
  server.listen(agentPort, () => {
    // eslint-disable-next-line no-console
    console.log(`Local agent is running on http://localhost:${agentPort}`);
    // eslint-disable-next-line no-console
    console.log(`Templates directory: ${templateDir}`);
  });
}

start().catch((error) => {
  // eslint-disable-next-line no-console
  console.error("Failed to start local agent", error);
  process.exit(1);
});
