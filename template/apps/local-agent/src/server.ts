import path from "node:path";

import cors from "cors";
import express from "express";
import { createServer, type Server } from "http";
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

import { normalizeStartUrl } from "./lib/url-utils.js";
import { RecorderService } from "./recording/recorder.js";
import { SpsiFlowRunner } from "./runner/spsi-flow-runner.js";
import { TemplateRunner } from "./runner/runner.js";
import { TemplateStore } from "./template-store.js";
import { WebsocketHub } from "./websocket-hub.js";

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

export type MonolithServer = {
  app: express.Express;
  server: Server;
  store: TemplateStore;
};

export function createMonolithServer(config: RuntimeConfig = getRuntimeConfig()): MonolithServer {
  const app = express();
  const server = createServer(app);
  const wsServer = new WebSocketServer({ server, path: config.wsPath });
  const hub = new WebsocketHub(wsServer);
  const store = new TemplateStore(config.templateDir);
  const recorder = new RecorderService((event) => hub.broadcast(event));
  const runner = new TemplateRunner((event) => hub.broadcast(event));
  const recordingSessions = new Map<string, RecordingSession>();

  app.use(cors());
  app.use(express.json({ limit: "5mb" }));

  app.get(`${config.apiPrefix}/health`, (_req, res) => {
    res.json({ ok: true });
  });

  app.get(`${config.apiPrefix}/templates`, (_req, res) => {
    const templates = store.list();
    res.json({ templates });
  });

  app.get(`${config.apiPrefix}/templates/:templateId`, (req, res) => {
    const templatePackage = store.get(req.params.templateId);
    if (!templatePackage) {
      res.status(404).json({ error: "Template not found" });
      return;
    }
    res.json(templatePackage);
  });

  app.post(`${config.apiPrefix}/recordings`, async (req, res) => {
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

  app.post(`${config.apiPrefix}/recordings/:sessionId/stop`, async (req, res) => {
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

  app.post(`${config.apiPrefix}/templates/import`, async (req, res) => {
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

  app.get(`${config.apiPrefix}/templates/:templateId/export`, (req, res) => {
    const templatePackage = store.get(req.params.templateId);
    if (!templatePackage) {
      res.status(404).json({ error: "Template not found" });
      return;
    }

    res.json(templatePackage);
  });

  app.post(`${config.apiPrefix}/runs`, async (req, res) => {
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

  // Direct SPSI flow runner endpoint - bypasses template system
  app.post(`${config.apiPrefix}/spsi/run`, async (_req, res) => {
    try {
      const spsiRunner = new SpsiFlowRunner();
      const result = await spsiRunner.run();
      res.json(result);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to run SPSI flow";
      res.status(500).json({ error: message });
    }
  });

  app.use(express.static(config.uiDistDir));
  app.get(/.*/, (_req, res) => {
    res.sendFile(path.join(config.uiDistDir, "index.html"));
  });

  return { app, server, store };
}

export async function start(config: RuntimeConfig = getRuntimeConfig()): Promise<void> {
  const monolith = createMonolithServer(config);
  await monolith.store.initialize();
  monolith.server.listen(config.port, () => {
    // eslint-disable-next-line no-console
    console.log(`Template creator is running on http://localhost:${config.port}`);
    // eslint-disable-next-line no-console
    console.log(`Templates directory: ${config.templateDir}`);
  });
}

if (process.env.NODE_ENV !== "test") {
  start().catch((error) => {
    // eslint-disable-next-line no-console
    console.error("Failed to start template creator", error);
    process.exit(1);
  });
}
