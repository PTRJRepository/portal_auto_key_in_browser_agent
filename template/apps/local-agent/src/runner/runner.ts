import { randomUUID } from "node:crypto";

import { chromium, type Page } from "playwright";

import { type FlowStep, type RunResult, type StepExecutionResult, type TemplatePackage } from "@template/flow-schema";

import type { AgentEvent } from "../types.js";
import { retryWithBackoff, waitForNetworkIdle, DEFAULT_RETRY_OPTIONS } from "./wait-utils.js";
import { captureFailureScreenshot } from "./screenshot-utils.js";
import { resolveResilientLocator } from "./selector-resolver.js";

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

function isTextLikeInput(inputType: string | undefined): boolean {
  return ["text", "password", "email", "search", "tel", "url", "number"].includes(inputType ?? "");
}

function isCheckableInput(inputType: string | undefined): boolean {
  return inputType === "radio" || inputType === "checkbox";
}

function coerceLegacyInputStep(step: FlowStep): FlowStep {
  const inputType = step.metadata?.inputType;

  if ((step.type === "type" || step.type === "select") && isCheckableInput(inputType)) {
    return {
      ...step,
      type: "check",
      label: step.label.replace(/^(Type|Select):/, "Check:")
    };
  }

  if (step.type === "select" && isTextLikeInput(inputType)) {
    return {
      ...step,
      type: "type",
      label: step.label.replace(/^Select:/, "Type:")
    };
  }

  return step;
}

async function executeStep(page: Page, step: FlowStep, variables: Record<string, string>): Promise<void> {
  const value = resolveStepValue(step, variables);
  const timeout = step.timeoutMs;

  switch (step.type) {
    case "openPage":
      if (!value) {
        throw new Error("openPage step requires URL value");
      }
      await page.goto(value, { timeout, waitUntil: "networkidle" });
      if (value.startsWith("http")) {
        const expected = normalizeComparableUrl(value);
        const actual = normalizeComparableUrl(page.url());
        if (actual !== expected) {
          throw new Error(`openPage URL mismatch. expected=${expected} actual=${actual}`);
        }
      }
      return;
    case "click": {
      const locator = await resolveResilientLocator(page, step, {
        timeoutMs: timeout,
        retryOptions: DEFAULT_RETRY_OPTIONS
      });
      await locator.click({ timeout, delay: 50 });
      return;
    }
    case "type": {
      const locator = await resolveResilientLocator(page, step, {
        timeoutMs: timeout,
        retryOptions: DEFAULT_RETRY_OPTIONS
      });
      await locator.clear();
      await locator.fill(value ?? "", { timeout });
      return;
    }
    case "select": {
      const locator = await resolveResilientLocator(page, step, {
        timeoutMs: timeout,
        retryOptions: DEFAULT_RETRY_OPTIONS
      });
      if (!value) {
        throw new Error("select step requires value");
      }
      await locator.selectOption(value, { timeout });
      return;
    }
    case "check": {
      const locator = await resolveResilientLocator(page, step, {
        timeoutMs: timeout,
        retryOptions: DEFAULT_RETRY_OPTIONS
      });
      await locator.check({ timeout });
      return;
    }
    case "uncheck": {
      const locator = await resolveResilientLocator(page, step, {
        timeoutMs: timeout,
        retryOptions: DEFAULT_RETRY_OPTIONS
      });
      await locator.uncheck({ timeout });
      return;
    }
    case "waitForElement": {
      const locator = await resolveResilientLocator(page, step, {
        timeoutMs: timeout,
        retryOptions: DEFAULT_RETRY_OPTIONS
      });
      await locator.waitFor({
        timeout,
        state: "visible"
      });
      return;
    }
    case "waitForNavigation":
      if (value?.startsWith("http")) {
        await page.waitForURL(value, { timeout, waitUntil: "networkidle" });
        const expected = normalizeComparableUrl(value);
        const actual = normalizeComparableUrl(page.url());
        if (actual !== expected) {
          throw new Error(`waitForNavigation URL mismatch. expected=${expected} actual=${actual}`);
        }
      } else {
        await waitForNetworkIdle(page, timeout);
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

    const browser = await chromium.launch({
      headless: false,
      args: [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox"
      ]
    });
    const context = await browser.newContext();
    const page = await context.newPage();

    let overallStatus: RunResult["status"] = "success";
    let failureMessage: string | undefined;
    let failedStepId: string | undefined;
    let failedAtIndex: number | null = null;

    try {
      await page.goto(templatePackage.entry.url, {
        timeout: templatePackage.runtime.defaultTimeoutMs,
        waitUntil: "networkidle"
      });

      for (let index = 0; index < templatePackage.flow.length; index += 1) {
        const step = templatePackage.flow[index];
        const executableStep = coerceLegacyInputStep(step);
        try {
          const stepWithRetry = retryWithBackoff(
            () => executeStep(page, executableStep, variables),
            DEFAULT_RETRY_OPTIONS
          );
          await stepWithRetry;
          stepResults.push({
            stepId: step.id,
            type: executableStep.type,
            status: "success"
          });
          this.publishEvent({
            type: "run.step",
            payload: {
              runId,
              stepId: step.id,
              stepType: executableStep.type,
              status: "success"
            }
          });
        } catch (error) {
          const message = error instanceof Error ? error.message : "Unknown execution error";

          await captureFailureScreenshot(page, step.id, step.label);

          stepResults.push({
            stepId: step.id,
            type: executableStep.type,
            status: "failed",
            message
          });

          this.publishEvent({
            type: "run.step",
            payload: {
              runId,
              stepId: step.id,
              stepType: executableStep.type,
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
  calculateFidelity,
  coerceLegacyInputStep
};