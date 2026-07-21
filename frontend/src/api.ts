import {
  STAGES,
  createConnectionFailureCampaign,
  normalizeHealth,
  normalizeCampaignStatus,
  normalizeStageKey,
  normalizeStageState,
  offlineHealth,
} from "./campaign.js";
import type {
  CampaignCreateResponse,
  CampaignDetail,
  CampaignEvent,
  CampaignFormData,
  HealthStatus,
} from "./types.js";

const DEFAULT_API_BASE = "/api/v1";

export interface ProgressStream {
  close: () => void;
}

export class ApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async getHealth(): Promise<HealthStatus> {
    try {
      const response = await fetch(`${this.baseUrl}/health`, {
        headers: { Accept: "application/json" },
      });

      if (!response.ok) {
        return offlineHealth(`Health check failed with HTTP ${response.status}.`);
      }

      return normalizeHealth(await response.json());
    } catch (error) {
      return offlineHealth(error instanceof Error ? error.message : "Health check failed.");
    }
  }

  async createCampaign(form: CampaignFormData): Promise<CampaignCreateResponse> {
    const body = new FormData();
    body.set("name", form.name.trim());
    body.set("description", form.description.trim());
    body.set("source_market", form.sourceMarket.trim());
    body.set("target_markets", splitMarkets(form.targetMarkets).join(","));
    body.set("languages", form.targetLanguages.join(","));

    if (form.transcription.trim()) {
      body.set("audio_transcription", form.transcription.trim());
    }

    if (form.imageFile) {
      body.set("product_image", form.imageFile);
    }

    const response = await fetch(`${this.baseUrl}/campaigns`, {
      method: "POST",
      body,
    });

    if (!response.ok) {
      throw new Error(`Campaign creation failed with HTTP ${response.status}.`);
    }

    return normalizeCreateResponse(await response.json());
  }

  async getCampaign(id: string): Promise<CampaignDetail> {
    const response = await fetch(`${this.baseUrl}/campaigns/${encodeURIComponent(id)}`, {
      headers: { Accept: "application/json" },
    });

    if (!response.ok) {
      throw new Error(`Campaign detail failed with HTTP ${response.status}.`);
    }

    return normalizeCampaignDetail(await response.json());
  }

  async rerunCampaign(id: string, stage: string): Promise<CampaignCreateResponse> {
    const response = await fetch(
      `${this.baseUrl}/campaigns/${encodeURIComponent(id)}/rerun/${encodeURIComponent(stage)}`,
      {
        method: "POST",
        headers: { Accept: "application/json" },
      },
    );

    if (!response.ok) {
      throw new Error(`Campaign rerun failed with HTTP ${response.status}.`);
    }

    return normalizeCreateResponse(await response.json());
  }

  async cancelCampaign(id: string): Promise<CampaignCreateResponse> {
    return this.postAction(id, "cancel");
  }

  async exportCampaign(id: string): Promise<Blob> {
    const response = await fetch(`${this.baseUrl}/campaigns/${encodeURIComponent(id)}/export`);

    if (!response.ok) {
      throw new Error(`Campaign export failed with HTTP ${response.status}.`);
    }

    return response.blob();
  }

  streamCampaign(
    id: string,
    lastSequence: number,
    onEvent: (event: CampaignEvent) => void,
    onError: (message: string) => void,
  ): ProgressStream | null {
    if (!("EventSource" in window)) {
      onError("This browser does not support resumable progress streaming.");
      return null;
    }

    const params = new URLSearchParams();
    if (lastSequence > 0) {
      params.set("last_sequence", String(lastSequence));
    }

    const suffix = params.toString() ? `?${params.toString()}` : "";
    const streamUrl = `${this.baseUrl}/campaigns/${encodeURIComponent(id)}/events${suffix}`;

    if (lastSequence > 0 && "fetch" in window && "ReadableStream" in window) {
      const controller = new AbortController();
      void this.streamCampaignWithFetch(streamUrl, lastSequence, controller.signal, onEvent, onError);
      return { close: () => controller.abort() };
    }

    const source = new EventSource(streamUrl);

    source.onmessage = (message) => {
      try {
        onEvent(JSON.parse(message.data) as CampaignEvent);
      } catch {
        onError("Received an unreadable progress update.");
      }
    };

    source.addEventListener("campaign", (message) => {
      try {
        onEvent(JSON.parse((message as MessageEvent<string>).data) as CampaignEvent);
      } catch {
        onError("Received an unreadable campaign update.");
      }
    });

    source.onerror = () => {
      onError("Progress stream interrupted. Reconnect will resume from the latest sequence.");
      source.close();
    };

    return source;
  }

  createConnectionFailure(reason: string): CampaignDetail {
    return createConnectionFailureCampaign(reason);
  }

  private async postAction(id: string, action: "rerun" | "cancel"): Promise<CampaignCreateResponse> {
    const response = await fetch(`${this.baseUrl}/campaigns/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });

    if (!response.ok) {
      throw new Error(`Campaign ${action} failed with HTTP ${response.status}.`);
    }

    return normalizeCreateResponse(await response.json());
  }

  private async streamCampaignWithFetch(
    streamUrl: string,
    lastSequence: number,
    signal: AbortSignal,
    onEvent: (event: CampaignEvent) => void,
    onError: (message: string) => void,
  ): Promise<void> {
    try {
      const response = await fetch(streamUrl, {
        headers: {
          Accept: "text/event-stream",
          "Last-Event-ID": String(lastSequence),
        },
        signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`Progress stream failed with HTTP ${response.status}.`);
      }

      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";

      for (;;) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += value;
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";
        chunks.forEach((chunk) => parseSseChunk(chunk, onEvent));
      }
    } catch (error) {
      if (signal.aborted) {
        return;
      }

      onError(error instanceof Error ? error.message : "Progress stream interrupted.");
    }
  }
}

export function normalizeCreateResponse(payload: unknown): CampaignCreateResponse {
  const record = asRecord(payload);

  return {
    id: String(record.id ?? record.campaign_id ?? ""),
    status: normalizeCampaignStatus(record.status),
    sequence: Number(record.sequence ?? record.last_sequence ?? 0),
    message: typeof record.message === "string" ? record.message : undefined,
  };
}

export function normalizeCampaignDetail(payload: unknown): CampaignDetail {
  const record = asRecord(payload);
  const rawStages = Array.isArray(record.stages) ? record.stages : [];
  const rawArtifacts = normalizeRawArtifacts(record.artifacts);
  const rawWarnings = Array.isArray(record.warnings) ? record.warnings : [];

  return {
    id: String(record.id ?? record.campaign_id ?? ""),
    status: normalizeCampaignStatus(record.status),
    sequence: Number(record.sequence ?? record.last_sequence ?? 0),
    createdAt: stringOrUndefined(record.created_at ?? record.createdAt),
    updatedAt: stringOrUndefined(record.updated_at ?? record.updatedAt),
    summary: stringOrUndefined(record.summary),
    stages: STAGES.map((stage) => {
      const raw = rawStages
        .map(asRecord)
        .find((candidate) => (candidate.key ?? candidate.stage ?? candidate.name) === stage.key);
      return {
        ...stage,
        state: normalizeStageState(raw?.state ?? raw?.status),
        detail: stringOrUndefined(raw?.detail ?? raw?.message),
      };
    }),
    artifacts: rawArtifacts.map((artifact, index) => {
      const raw = asRecord(artifact);
      return {
        id: String(raw.id ?? `artifact-${index}`),
        title: String(raw.title ?? raw.name ?? "Artifact"),
        language: normalizeLanguage(raw.language),
        kind: normalizeArtifactKind(raw.kind ?? raw.type),
        content: String(raw.content ?? raw.text ?? ""),
        quality: normalizeArtifactQuality(raw.quality ?? raw.status),
      };
    }),
    warnings: rawWarnings.map(String),
    error: stringOrUndefined(record.error ?? record.error_message),
  };
}

function normalizeRawArtifacts(value: unknown): unknown[] {
  if (Array.isArray(value)) {
    return value;
  }

  const record = asRecord(value);
  return Object.entries(record).flatMap(([stage, artifact]) => {
    if (Array.isArray(artifact)) {
      return artifact.map((entry) => ({ ...asRecord(entry), stage }));
    }

    const raw = asRecord(artifact);
    if (Object.keys(raw).length === 0) {
      return [];
    }

    return expandStageArtifact(stage, raw);
  });
}

function expandStageArtifact(stage: string, raw: Record<string, unknown>): unknown[] {
  const explicitArtifacts = Array.isArray(raw.artifacts) ? raw.artifacts.map((entry) => ({ ...asRecord(entry), stage })) : [];
  const generatedArtifacts = Object.entries(raw).flatMap(([key, value]) => {
    if (key === "artifacts" || value == null) {
      return [];
    }

    if (typeof value === "object" && !Array.isArray(value)) {
      const nested = asRecord(value);
      return Object.entries(nested).map(([nestedKey, nestedValue]) => ({
        id: `${stage}-${key}-${nestedKey}`,
        title: artifactTitle(stage, key, nestedKey),
        language: nestedKey,
        kind: artifactKindFromKey(key),
        content: stringifyArtifactContent(nestedValue),
      }));
    }

    return [
      {
        id: `${stage}-${key}`,
        title: artifactTitle(stage, key),
        language: inferLanguage(raw.language),
        kind: artifactKindFromKey(key),
        content: stringifyArtifactContent(value),
      },
    ];
  });

  return [...explicitArtifacts, ...generatedArtifacts];
}

function artifactTitle(stage: string, key: string, language?: string): string {
  const stageKey = normalizeStageKey(stage);
  const stageLabel = STAGES.find((item) => item.key === stageKey)?.label ?? stage;
  const suffix = language ? ` ${language.toUpperCase()}` : "";
  return `${stageLabel} ${key.replaceAll("_", " ")}${suffix}`;
}

function artifactKindFromKey(key: string): "copy" | "brief" | "image_prompt" | "audio" | "export" | "diagnostic" {
  if (key.includes("poster") || key.includes("visual") || key.includes("prompt")) {
    return "image_prompt";
  }

  if (key.includes("wav") || key.includes("audio")) {
    return "audio";
  }

  if (key.includes("video")) {
    return "export";
  }

  if (key.includes("qc") || key.includes("quality")) {
    return "diagnostic";
  }

  if (key.includes("brief")) {
    return "brief";
  }

  return "copy";
}

function stringifyArtifactContent(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  return JSON.stringify(value, null, 2);
}

function splitMarkets(value: string): string[] {
  return value
    .split(",")
    .map((market) => market.trim())
    .filter(Boolean);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function stringOrUndefined(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function normalizeLanguage(value: unknown): "zh" | "en" | "ja" {
  return value === "zh" || value === "ja" ? value : "en";
}

function inferLanguage(value: unknown): "zh" | "en" | "ja" {
  return normalizeLanguage(value);
}

function normalizeArtifactKind(value: unknown): "copy" | "brief" | "image_prompt" | "audio" | "export" | "diagnostic" {
  if (value === "brief" || value === "image_prompt" || value === "audio" || value === "export" || value === "diagnostic") {
    return value;
  }

  return "copy";
}

function normalizeArtifactQuality(value: unknown): "final" | "partial" | "degraded" {
  if (value === "partial" || value === "degraded") {
    return value;
  }

  return "final";
}

function parseSseChunk(chunk: string, onEvent: (event: CampaignEvent) => void): void {
  const data = chunk
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim())
    .join("\n");

  if (!data) {
    return;
  }

  onEvent(JSON.parse(data) as CampaignEvent);
}
