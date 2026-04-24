import { randomUUID } from "node:crypto";

import { chromium, type Page } from "playwright";

import { type FlowStep, type RunResult, type StepExecutionResult, type TemplatePackage } from "@template/flow-schema";

import type { AgentEvent } from "../types.js";

function resolveStepValue(step: FlowStep, variables: Record<string, string>): string | undefined {
  const mode = step.valueMode ?? (step.variableRef ? "variable" : "fixed");

  if (mode === "generatedTimestamp") {
    return new Date().toISOString();
  }

  if (mode === "generatedRandomNumber") {
    return `${Math.floor(100000 + Math.random() * 900000)}`;
  }

  if (mode === "generatedUuid") {
    return randomUUID();
  }

  if (mode === "variable") {
    if (!step.variableRef) {
      return step.value;
    }
    return variables[step.variableRef] ?? step.value;
  }

  return step.value;
}

function normalizeComparableUrl(rawUrl: string): string {
  try {
    const parsed = new URL(rawUrl);
    parsed.hash = "";
    if (parsed.pathname.length > 1 && parsed.pathname.endsWith("/")) {
      parsed.pathname = parsed.pathname.slice(0, -1);
    }
    return parsed.toString();
  } catch {
    return rawUrl;
  }
}

async function resolveLocator(page: Page, step: FlowStep) {
  const candidates: string[] = [];
  if (step.selector) {
    candidates.push(step.selector);
  }
  if (step.selectorFallback?.css) {
    candidates.push(step.selectorFallback.css);
  }
  if (step.selectorFallback?.text) {
    candidates.push(`text=${step.selectorFallback.text}`);
  }

  for (const candidate of candidates) {
    const locator = page.locator(candidate).first();
    if ((await locator.count()) > 0) {
      return locator;
    }
  }
  throw new Error(`Unable to find element for step ${step.id}`);
}

async function executeStep(page: Page, step: FlowStep, variables: Record<string, string>): Promise<void> {
  const value = resolveStepValue(step, variables);
  const timeout = step.timeoutMs;

  switch (step.type) {
    case "openPage":
      if (!value) {
        throw new Error("openPage step requires URL value");
      }
      await page.goto(value, { timeout, waitUntil: "domcontentloaded" });
      if (value.startsWith("http")) {
        const expected = normalizeComparableUrl(value);
        const actual = normalizeComparableUrl(page.url());
        if (actual !== expected) {
          throw new Error(`openPage URL mismatch. expected=${expected} actual=${actual}`);
        }
      }
      return;
    case "click": {
      const locator = await resolveLocator(page, step);
      await locator.click({ timeout });
      return;
    }
    case "type": {
      const locator = await resolveLocator(page, step);
      await locator.fill(value ?? "", { timeout });
      return;
    }
    case "select": {
      const locator = await resolveLocator(page, step);
      if (!value) {
        throw new Error("select step requires value");
      }
      await locator.selectOption(value, { timeout });
      return;
    }
    case "check": {
      const locator = await resolveLocator(page, step);
      await locator.check({ timeout });
      return;
    }
    case "uncheck": {
      const locator = await resolveLocator(page, step);
      await locator.uncheck({ timeout });
      return;
    }
    case "waitForElement": {
      const locator = await resolveLocator(page, step);
      await locator.waitFor({
        timeout,
        state: "visible"
      });
      return;
    }
    case "waitForNavigation":
      if (value?.startsWith("http")) {
        await page.waitForURL(value, { timeout });
        const expected = normalizeComparableUrl(value);
        const actual = normalizeComparableUrl(page.url());
        if (actual !== expected) {
          throw new Error(`waitForNavigation URL mismatch. expected=${expected} actual=${actual}`);
        }
      } else {
        await page.waitForLoadState("domcontentloaded", { timeout });
      }
      return;
    case "pressKey":
      await page.keyboard.press(value ?? "Enter");
      return;
    default:
      throw new Error(`Unsupported step type: ${(step as FlowStep).type}`);
  }
}

function calculateFidelity(
  expectedSteps: number,
  stepResults: StepExecutionResult[],
  mode: "strict" | "basic"
): NonNullable<RunResult["fidelity"]> {
  const successfulSteps = stepResults.filter((step) => step.status === "success").length;
  const ratio = expectedSteps === 0 ? 1 : successfulSteps / expectedSteps;
  const scorePercent = Number((ratio * 100).toFixed(2));
  const exactMatch = successfulSteps === expectedSteps && stepResults.length === expectedSteps;
  return {
    mode,
    expectedSteps,
    successfulSteps,
    scorePercent,
    exactMatch
  };
}

export type RunTemplateOptions = {
  strictFidelity?: boolean;
};

export class TemplateRunner {
  constructor(private readonly publishEvent: (event: AgentEvent) => void) {}

  public async runTemplate(
    templatePackage: TemplatePackage,
    variables: Record<string, string>,
    options?: RunTemplateOptions
  ): Promise<RunResult> {
    const strictFidelity = options?.strictFidelity ?? true;
    const runId = randomUUID();
    const startedAt = new Date().toISOString();
    const stepResults: StepExecutionResult[] = [];
    this.publishEvent({
      type: "run.started",
      payload: {
        runId,
        templateId: templatePackage.template.id
      }
    });

    const browser = await chromium.launch({ headless: false });
    const context = await browser.newContext();
    const page = await context.newPage();

    let overallStatus: RunResult["status"] = "success";
    let failureMessage: string | undefined;
    let failedStepId: string | undefined;
    let failedAtIndex: number | null = null;

    try {
      await page.goto(templatePackage.entry.url, {
        timeout: templatePackage.runtime.defaultTimeoutMs,
        waitUntil: "domcontentloaded"
      });

      for (let index = 0; index < templatePackage.flow.length; index += 1) {
        const step = templatePackage.flow[index];
        try {
          await executeStep(page, step, variables);
          stepResults.push({
            stepId: step.id,
            type: step.type,
            status: "success"
          });
          this.publishEvent({
            type: "run.step",
            payload: {
              runId,
              stepId: step.id,
              stepType: step.type,
              status: "success"
            }
          });
        } catch (error) {
          const message = error instanceof Error ? error.message : "Unknown execution error";
          stepResults.push({
            stepId: step.id,
            type: step.type,
            status: "failed",
            message
          });

          this.publishEvent({
            type: "run.step",
            payload: {
              runId,
              stepId: step.id,
              stepType: step.type,
              status: "failed",
              message
            }
          });

          const shouldContinue = !strictFidelity && step.continueOnError;
          if (!shouldContinue) {
            overallStatus = "failed";
            failureMessage = message;
            failedStepId = step.id;
            failedAtIndex = index;
            break;
          }
        }
      }

      if (failedAtIndex !== null) {
        for (let index = failedAtIndex + 1; index < templatePackage.flow.length; index += 1) {
          const step = templatePackage.flow[index];
          stepResults.push({
            stepId: step.id,
            type: step.type,
            status: "skipped",
            message: "Skipped because previous step failed"
          });
        }
      }
    } finally {
      await context.close();
      await browser.close();
    }

    const fidelity = calculateFidelity(
      templatePackage.flow.length,
      stepResults,
      strictFidelity ? "strict" : "basic"
    );

    if (strictFidelity && !fidelity.exactMatch) {
      overallStatus = "failed";
      if (!failureMessage) {
        failureMessage = "Strict fidelity mismatch. Replay is not 100% identical to template.";
      }
    }

    const finishedAt = new Date().toISOString();
    this.publishEvent({
      type: "run.completed",
      payload: {
        runId,
        templateId: templatePackage.template.id,
        status: overallStatus,
        failedStepId,
        message: failureMessage,
        fidelityScorePercent: fidelity.scorePercent,
        exactMatch: fidelity.exactMatch
      }
    });

    return {
      runId,
      templateId: templatePackage.template.id,
      startedAt,
      finishedAt,
      status: overallStatus,
      failedStepId,
      message: failureMessage,
      fidelity,
      steps: stepResults
    };
  }
}

export const runnerInternals = {
  resolveStepValue,
  calculateFidelity
};
