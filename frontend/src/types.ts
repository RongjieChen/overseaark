export type LanguageCode = "zh" | "en" | "ja";

export type CampaignStageKey =
  | "market_positioning"
  | "buyer_persona"
  | "multilingual_copy"
  | "visual_design"
  | "media_production"
  | "quality_packaging";

export type StageState = "pending" | "running" | "complete" | "partial" | "failed" | "cancelled" | "skipped";

export type CampaignStatus = "idle" | "queued" | "running" | "partial" | "complete" | "failed" | "cancelled";

export interface CampaignFormData {
  name: string;
  description: string;
  sourceMarket: string;
  targetMarkets: string;
  transcription: string;
  targetLanguages: LanguageCode[];
  imageFile: File | null;
}

export interface CampaignCreateResponse {
  id: string;
  status?: CampaignStatus;
  sequence?: number;
  message?: string;
}

export interface CampaignStage {
  key: CampaignStageKey;
  label: string;
  description: string;
  state: StageState;
  detail?: string;
}

export interface Artifact {
  id: string;
  title: string;
  language: LanguageCode;
  kind: "copy" | "brief" | "image_prompt" | "audio" | "export" | "diagnostic";
  content: string;
  quality?: "final" | "partial" | "degraded";
  titleContext?: {
    stage: CampaignStageKey;
    key: string;
    language?: LanguageCode;
  };
}

export interface CampaignDetail {
  id: string;
  status: CampaignStatus;
  sequence: number;
  createdAt?: string;
  updatedAt?: string;
  summary?: string;
  stages: CampaignStage[];
  artifacts: Artifact[];
  warnings: string[];
  error?: string;
}

export interface CampaignEvent {
  sequence: number;
  type: string;
  status?: string;
  campaign?: Partial<CampaignDetail>;
  stage?: (Partial<CampaignStage> & { key: CampaignStageKey }) | CampaignStageKey | string;
  artifact?: Artifact;
  message?: string;
  payload?: unknown;
}

export interface HealthStatus {
  ok: boolean;
  api: "online" | "degraded" | "offline" | "unknown";
  model: "ready" | "warming" | "degraded" | "offline" | "unknown";
  detail: string;
  updatedAt: string;
}
