import type {
  CampaignDetail,
  CampaignEvent,
  CampaignStage,
  CampaignStageKey,
  CampaignStatus,
  HealthStatus,
  LanguageCode,
  StageState,
} from "./types.js";

export const STAGES: readonly Omit<CampaignStage, "state" | "detail">[] = [
  {
    key: "market_positioning",
    label: "Market Positioning",
    description: "Product category, differentiators, region fit, and offer angle defined.",
  },
  {
    key: "buyer_persona",
    label: "Buyer Persona",
    description: "Target buyer motivations, objections, and decision triggers mapped.",
  },
  {
    key: "multilingual_copy",
    label: "Multilingual Copy",
    description: "Chinese, English, and Japanese copy variants generated.",
  },
  {
    key: "visual_design",
    label: "Visual Design",
    description: "Visual direction, layout guidance, and image prompts prepared.",
  },
  {
    key: "media_production",
    label: "Media Production",
    description: "Media-ready captions, scripts, and production notes assembled.",
  },
  {
    key: "quality_packaging",
    label: "Quality Packaging",
    description: "Artifacts checked, warnings surfaced, and export package prepared.",
  },
];

export const LANGUAGE_LABELS: Record<LanguageCode, string> = {
  zh: "中文",
  en: "English",
  ja: "日本語",
};

export function createEmptyCampaign(): CampaignDetail {
  return {
    id: "",
    status: "idle",
    sequence: 0,
    stages: STAGES.map((stage) => ({ ...stage, state: "pending" })),
    artifacts: [],
    warnings: [],
  };
}

export function validateDescription(value: string): string | null {
  const length = value.trim().length;

  if (length < 5) {
    return "Description must contain at least 5 characters.";
  }

  if (length > 2000) {
    return "Description must be 2000 characters or fewer.";
  }

  return null;
}

export function validateProductImage(file: File | null): string | null {
  if (!file) {
    return "Product image is required.";
  }

  const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
  if (!allowedTypes.has(file.type)) {
    return "Product image must be JPG, PNG, or WebP.";
  }

  if (file.size > 20 * 1024 * 1024) {
    return "Product image must be 20MB or smaller.";
  }

  return null;
}

export function statusTone(status: CampaignStatus | StageState): "neutral" | "good" | "warn" | "bad" | "active" {
  if (status === "complete" || status === "skipped") {
    return "good";
  }

  if (status === "partial") {
    return "warn";
  }

  if (status === "failed" || status === "cancelled") {
    return "bad";
  }

  if (status === "running" || status === "queued") {
    return "active";
  }

  return "neutral";
}

export function mergeCampaignEvent(current: CampaignDetail, event: CampaignEvent): CampaignDetail {
  const next: CampaignDetail = {
    ...current,
    sequence: Math.max(current.sequence, event.sequence),
    stages: current.stages.map((stage) => ({ ...stage })),
    artifacts: [...current.artifacts],
    warnings: [...current.warnings],
  };

  if (event.campaign) {
    Object.assign(next, event.campaign);
    next.stages = event.campaign.stages ? [...event.campaign.stages] : next.stages;
    next.artifacts = event.campaign.artifacts ? [...event.campaign.artifacts] : next.artifacts;
    next.warnings = event.campaign.warnings ? [...event.campaign.warnings] : next.warnings;
  }

  if (event.stage) {
    const eventStage = normalizeEventStage(event.stage, event.status, event.message);
    const index = next.stages.findIndex((stage) => stage.key === eventStage.key);
    const mergedStage = {
      ...(index >= 0 ? next.stages[index] : fallbackStage(eventStage.key)),
      ...eventStage,
    } as CampaignStage;

    if (index >= 0) {
      next.stages[index] = mergedStage;
    } else {
      next.stages.push(mergedStage);
    }
  }

  if (event.artifact) {
    const index = next.artifacts.findIndex((artifact) => artifact.id === event.artifact?.id);
    if (index >= 0) {
      next.artifacts[index] = event.artifact;
    } else {
      next.artifacts.push(event.artifact);
    }
  }

  if (event.type === "warning" && event.message && !next.warnings.includes(event.message)) {
    next.warnings.push(event.message);
  }

  if (event.status) {
    next.status = normalizeCampaignStatus(event.status);
  }

  if (event.type.includes("error") || event.type.includes("failed")) {
    next.status = "failed";
    next.error = event.message ?? next.error;
  }

  return next;
}

function fallbackStage(key: CampaignStageKey): CampaignStage {
  const template = STAGES.find((stage) => stage.key === key);

  return {
    key,
    label: template?.label ?? key,
    description: template?.description ?? "",
    state: "pending",
  };
}

export function createConnectionFailureCampaign(reason: string): CampaignDetail {
  return {
    ...createEmptyCampaign(),
    status: "failed",
    sequence: 0,
    summary: "Campaign creation did not reach the backend.",
    stages: STAGES.map((stage, index) => ({
      ...stage,
      state: index === 0 ? "failed" : "pending",
      detail: index === 0 ? reason : undefined,
    })),
    artifacts: [],
    warnings: [],
    error: reason,
  };
}

export function normalizeCampaignStatus(value: unknown): CampaignStatus {
  const status = String(value ?? "idle").toLowerCase();

  if (status === "completed" || status === "succeeded" || status === "success") {
    return "complete";
  }

  if (["queued", "running", "partial", "complete", "failed", "cancelled", "idle"].includes(status)) {
    return status as CampaignStatus;
  }

  return "partial";
}

export function normalizeStageState(value: unknown): StageState {
  const status = String(value ?? "pending").toLowerCase();

  if (status === "completed" || status === "succeeded" || status === "success") {
    return "complete";
  }

  if (["pending", "running", "complete", "partial", "failed", "cancelled", "skipped"].includes(status)) {
    return status as StageState;
  }

  return "partial";
}

export function normalizeStageKey(value: unknown): CampaignStageKey | null {
  if (typeof value !== "string") {
    return null;
  }

  return STAGES.some((stage) => stage.key === value) ? (value as CampaignStageKey) : null;
}

function normalizeEventStage(
  value: CampaignEvent["stage"],
  status: unknown,
  message: string | undefined,
): CampaignStage {
  if (!value) {
    return {
      ...fallbackStage("market_positioning"),
      state: normalizeStageState(status),
      detail: message,
    };
  }

  if (typeof value === "string") {
    const key = normalizeStageKey(value) ?? "market_positioning";
    return {
      ...fallbackStage(key),
      state: normalizeStageState(status),
      detail: message,
    };
  }

  return {
    ...fallbackStage(value.key),
    ...value,
    state: normalizeStageState(value.state ?? status),
    detail: value.detail ?? message,
  };
}

export function formatDateTime(value?: string): string {
  if (!value) {
    return "Not available";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function normalizeHealth(payload: unknown): HealthStatus {
  if (!payload || typeof payload !== "object") {
    return offlineHealth("Health endpoint returned an invalid response.");
  }

  const record = payload as Record<string, unknown>;
  const ok = Boolean(record.ok ?? record.healthy ?? record.status === "ok");
  const modelValue = String(record.modelStatus ?? record.model_status ?? record.model ?? "unknown");
  const apiValue = ok ? "online" : String(record.status ?? "degraded");

  return {
    ok,
    api: normalizeAvailability(apiValue),
    model: normalizeModel(modelValue),
    detail: String(record.detail ?? record.message ?? (ok ? "API reachable" : "Service is degraded")),
    updatedAt: new Date().toISOString(),
  };
}

export function offlineHealth(detail: string): HealthStatus {
  return {
    ok: false,
    api: "offline",
    model: "unknown",
    detail,
    updatedAt: new Date().toISOString(),
  };
}

function normalizeAvailability(value: string): HealthStatus["api"] {
  if (value === "online" || value === "ok" || value === "ready") {
    return "online";
  }

  if (value === "degraded" || value === "partial") {
    return "degraded";
  }

  if (value === "offline" || value === "failed") {
    return "offline";
  }

  return "unknown";
}

function normalizeModel(value: string): HealthStatus["model"] {
  if (value === "ready" || value === "online" || value === "ok") {
    return "ready";
  }

  if (value === "warming" || value === "loading") {
    return "warming";
  }

  if (value === "degraded" || value === "partial") {
    return "degraded";
  }

  if (value === "offline" || value === "failed") {
    return "offline";
  }

  return "unknown";
}
