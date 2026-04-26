import { randomUUID } from "node:crypto";

import { chromium, type Browser, type BrowserContext, type Page } from "playwright";

import { createTemplatePackage, type RecordingSession, type TemplatePackage } from "@template/flow-schema";

import type { AgentEvent, RawBrowserEvent } from "../types.js";
import { normalizeRecordedEvents } from "./normalizer.js";

type InternalSession = {
  sessionId: string;
  url: string;
  startedAt: string;
  browser: Browser;
  context: BrowserContext;
  page: Page;
  events: RawBrowserEvent[];
};

async function closeIgnoringAlreadyClosed(closeResource: () => Promise<void>): Promise<void> {
  try {
    await closeResource();
  } catch {
    // Browser may already be closed manually by the user. Recording finalization
    // must still save the captured flow.
  }
}

async function launchRecorderBrowser(): Promise<Browser> {
  const errors: string[] = [];

  const candidates: Array<{
    label: string;
    launch: () => Promise<Browser>;
  }> = [
    {
      label: "playwright chromium",
      launch: () => chromium.launch({ headless: false })
    },
    {
      label: "google chrome channel",
      launch: () => chromium.launch({ headless: false, channel: "chrome" })
    },
    {
      label: "microsoft edge channel",
      launch: () => chromium.launch({ headless: false, channel: "msedge" })
    }
  ];

  for (const candidate of candidates) {
    try {
      return await candidate.launch();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown launch error";
      errors.push(`${candidate.label}: ${message}`);
    }
  }

  throw new Error(
    `Gagal membuka browser untuk recording. Coba jalankan "npm run setup:chromium" atau pastikan Chrome/Edge terpasang. Detail: ${errors.join(
      " | "
    )}`
  );
}

const recorderScript = `
(() => {
  const buildSelector = (element) => {
    if (!(element instanceof Element)) return "";
    if (element.id) return "#" + CSS.escape(element.id);
    const parts = [];
    let current = element;
    while (current && current.nodeType === 1 && parts.length < 3) {
      let selector = current.tagName.toLowerCase();
      if (current.classList.length > 0) {
        selector += "." + Array.from(current.classList).slice(0, 2).map((c) => CSS.escape(c)).join(".");
      }
      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((child) => child.tagName === current.tagName);
        if (siblings.length > 1) {
          selector += ":nth-of-type(" + (siblings.indexOf(current) + 1) + ")";
        }
      }
      parts.unshift(selector);
      current = parent;
    }
    return parts.join(" > ");
  };

  const emit = (event) => {
    const handler = window.__templateRecorderEmit;
    if (typeof handler === "function") {
      handler(event).catch(() => {});
    }
  };

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    emit({
      kind: "click",
      selector: buildSelector(target),
      fallback: {
        text: (target.textContent || "").trim().slice(0, 80),
        tag: target.tagName.toLowerCase()
      },
      url: window.location.href
    });
  }, true);

  document.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
    emit({
      kind: "input",
      selector: buildSelector(target),
      value: target.value || "",
      inputType: target.type || "text",
      url: window.location.href
    });
  }, true);

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
    emit({
      kind: "change",
      selector: buildSelector(target),
      value: "value" in target ? (target.value || "") : "",
      inputType: target instanceof HTMLInputElement ? target.type : "select",
      checked: target instanceof HTMLInputElement ? target.checked : undefined,
      url: window.location.href
    });
  }, true);

  document.addEventListener("keydown", (event) => {
    emit({
      kind: "keydown",
      key: event.key,
      url: window.location.href
    });
  }, true);
})();
`;

export class RecorderService {
  private readonly sessions = new Map<string, InternalSession>();

  constructor(private readonly publishEvent: (event: AgentEvent) => void) {}

  public async startRecording(url: string): Promise<RecordingSession> {
    const browser = await launchRecorderBrowser();
    const context = await browser.newContext();
    const sessionId = randomUUID();
    const startedAt = new Date().toISOString();
    const events: RawBrowserEvent[] = [];

    await context.exposeBinding("__templateRecorderEmit", async (_source, payload: RawBrowserEvent) => {
      events.push(payload);
      this.publishEvent({
        type: "recording.event",
        payload: {
          sessionId,
          event: payload
        }
      });
      this.publishFlowPreview(sessionId, url, events);
    });

    await context.addInitScript(recorderScript);
    const page = await context.newPage();
    this.bindNavigation(page, sessionId, url, events);
    context.on("page", (newPage) => {
      this.bindNavigation(newPage, sessionId, url, events);
    });

    await page.goto(url, { waitUntil: "domcontentloaded" });

    this.sessions.set(sessionId, {
      sessionId,
      startedAt,
      url,
      browser,
      context,
      page,
      events
    });
    browser.on("disconnected", () => {
      if (!this.sessions.has(sessionId)) {
        return;
      }
      this.publishEvent({
        type: "recording.browserClosed",
        payload: {
          sessionId
        }
      });
    });

    this.publishEvent({
      type: "recording.started",
      payload: {
        sessionId,
        url
      }
    });
    this.publishFlowPreview(sessionId, url, events);

    return {
      sessionId,
      url,
      startedAt
    };
  }

  public async stopRecording(sessionId: string): Promise<TemplatePackage> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Recording session not found: ${sessionId}`);
    }

    const templatePackage = buildTemplateFromRecordedEvents(session.url, session.events);

    this.sessions.delete(sessionId);
    await closeIgnoringAlreadyClosed(() => session.context.close());
    await closeIgnoringAlreadyClosed(() => session.browser.close());

    this.publishEvent({
      type: "recording.stopped",
      payload: {
        sessionId,
        templateId: templatePackage.template.id
      }
    });

    return templatePackage;
  }

  private bindNavigation(
    page: Page,
    sessionId: string,
    entryUrl: string,
    events: RawBrowserEvent[]
  ): void {
    page.on("framenavigated", (frame) => {
      if (frame !== page.mainFrame()) {
        return;
      }

      const event: RawBrowserEvent = {
        kind: "navigation",
        url: frame.url()
      };
      events.push(event);
      this.publishEvent({
        type: "recording.event",
        payload: {
          sessionId,
          event
        }
      });
      this.publishFlowPreview(sessionId, entryUrl, events);
    });
  }

  private publishFlowPreview(sessionId: string, entryUrl: string, events: RawBrowserEvent[]): void {
    const flow = normalizeRecordedEvents(entryUrl, events);
    this.publishEvent({
      type: "recording.flowPreview",
      payload: {
        sessionId,
        entryUrl,
        flow
      }
    });
  }
}

export function buildTemplateFromRecordedEvents(
  entryUrl: string,
  events: RawBrowserEvent[],
  templateName?: string
): TemplatePackage {
  const normalizedFlow = normalizeRecordedEvents(entryUrl, events);
  return createTemplatePackage({
    id: randomUUID(),
    name: templateName ?? `Template ${new Date().toISOString()}`,
    entryUrl,
    flow: normalizedFlow
  });
}
