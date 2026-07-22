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
  Artifact,
  CampaignCreateResponse,
  CampaignDetail,
  CampaignEvent,
  CampaignFormData,
  CampaignStage,
  HealthStatus,
  LanguageCode,
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

  assetUrl(id: string, assetKey: NonNullable<Artifact["assetKey"]>): string {
    return buildCampaignAssetUrl(this.baseUrl, id, assetKey);
  }

  async exportCampaign(id: string, language?: LanguageCode): Promise<Blob> {
    const response = await fetch(buildCampaignExportUrl(this.baseUrl, id, language));

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
        onEvent(normalizeCampaignEvent(JSON.parse(message.data)));
      } catch {
        onError("Received an unreadable progress update.");
      }
    };

    source.addEventListener("campaign", (message) => {
      try {
        onEvent(normalizeCampaignEvent(JSON.parse((message as MessageEvent<string>).data)));
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

  createConnectionFailure(reason: string, summary?: string): CampaignDetail {
    return createConnectionFailureCampaign(reason, summary);
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
    artifacts: normalizeArtifacts(rawArtifacts),
    warnings: rawWarnings.map(String),
    error: stringOrUndefined(record.error ?? record.error_message),
  };
}

export function normalizeCampaignEvent(payload: unknown): CampaignEvent {
  const record = asRecord(payload);
  const type = String(record.type ?? "campaign.update");
  const message = stringOrUndefined(record.message);
  const stageKey = normalizeStageKey(record.stage) ?? normalizeStageKey(asRecord(record.stage).key);
  const eventPayload = asRecord(record.payload);
  const stageOutput = Object.hasOwn(eventPayload, "output")
    ? asRecord(eventPayload.output)
    : eventPayload;
  const artifacts = stageKey && type === "stage.succeeded"
    ? normalizeArtifacts(normalizeRawArtifacts({ [stageKey]: stageOutput }))
    : [];
  const stageState = stageStateFromEventType(type);

  return {
    sequence: normalizeSequence(record.sequence),
    type,
    status: stringOrUndefined(record.status),
    campaign: normalizeEventCampaign(record.campaign),
    stage: stageKey
      ? {
          key: stageKey,
          ...(stageState ? { state: stageState } : {}),
          ...(message ? { detail: message } : {}),
        }
      : undefined,
    artifact: normalizeEventArtifact(record.artifact),
    artifacts: artifacts.length > 0 ? artifacts : undefined,
    message,
    payload: eventPayload,
  };
}

function normalizeArtifacts(rawArtifacts: unknown[]): Artifact[] {
  return rawArtifacts.map((artifact, index) => {
    const raw = asRecord(artifact);
    const stage = normalizeStageKey(raw.stage ?? raw.title_context_stage) ?? "market_positioning";
    const key = normalizeArtifactKey(raw.key ?? raw.title_context_key ?? raw.name ?? "");
    const language = normalizeOptionalLanguage(raw.language);
    const kind = normalizeArtifactKind(raw.kind ?? raw.type ?? artifactKindFromKey(key));
    return {
      id: String(raw.id ?? `artifact-${index}`),
      title: String(raw.title ?? raw.name ?? "Artifact"),
      stage,
      key,
      language,
      kind,
      content: String(raw.content ?? raw.text ?? ""),
      assetKey: normalizeAssetKey(raw.asset_key ?? raw.assetKey) ?? assetKeyForArtifact(stage, key, language, kind),
      quality: normalizeArtifactQuality(raw.quality ?? raw.status),
      titleContext: normalizeArtifactTitleContext(raw.title_context, stage, key, language),
    };
  });
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
  const explicitArtifacts = Array.isArray(raw.artifacts) ? raw.artifacts.map((entry) => normalizeExplicitArtifact(stage, entry)) : [];
  const generatedArtifacts: unknown[] = [];
  Object.entries(raw).forEach(([key, value]) => {
    if (key === "artifacts" || value == null) {
      return;
    }

    if (isLanguageMapArtifact(value)) {
      const nested = asRecord(value);
      Object.entries(nested).forEach(([nestedKey, nestedValue]) => {
        generatedArtifacts.push({
          id: `${stage}-${key}-${nestedKey}`,
          title: artifactTitle(stage, key, nestedKey),
          stage,
          key,
          language: nestedKey,
          kind: artifactKindFromKey(key),
          content: stringifyArtifactContent(nestedValue),
          title_context: { stage, key, language: nestedKey },
        });
      });
      return;
    }

    generatedArtifacts.push({
      id: `${stage}-${key}`,
      title: artifactTitle(stage, key),
      stage,
      key,
      language: inferLanguageFromKey(key, raw.language),
      kind: artifactKindFromKey(key),
      content: stringifyArtifactContent(value),
      title_context: { stage, key, language: "" },
    });
  });

  return [...explicitArtifacts, ...generatedArtifacts];
}

function normalizeExplicitArtifact(stage: string, value: unknown): Record<string, unknown> {
  const raw = asRecord(value);
  const key = normalizeArtifactKey(raw.key ?? raw.name ?? raw.title_context_key ?? "");
  return {
    ...raw,
    stage: raw.stage ?? stage,
    key,
    language: raw.language ?? inferLanguageFromKey(key),
  };
}

function isLanguageMapArtifact(value: unknown): boolean {
  if (typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const nested = asRecord(value);
  const nestedKeys = Object.keys(nested);
  return nestedKeys.length > 0 && nestedKeys.every((nestedKey) => normalizeOptionalLanguage(nestedKey));
}

function artifactTitle(stage: string, key: string, language?: string): string {
  const stageKey = normalizeStageKey(stage);
  const stageLabel = STAGES.find((item) => item.key === stageKey)?.label ?? stage;
  const suffix = language ? ` ${language.toUpperCase()}` : "";
  return `${stageLabel} ${key.replaceAll("_", " ")}${suffix}`;
}

function artifactKindFromKey(key: string): Artifact["kind"] {
  if (key.includes("poster") || key.includes("image_path")) {
    return "poster";
  }

  if (key.includes("visual") || key.includes("prompt")) {
    return "image_prompt";
  }

  if (key.includes("wav") || key.includes("audio")) {
    return "audio";
  }

  if (key.includes("video")) {
    return "video";
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

export function splitMarkets(value: string): string[] {
  return value
    .split(/[,，、]/u)
    .map((market) => market.trim())
    .filter(Boolean);
}

export function buildCampaignAssetUrl(
  baseUrl: string,
  campaignId: string,
  assetKey: NonNullable<Artifact["assetKey"]>,
): string {
  return `${baseUrl.replace(/\/$/, "")}/campaigns/${encodeURIComponent(campaignId)}/assets/${encodeURIComponent(assetKey)}`;
}

export function buildCampaignExportUrl(baseUrl: string, campaignId: string, language?: LanguageCode): string {
  const url = `${baseUrl.replace(/\/$/, "")}/campaigns/${encodeURIComponent(campaignId)}/export`;
  return language ? `${url}?language=${encodeURIComponent(language)}` : url;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function normalizeSequence(value: unknown): number {
  const sequence = Number(value);
  return Number.isSafeInteger(sequence) && sequence >= 0 ? sequence : 0;
}

function stageStateFromEventType(type: string): CampaignStage["state"] | undefined {
  if (type === "stage.succeeded" || type === "stage.completed") {
    return "complete";
  }

  if (type === "stage.failed") {
    return "failed";
  }

  if (type === "stage.skipped") {
    return "skipped";
  }

  if (type === "stage.started" || type === "stage.running" || type === "stage.retry") {
    return "running";
  }

  return undefined;
}

function normalizeEventCampaign(value: unknown): Partial<CampaignDetail> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }

  return value as Partial<CampaignDetail>;
}

function normalizeEventArtifact(value: unknown): Artifact | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }

  return normalizeArtifacts([value])[0];
}

function stringOrUndefined(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function normalizeOptionalLanguage(value: unknown): LanguageCode | undefined {
  return value === "zh" || value === "en" || value === "ja" ? value : undefined;
}

function inferLanguageFromKey(key: string, fallback?: unknown): LanguageCode | undefined {
  const fallbackLanguage = normalizeOptionalLanguage(fallback);
  if (fallbackLanguage) {
    return fallbackLanguage;
  }

  const match = /(?:^|[_-])(zh|en|ja)(?:$|[_-])/u.exec(key);
  return normalizeOptionalLanguage(match?.[1]);
}

function normalizeArtifactKind(value: unknown): Artifact["kind"] {
  if (
    value === "brief" ||
    value === "image_prompt" ||
    value === "poster" ||
    value === "audio" ||
    value === "video" ||
    value === "export" ||
    value === "diagnostic"
  ) {
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

function normalizeArtifactKey(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "artifact";
}

function normalizeAssetKey(value: unknown): Artifact["assetKey"] {
  if (
    value === "source" ||
    value === "poster" ||
    value === "video" ||
    value === "audio-zh" ||
    value === "audio-en" ||
    value === "audio-ja" ||
    value === "qc"
  ) {
    return value;
  }

  return undefined;
}

function assetKeyForArtifact(
  stage: Artifact["stage"],
  key: string,
  language: Artifact["language"],
  kind: Artifact["kind"],
): Artifact["assetKey"] {
  if (stage === "visual_design" && kind === "poster") {
    return "poster";
  }

  if (stage === "media_production" && kind === "audio" && language) {
    return `audio-${language}`;
  }

  if (stage === "media_production" && kind === "video") {
    return "video";
  }

  if (stage === "quality_packaging" && (key.includes("qc") || kind === "diagnostic")) {
    return "qc";
  }

  return undefined;
}

function normalizeArtifactTitleContext(
  value: unknown,
  fallbackStage: Artifact["stage"],
  fallbackKey: string,
  fallbackLanguage: Artifact["language"],
): Artifact["titleContext"] {
  const record = asRecord(value);
  const stage = normalizeStageKey(record.stage) ?? fallbackStage;
  const key = normalizeArtifactKey(record.key ?? fallbackKey);
  if (!stage || !key) {
    return undefined;
  }

  const language = normalizeOptionalLanguage(record.language) ?? fallbackLanguage;
  return { stage, key, language };
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

  onEvent(normalizeCampaignEvent(JSON.parse(data)));
}
