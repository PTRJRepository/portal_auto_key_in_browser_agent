import { randomUUID } from "node:crypto";

import type { FlowStep } from "@template/flow-schema";

import type { RawBrowserEvent } from "../types.js";

function toLabel(prefix: string, target?: string): string {
  return target ? `${prefix}: ${target}` : prefix;
}

function optionalNonEmpty(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

function makeSelectorFallback(fallback: { text?: string; tag?: string } | undefined): FlowStep["selectorFallback"] {
  const selectorFallback: FlowStep["selectorFallback"] = {};
  const text = optionalNonEmpty(fallback?.text);
  const tag = optionalNonEmpty(fallback?.tag);
  if (text) {
    selectorFallback.text = text;
  }
  if (tag) {
    selectorFallback.tag = tag;
  }
  return Object.keys(selectorFallback).length > 0 ? selectorFallback : undefined;
}

function makeBaseStep(params: {
  type: FlowStep["type"];
  label: string;
  selector?: string;
  value?: string;
  variableRef?: string;
  metadata?: FlowStep["metadata"];
  fallback?: FlowStep["selectorFallback"];
}): FlowStep {
  return {
    id: randomUUID(),
    type: params.type,
    label: params.label,
    selector: params.selector,
    selectorFallback: params.fallback,
    value: params.value,
    variableRef: params.variableRef,
    valueMode: params.value !== undefined ? "fixed" : undefined,
    timeoutMs: 15000,
    continueOnError: false,
    metadata: params.metadata
  };
}

function flowFingerprint(step: FlowStep): string {
  return JSON.stringify({
    type: step.type,
    selector: step.selector ?? "",
    value: step.value ?? "",
    key: step.type === "pressKey" ? step.value ?? "" : "",
    url: step.metadata?.url ?? "",
    fallbackText: step.selectorFallback?.text ?? "",
    fallbackTag: step.selectorFallback?.tag ?? ""
  });
}

function canLatestStateWin(previous: FlowStep, current: FlowStep): boolean {
  return (
    (current.type === "type" || current.type === "select") &&
    previous.type === current.type &&
    (previous.selector ?? "") === (current.selector ?? "") &&
    (previous.metadata?.url ?? "") === (current.metadata?.url ?? "")
  );
}

function convertEventToStep(event: RawBrowserEvent): FlowStep | undefined {
  if (event.kind === "click") {
    return makeBaseStep({
      type: "click",
      label: toLabel("Click", event.selector),
      selector: event.selector,
      fallback: makeSelectorFallback(event.fallback),
      metadata: { url: event.url }
    });
  }

  if (event.kind === "input") {
    if (event.inputType === "radio" || event.inputType === "checkbox") {
      return undefined;
    }

    return makeBaseStep({
      type: "type",
      label: toLabel("Type", event.selector),
      selector: event.selector,
      value: event.value,
      metadata: {
        url: event.url,
        inputType: event.inputType
      }
    });
  }

  if (event.kind === "change") {
    if (event.inputType === "checkbox" || event.inputType === "radio") {
      return makeBaseStep({
        type: event.checked ? "check" : "uncheck",
        label: toLabel(event.checked ? "Check" : "Uncheck", event.selector),
        selector: event.selector,
        metadata: {
          url: event.url,
          inputType: event.inputType
        }
      });
    }

    if (event.inputType !== "select") {
      return undefined;
    }

    return makeBaseStep({
      type: "select",
      label: toLabel("Select", event.selector),
      selector: event.selector,
      value: event.value,
      metadata: {
        url: event.url,
        inputType: event.inputType
      }
    });
  }

  if (event.kind === "keydown") {
    const supportedKeys = new Set(["Enter", "Tab", "Escape", "ArrowDown", "ArrowUp"]);
    if (!supportedKeys.has(event.key)) {
      return undefined;
    }

    return makeBaseStep({
      type: "pressKey",
      label: toLabel("Press key", event.key),
      value: event.key,
      metadata: { url: event.url }
    });
  }

  if (event.kind === "navigation") {
    return makeBaseStep({
      type: "waitForNavigation",
      label: "Wait for navigation",
      value: event.url,
      metadata: { url: event.url }
    });
  }

  return undefined;
}

export function normalizeRecordedEvents(entryUrl: string, events: RawBrowserEvent[]): FlowStep[] {
  const steps: FlowStep[] = [
    makeBaseStep({
      type: "openPage",
      label: "Open start page",
      value: entryUrl,
      metadata: { url: entryUrl }
    })
  ];

  for (const event of events) {
    const converted = convertEventToStep(event);
    if (!converted) {
      continue;
    }

    const previous = steps[steps.length - 1];

    if (previous && canLatestStateWin(previous, converted)) {
      steps[steps.length - 1] = converted;
      continue;
    }

    if (previous && flowFingerprint(previous) === flowFingerprint(converted)) {
      continue;
    }

    steps.push(converted);
  }

  return steps;
}
