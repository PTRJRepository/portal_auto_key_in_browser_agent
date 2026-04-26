import type { Page, Locator } from "playwright";
import type { FlowStep } from "@template/flow-schema";
import { retryWithBackoff, type RetryOptions } from "./wait-utils.js";

export interface SelectorCandidate {
  selector: string;
  weight: number;
  type: "css" | "text" | "role" | "id" | "name" | "xpath" | "tag";
}

export interface ResilientLocatorOptions {
  timeoutMs: number;
  retryOptions: RetryOptions;
}

export function buildSelectorCandidates(step: FlowStep): SelectorCandidate[] {
  const candidates: SelectorCandidate[] = [];

  if (step.selector) {
    candidates.push({ selector: step.selector, weight: 100, type: "css" });
  }

  if (step.selectorFallback?.css) {
    const css = step.selectorFallback.css;
    const idMatch = css.match(/#([a-zA-Z0-9_-]+)/);
    if (idMatch) {
      candidates.push({ selector: `#${idMatch[1]}`, weight: 95, type: "id" });
    }
    candidates.push({ selector: css, weight: 85, type: "css" });
  }

  if (step.selectorFallback?.text) {
    candidates.push({
      selector: `text=${step.selectorFallback.text}`,
      weight: 80,
      type: "text"
    });
  }

  if (step.selectorFallback?.role) {
    candidates.push({
      selector: `[role="${step.selectorFallback.role}"]`,
      weight: 70,
      type: "role"
    });
  }

  if (step.selectorFallback?.tag) {
    candidates.push({
      selector: step.selectorFallback.tag,
      weight: 40,
      type: "tag"
    });
  }

  return candidates.sort((a, b) => b.weight - a.weight);
}

export async function resolveResilientLocator(
  page: Page,
  step: FlowStep,
  options: ResilientLocatorOptions
): Promise<Locator> {
  const candidates = buildSelectorCandidates(step);

  if (candidates.length === 0) {
    throw new Error(`No selectors available for step ${step.id}`);
  }

  const { timeoutMs, retryOptions } = options;

  return retryWithBackoff(async () => {
    for (const candidate of candidates) {
      const locator = page.locator(candidate.selector).first();
      const count = await locator.count();

      if (count > 0) {
        const isVisible = await locator.isVisible().catch(() => false);
        if (isVisible || candidate.type === "text") {
          return locator;
        }
      }
    }

    const triedSelectors = candidates.map((c) => `${c.type}: ${c.selector}`).join(", ");
    throw new Error(
      `Element not found for step ${step.label}. Tried: ${triedSelectors}`
    );
  }, retryOptions);
}