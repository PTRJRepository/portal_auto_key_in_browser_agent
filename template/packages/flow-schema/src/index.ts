import { z } from "zod";

export const FLOW_SCHEMA_VERSION = "1.0.0";

export const stepTypeValues = [
  "openPage",
  "click",
  "type",
  "select",
  "check",
  "uncheck",
  "waitForElement",
  "waitForNavigation",
  "pressKey"
] as const;

export const stepTypeSchema = z.enum(stepTypeValues);
export type StepType = z.infer<typeof stepTypeSchema>;

export const stepValueModeValues = [
  "fixed",
  "variable",
  "generatedTimestamp",
  "generatedRandomNumber",
  "generatedUuid"
] as const;

export const stepValueModeSchema = z.enum(stepValueModeValues);
export type StepValueMode = z.infer<typeof stepValueModeSchema>;

export const selectorFallbackSchema = z
  .object({
    css: z.string().min(1).optional(),
    text: z.string().min(1).optional(),
    role: z.string().min(1).optional(),
    tag: z.string().min(1).optional()
  })
  .refine((value) => Object.keys(value).length > 0, {
    message: "selectorFallback needs at least one strategy"
  });

const stepSchemaBase = z.object({
  id: z.string().min(1),
  type: stepTypeSchema,
  label: z.string().min(1),
  selector: z.string().min(1).optional(),
  selectorFallback: selectorFallbackSchema.optional(),
  value: z.string().optional(),
  variableRef: z.string().min(1).optional(),
  valueMode: stepValueModeSchema.optional(),
  timeoutMs: z.number().int().positive().max(600000).default(15000),
  continueOnError: z.boolean().default(false),
  metadata: z
    .object({
      url: z.string().url().optional(),
      inputType: z.string().optional()
    })
    .optional()
});

export const flowStepSchema = stepSchemaBase.superRefine((step, ctx) => {
  const selectorRequiredFor: StepType[] = [
    "click",
    "type",
    "select",
    "check",
    "uncheck",
    "waitForElement"
  ];

  if (selectorRequiredFor.includes(step.type) && !step.selector && !step.selectorFallback?.css) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["selector"],
      message: `selector is required for step type ${step.type}`
    });
  }

  if (step.type === "openPage" && !step.value) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["value"],
      message: "openPage requires value to contain URL"
    });
  }

  if (step.variableRef && step.variableRef.includes(" ")) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["variableRef"],
      message: "variableRef cannot contain spaces"
    });
  }
});

export type FlowStep = z.infer<typeof flowStepSchema>;

export const templateVariableSchema = z.object({
  name: z.string().min(1).regex(/^[a-zA-Z_][a-zA-Z0-9_]*$/),
  label: z.string().min(1),
  defaultValue: z.string().optional()
});

export type TemplateVariable = z.infer<typeof templateVariableSchema>;

export const templatePackageSchema = z.object({
  schemaVersion: z.string().min(1).default(FLOW_SCHEMA_VERSION),
  template: z.object({
    id: z.string().min(1),
    name: z.string().min(1),
    description: z.string().default(""),
    version: z.string().min(1).default("1.0.0"),
    createdAt: z.string().datetime()
  }),
  entry: z.object({
    url: z.string().url()
  }),
  variables: z.array(templateVariableSchema).default([]),
  flow: z.array(flowStepSchema),
  runtime: z.object({
    defaultTimeoutMs: z.number().int().positive().max(600000).default(15000),
    sessionMode: z.enum(["fresh"]).default("fresh")
  })
});

export type TemplatePackage = z.infer<typeof templatePackageSchema>;

export type TemplateSummary = Pick<TemplatePackage["template"], "id" | "name" | "version" | "createdAt">;

export type RecordingSession = {
  sessionId: string;
  url: string;
  startedAt: string;
};

export type StepExecutionResult = {
  stepId: string;
  type: StepType;
  status: "success" | "failed" | "skipped";
  message?: string;
};

export type RunResult = {
  runId: string;
  templateId: string;
  startedAt: string;
  finishedAt: string;
  status: "success" | "failed";
  failedStepId?: string;
  message?: string;
  fidelity?: {
    mode: "strict" | "basic";
    expectedSteps: number;
    successfulSteps: number;
    scorePercent: number;
    exactMatch: boolean;
  };
  steps: StepExecutionResult[];
};

export function validateTemplatePackage(input: unknown): TemplatePackage {
  return templatePackageSchema.parse(input);
}

export function summarizeTemplate(templatePackage: TemplatePackage): TemplateSummary {
  const { id, name, version, createdAt } = templatePackage.template;
  return { id, name, version, createdAt };
}

export function createTemplatePackage(params: {
  id: string;
  name: string;
  entryUrl: string;
  flow: FlowStep[];
  description?: string;
  variables?: TemplateVariable[];
}): TemplatePackage {
  return validateTemplatePackage({
    schemaVersion: FLOW_SCHEMA_VERSION,
    template: {
      id: params.id,
      name: params.name,
      description: params.description ?? "",
      version: "1.0.0",
      createdAt: new Date().toISOString()
    },
    entry: { url: params.entryUrl },
    variables: params.variables ?? [],
    flow: params.flow,
    runtime: {
      defaultTimeoutMs: 15000,
      sessionMode: "fresh"
    }
  });
}

export function serializeTemplatePackage(templatePackage: TemplatePackage): string {
  return JSON.stringify(templatePackage, null, 2);
}

export type FlowOptimizationReport = {
  originalSteps: number;
  optimizedSteps: number;
  removedSteps: number;
  reasons: {
    duplicateConsecutiveStep: number;
    latestInputStateWins: number;
  };
};

function toComparableKey(step: FlowStep): string {
  return JSON.stringify({
    type: step.type,
    selector: step.selector ?? "",
    value: step.value ?? "",
    variableRef: step.variableRef ?? "",
    valueMode: step.valueMode ?? "fixed",
    continueOnError: step.continueOnError,
    timeoutMs: step.timeoutMs
  });
}

function isLatestInputStatePair(previous: FlowStep, current: FlowStep): boolean {
  const latestWinsTypes: StepType[] = ["type", "select"];
  return (
    latestWinsTypes.includes(previous.type) &&
    previous.type === current.type &&
    (previous.selector ?? "") === (current.selector ?? "")
  );
}

export function optimizeFlowSteps(flow: FlowStep[]): { flow: FlowStep[]; report: FlowOptimizationReport } {
  const optimized: FlowStep[] = [];
  const report: FlowOptimizationReport = {
    originalSteps: flow.length,
    optimizedSteps: 0,
    removedSteps: 0,
    reasons: {
      duplicateConsecutiveStep: 0,
      latestInputStateWins: 0
    }
  };

  for (const step of flow) {
    const previous = optimized[optimized.length - 1];
    if (!previous) {
      optimized.push(step);
      continue;
    }

    if (toComparableKey(previous) === toComparableKey(step)) {
      report.reasons.duplicateConsecutiveStep += 1;
      continue;
    }

    if (isLatestInputStatePair(previous, step)) {
      optimized[optimized.length - 1] = step;
      report.reasons.latestInputStateWins += 1;
      continue;
    }

    optimized.push(step);
  }

  report.optimizedSteps = optimized.length;
  report.removedSteps = report.originalSteps - report.optimizedSteps;

  return { flow: optimized, report };
}

export function optimizeTemplatePackage(templatePackage: TemplatePackage): {
  templatePackage: TemplatePackage;
  report: FlowOptimizationReport;
} {
  const { flow, report } = optimizeFlowSteps(templatePackage.flow);
  return {
    templatePackage: {
      ...templatePackage,
      flow
    },
    report
  };
}
