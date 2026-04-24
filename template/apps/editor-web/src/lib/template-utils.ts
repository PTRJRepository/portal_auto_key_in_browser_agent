import type { FlowStep, TemplatePackage, TemplateVariable } from "@template/flow-schema";

export function reorderSteps(flow: FlowStep[], sourceIndex: number, targetIndex: number): FlowStep[] {
  if (sourceIndex === targetIndex) {
    return [...flow];
  }

  const next = [...flow];
  const [moved] = next.splice(sourceIndex, 1);
  next.splice(targetIndex, 0, moved);
  return next;
}

export function updateStep(templatePackage: TemplatePackage, stepId: string, patch: Partial<FlowStep>): TemplatePackage {
  return {
    ...templatePackage,
    flow: templatePackage.flow.map((step) => (step.id === stepId ? { ...step, ...patch } : step))
  };
}

function sanitizeVariableName(raw: string): string {
  const normalized = raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_ ]/g, "")
    .replace(/\s+/g, "_");
  if (!normalized) {
    return "field_value";
  }
  if (!/^[a-z_]/.test(normalized)) {
    return `field_${normalized}`;
  }
  return normalized;
}

function ensureUniqueName(baseName: string, variables: TemplateVariable[]): string {
  const existing = new Set(variables.map((item) => item.name));
  if (!existing.has(baseName)) {
    return baseName;
  }
  let index = 2;
  while (existing.has(`${baseName}_${index}`)) {
    index += 1;
  }
  return `${baseName}_${index}`;
}

export function convertStepValueToVariable(templatePackage: TemplatePackage, stepId: string): TemplatePackage {
  const targetStep = templatePackage.flow.find((step) => step.id === stepId);
  if (!targetStep || !targetStep.value) {
    return templatePackage;
  }

  const baseName = sanitizeVariableName(targetStep.label);
  const variableName = ensureUniqueName(baseName, templatePackage.variables);

  const variable: TemplateVariable = {
    name: variableName,
    label: targetStep.label,
    defaultValue: targetStep.value
  };

  return {
    ...templatePackage,
    variables: [...templatePackage.variables, variable],
    flow: templatePackage.flow.map((step) =>
      step.id === stepId
        ? {
            ...step,
            variableRef: variableName
          }
        : step
    )
  };
}

export function toDownloadFilename(templatePackage: TemplatePackage): string {
  const safeName = templatePackage.template.name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
  return `${safeName || "template"}-${templatePackage.template.id}.json`;
}

