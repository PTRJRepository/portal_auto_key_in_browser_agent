import type { FlowStep, StepType, TemplatePackage } from "@template/flow-schema";

export type RawBrowserEvent =
  | {
      kind: "click";
      selector: string;
      fallback?: {
        text?: string;
        tag?: string;
      };
      url: string;
    }
  | {
      kind: "input";
      selector: string;
      value: string;
      inputType?: string;
      url: string;
    }
  | {
      kind: "change";
      selector: string;
      value: string;
      inputType?: string;
      checked?: boolean;
      url: string;
    }
  | {
      kind: "keydown";
      key: string;
      url: string;
    }
  | {
      kind: "navigation";
      url: string;
    };

export type AgentEvent =
  | {
      type: "recording.started";
      payload: {
        sessionId: string;
        url: string;
      };
    }
  | {
      type: "recording.flowPreview";
      payload: {
        sessionId: string;
        entryUrl: string;
        flow: FlowStep[];
      };
    }
  | {
      type: "recording.event";
      payload: {
        sessionId: string;
        event: RawBrowserEvent;
      };
    }
  | {
      type: "recording.stopped";
      payload: {
        sessionId: string;
        templateId: string;
      };
    }
  | {
      type: "recording.browserClosed";
      payload: {
        sessionId: string;
      };
    }
  | {
      type: "run.started";
      payload: {
        runId: string;
        templateId: string;
      };
    }
  | {
      type: "run.step";
      payload: {
        runId: string;
        stepId: string;
        stepType: StepType;
        status: "success" | "failed" | "skipped";
        message?: string;
      };
    }
  | {
      type: "run.completed";
      payload: {
        runId: string;
        templateId: string;
        status: "success" | "failed";
        failedStepId?: string;
        message?: string;
        fidelityScorePercent?: number;
        exactMatch?: boolean;
      };
    };

export type StoredTemplate = {
  template: TemplatePackage;
  filename: string;
};

export type StepDraft = Omit<FlowStep, "type"> & {
  type: StepType;
};
