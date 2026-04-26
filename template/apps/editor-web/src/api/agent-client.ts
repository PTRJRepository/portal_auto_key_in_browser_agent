import type {
  FlowOptimizationReport,
  RecordingSession,
  RunResult,
  TemplatePackage,
  TemplateSummary
} from "@template/flow-schema";

const AGENT_BASE_URL = import.meta.env.VITE_AGENT_BASE_URL as string | undefined;

type JsonValue = Record<string, unknown>;

export function apiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return AGENT_BASE_URL ? `${AGENT_BASE_URL}/api${normalized}` : `/api${normalized}`;
}

async function postJson<TResponse>(path: string, body: JsonValue): Promise<TResponse> {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    const raw = (await response.json().catch(() => ({ error: "Unknown request failure" }))) as {
      error?: string;
    };
    throw new Error(raw.error ?? `Request failed: ${response.status}`);
  }

  return (await response.json()) as TResponse;
}

export async function startRecording(url: string): Promise<RecordingSession> {
  return postJson<RecordingSession>("/recordings", { url });
}

export async function stopRecording(sessionId: string): Promise<TemplatePackage> {
  return postJson<TemplatePackage>(`/recordings/${sessionId}/stop`, {});
}

export async function listTemplates(): Promise<TemplateSummary[]> {
  const response = await fetch(apiUrl("/templates"));
  if (!response.ok) {
    throw new Error("Unable to load templates");
  }
  const payload = (await response.json()) as { templates: TemplateSummary[] };
  return payload.templates;
}

export async function getTemplate(templateId: string): Promise<TemplatePackage> {
  const response = await fetch(apiUrl(`/templates/${templateId}`));
  if (!response.ok) {
    throw new Error(`Unable to load template ${templateId}`);
  }
  return (await response.json()) as TemplatePackage;
}

export type ImportTemplateResult = {
  template: TemplateSummary;
  templatePackage: TemplatePackage;
  optimization: FlowOptimizationReport;
};

export async function importTemplate(
  packageJson: string,
  options?: {
    optimize?: boolean;
  }
): Promise<ImportTemplateResult> {
  return postJson<ImportTemplateResult>("/templates/import", {
    packageJson,
    optimize: options?.optimize ?? true
  });
}

export async function exportTemplate(templateId: string): Promise<TemplatePackage> {
  const response = await fetch(apiUrl(`/templates/${templateId}/export`));
  if (!response.ok) {
    throw new Error(`Unable to export template ${templateId}`);
  }
  return (await response.json()) as TemplatePackage;
}

export async function runTemplate(params: {
  templateId?: string;
  template?: TemplatePackage;
  variables: Record<string, string>;
  strictFidelity?: boolean;
  recallFromSaved?: boolean;
}): Promise<RunResult> {
  return postJson<RunResult>("/runs", params as JsonValue);
}

export function wsUrl(locationLike: Pick<Location | URL, "protocol" | "host"> = window.location): string {
  if (AGENT_BASE_URL) {
    return AGENT_BASE_URL.replace(/^http/i, "ws") + "/ws";
  }
  const protocol = locationLike.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${locationLike.host}/ws`;
}
