import type { Artifact, CampaignStageKey, CampaignStatus, HealthStatus, LanguageCode, StageState } from "./types.js";

export type Locale = "zh-CN" | "en";

export type StreamMessageKey =
  | "noActiveStream"
  | "restoredCampaign"
  | "restoreFailedWithDetail"
  | "restoreFailed"
  | "creatingCampaign"
  | "campaignCreated"
  | "campaignCreationFailed"
  | "connectionFailed"
  | "loadingDetail"
  | "detailLoaded"
  | "detailFailed"
  | "detailUnavailable"
  | "requestingRerun"
  | "rerunFailed"
  | "campaignCancelled"
  | "cancelFailed"
  | "exportFailed"
  | "progressUpdate"
  | "detailRefreshed"
  | "detailRefreshFailed";

export type StreamMessageState =
  | { kind: "localized"; key: StreamMessageKey; campaignId?: string; sequence?: number; message?: string }
  | { kind: "raw"; text: string };

export interface ValidationMessages {
  descriptionTooShort: string;
  descriptionTooLong: string;
  imageRequired: string;
  imageType: string;
  imageTooLarge: string;
}

export const LOCALE_STORAGE_KEY = "overseaark.locale";

interface BrowserStorageHost {
  readonly localStorage: Pick<Storage, "getItem" | "setItem" | "removeItem">;
}

const localeLabels: Record<Locale, string> = {
  "zh-CN": "中文",
  en: "English",
};

const languageLabels: Record<Locale, Record<LanguageCode, string>> = {
  "zh-CN": {
    zh: "中文",
    en: "英语",
    ja: "日语",
  },
  en: {
    zh: "Chinese",
    en: "English",
    ja: "Japanese",
  },
};

const stageText: Record<Locale, Record<CampaignStageKey, { label: string; description: string }>> = {
  "zh-CN": {
    market_positioning: {
      label: "市场定位",
      description: "明确产品类别、差异化卖点、区域适配度和报价切入点。",
    },
    buyer_persona: {
      label: "买家画像",
      description: "梳理目标买家的购买动机、疑虑和决策触发因素。",
    },
    multilingual_copy: {
      label: "多语文案",
      description: "生成中文、英文和日语的本地化营销文案。",
    },
    visual_design: {
      label: "视觉设计",
      description: "准备视觉方向、版式建议和产品图编辑提示词。",
    },
    media_production: {
      label: "音视频制作",
      description: "组合配音、字幕、脚本和视频生产素材。",
    },
    quality_packaging: {
      label: "质量与打包",
      description: "检查产物、暴露风险并生成可下载交付包。",
    },
  },
  en: {
    market_positioning: {
      label: "Market Positioning",
      description: "Product category, differentiators, region fit, and offer angle defined.",
    },
    buyer_persona: {
      label: "Buyer Persona",
      description: "Target buyer motivations, objections, and decision triggers mapped.",
    },
    multilingual_copy: {
      label: "Multilingual Copy",
      description: "Chinese, English, and Japanese copy variants generated.",
    },
    visual_design: {
      label: "Visual Design",
      description: "Visual direction, layout guidance, and image prompts prepared.",
    },
    media_production: {
      label: "Media Production",
      description: "Media-ready captions, scripts, and production notes assembled.",
    },
    quality_packaging: {
      label: "Quality Packaging",
      description: "Artifacts checked, warnings surfaced, and export package prepared.",
    },
  },
};

const statusText: Record<Locale, Record<CampaignStatus | StageState, string>> = {
  "zh-CN": {
    idle: "未选择",
    queued: "排队中",
    running: "运行中",
    pending: "待处理",
    complete: "已完成",
    partial: "部分完成",
    failed: "失败",
    cancelled: "已取消",
    skipped: "已跳过",
  },
  en: {
    idle: "Idle",
    queued: "Queued",
    running: "Running",
    pending: "Pending",
    complete: "Complete",
    partial: "Partial",
    failed: "Failed",
    cancelled: "Cancelled",
    skipped: "Skipped",
  },
};

const apiStatusText: Record<Locale, Record<HealthStatus["api"], string>> = {
  "zh-CN": {
    online: "在线",
    degraded: "降级",
    offline: "离线",
    unknown: "未知",
  },
  en: {
    online: "Online",
    degraded: "Degraded",
    offline: "Offline",
    unknown: "Unknown",
  },
};

const modelStatusText: Record<Locale, Record<HealthStatus["model"], string>> = {
  "zh-CN": {
    ready: "就绪",
    warming: "加载中",
    degraded: "降级",
    offline: "离线",
    unknown: "未知",
  },
  en: {
    ready: "Ready",
    warming: "Warming",
    degraded: "Degraded",
    offline: "Offline",
    unknown: "Unknown",
  },
};

const artifactKindText: Record<Locale, Record<Artifact["kind"], string>> = {
  "zh-CN": {
    copy: "文案",
    brief: "简报",
    image_prompt: "视觉提示词",
    audio: "音频",
    export: "导出",
    diagnostic: "诊断",
  },
  en: {
    copy: "Copy",
    brief: "Brief",
    image_prompt: "Image prompt",
    audio: "Audio",
    export: "Export",
    diagnostic: "Diagnostic",
  },
};

const qualityText: Record<Locale, Record<NonNullable<Artifact["quality"]>, string>> = {
  "zh-CN": {
    final: "最终版",
    partial: "部分产物",
    degraded: "降级产物",
  },
  en: {
    final: "Final",
    partial: "Partial",
    degraded: "Degraded",
  },
};

const artifactTitleKeyText: Record<Locale, Record<string, string>> = {
  "zh-CN": {
    copy: "文案",
    poster: "海报",
    visual: "视觉方案",
    prompt: "提示词",
    wav_zh: "中文音频",
    wav_en: "英语音频",
    wav_ja: "日语音频",
    audio: "音频",
    video: "视频",
    qc_report: "质检报告",
    quality_report: "质量报告",
    export_package: "导出包",
  },
  en: {
    copy: "Copy",
    poster: "Poster",
    visual: "Visual direction",
    prompt: "Prompt",
    wav_zh: "Chinese audio",
    wav_en: "English audio",
    wav_ja: "Japanese audio",
    audio: "Audio",
    video: "Video",
    qc_report: "QC report",
    quality_report: "Quality report",
    export_package: "Export package",
  },
};

export const validationMessages: Record<Locale, ValidationMessages> = {
  "zh-CN": {
    descriptionTooShort: "产品描述至少需要 5 个字符。",
    descriptionTooLong: "产品描述不能超过 2000 个字符。",
    imageRequired: "请上传产品图片。",
    imageType: "产品图片必须是 JPG、PNG 或 WebP 格式。",
    imageTooLarge: "产品图片不能超过 20MB。",
  },
  en: {
    descriptionTooShort: "Description must contain at least 5 characters.",
    descriptionTooLong: "Description must be 2000 characters or fewer.",
    imageRequired: "Product image is required.",
    imageType: "Product image must be JPG, PNG, or WebP.",
    imageTooLarge: "Product image must be 20MB or smaller.",
  },
};

export const messages = {
  "zh-CN": {
    documentTitle: "OverseaArk 工作台",
    appTitle: "跨境营销活动工作台",
    workspaceLabel: "营销活动工作区",
    detailArtifactsLabel: "活动详情与产物",
    createEyebrow: "创建",
    productCampaign: "产品营销活动",
    refreshAria: "刷新健康和模型状态",
    refreshTitle: "刷新状态",
    languageSwitcherLabel: "界面语言",
    campaignName: "活动名称",
    campaignNamePlaceholder: "NVIDIA Jetson 零售演示套件",
    productImage: "产品图片",
    selectedProductPreview: "已选产品预览",
    uploadImage: "上传图片",
    uploadImageHint: "PNG、JPG 或 WebP 产品图",
    productDescription: "产品描述",
    descriptionPlaceholder: "描述产品功能、受众、价格带、差异化卖点和目标区域。",
    audioTranscription: "音频转写",
    optional: "可选",
    transcriptionPlaceholder: "粘贴语音备忘或会议摘要转写。",
    sourceMarket: "来源市场",
    sourceMarketPlaceholder: "中国大陆",
    targetMarkets: "目标市场",
    targetMarketsPlaceholder: "美国、日本、中国大陆",
    defaultTargetMarkets: "美国,日本,中国大陆",
    outputLanguages: "输出语言",
    createCampaign: "创建活动",
    loadDetail: "加载详情",
    progressEyebrow: "进度",
    pipelineTitle: "六阶段流水线",
    noActiveStream: "暂无活动进度流。",
    stageToRerun: "选择要重跑的阶段",
    rerun: "重跑",
    cancel: "取消",
    export: "导出",
    detailEyebrow: "详情",
    noCampaignSelected: "未选择活动",
    campaign: "活动",
    sequence: "序列",
    created: "创建时间",
    updated: "更新时间",
    notAvailable: "暂无",
    defaultSummary: "后端返回进度和产物后，活动详情会显示在这里。",
    artifactsEyebrow: "产物",
    localizedOutputs: "本地化输出",
    artifactLanguage: "产物语言",
    emptyArtifacts: (language: string) => `还没有 ${language} 产物。`,
    checking: "检查中",
    modelStatusPending: "模型状态待确认",
    api: "API",
    model: "模型",
    restoredCampaign: (campaignId: string) => `已恢复活动 ${campaignId}。`,
    restoreFailedWithDetail: (message: string) => `无法恢复已保存活动：${message}`,
    restoreFailed: "无法恢复已保存活动。",
    creatingCampaign: "正在创建活动...",
    campaignCreated: "活动已创建，正在打开进度流...",
    campaignCreationFailed: "活动创建失败。",
    connectionFailed: "连接后端失败，未创建活动。请检查服务是否已启动。",
    connectionFailureSummary: "活动创建请求未到达后端。",
    loadingDetail: "正在加载活动详情...",
    detailLoaded: "活动详情已加载。",
    detailFailed: "活动详情加载失败。",
    detailUnavailable: "详情暂不可用，已保留现有进度。",
    requestingRerun: "正在请求重跑...",
    rerunFailed: "重跑失败。",
    campaignCancelled: "活动已取消。",
    cancelFailed: "取消失败。",
    exportFailed: "导出失败。",
    progressUpdate: (sequence: number) => `收到进度更新，序列 ${sequence}。`,
    detailRefreshed: (sequence: number) => `活动详情已刷新，序列 ${sequence}。`,
    detailRefreshFailed: "详情刷新失败。",
  },
  en: {
    documentTitle: "OverseaArk Workbench",
    appTitle: "Cross-border campaign workbench",
    workspaceLabel: "Campaign workspace",
    detailArtifactsLabel: "Campaign detail and artifacts",
    createEyebrow: "Create",
    productCampaign: "Product campaign",
    refreshAria: "Refresh health and model status",
    refreshTitle: "Refresh status",
    languageSwitcherLabel: "Interface language",
    campaignName: "Campaign name",
    campaignNamePlaceholder: "NVIDIA Jetson retail demo kit",
    productImage: "Product image",
    selectedProductPreview: "Selected product preview",
    uploadImage: "Upload image",
    uploadImageHint: "PNG, JPG, or WebP product shot",
    productDescription: "Product description",
    descriptionPlaceholder: "Describe product features, audience, price band, differentiators, and target region.",
    audioTranscription: "Audio transcription",
    optional: "optional",
    transcriptionPlaceholder: "Paste voice note transcription or meeting summary.",
    sourceMarket: "Source market",
    sourceMarketPlaceholder: "Mainland China",
    targetMarkets: "Target markets",
    targetMarketsPlaceholder: "United States, Japan, Mainland China",
    defaultTargetMarkets: "United States, Japan, Mainland China",
    outputLanguages: "Output languages",
    createCampaign: "Create campaign",
    loadDetail: "Load detail",
    progressEyebrow: "Progress",
    pipelineTitle: "Six-stage pipeline",
    noActiveStream: "No active stream.",
    stageToRerun: "Stage to rerun",
    rerun: "Rerun",
    cancel: "Cancel",
    export: "Export",
    detailEyebrow: "Detail",
    noCampaignSelected: "No campaign selected",
    campaign: "Campaign",
    sequence: "Seq",
    created: "Created",
    updated: "Updated",
    notAvailable: "Not available",
    defaultSummary: "Campaign details will appear as the backend returns progress and artifacts.",
    artifactsEyebrow: "Artifacts",
    localizedOutputs: "Localized outputs",
    artifactLanguage: "Artifact language",
    emptyArtifacts: (language: string) => `No ${language} artifacts yet.`,
    checking: "Checking",
    modelStatusPending: "Model status pending",
    api: "API",
    model: "Model",
    restoredCampaign: (campaignId: string) => `Restored campaign ${campaignId}.`,
    restoreFailedWithDetail: (message: string) => `Stored campaign could not be restored: ${message}`,
    restoreFailed: "Stored campaign could not be restored.",
    creatingCampaign: "Creating campaign...",
    campaignCreated: "Campaign created. Opening progress stream...",
    campaignCreationFailed: "Campaign creation failed.",
    connectionFailed: "Connection failed. No campaign was created. Check that the backend is running.",
    connectionFailureSummary: "Campaign creation did not reach the backend.",
    loadingDetail: "Loading campaign detail...",
    detailLoaded: "Campaign detail loaded.",
    detailFailed: "Campaign detail failed.",
    detailUnavailable: "Detail unavailable; existing progress is preserved.",
    requestingRerun: "Requesting rerun...",
    rerunFailed: "Rerun failed.",
    campaignCancelled: "Campaign cancelled.",
    cancelFailed: "Cancel failed.",
    exportFailed: "Export failed.",
    progressUpdate: (sequence: number) => `Progress update received at sequence ${sequence}.`,
    detailRefreshed: (sequence: number) => `Campaign detail refreshed at sequence ${sequence}.`,
    detailRefreshFailed: "Detail refresh failed.",
  },
} as const;

const stableErrorPatterns: readonly {
  pattern: RegExp;
  zh: (match: RegExpExecArray) => string;
  en: (match: RegExpExecArray) => string;
}[] = [
  {
    pattern: /^Health check failed with HTTP (\d+)\.$/,
    zh: (match) => `健康检查失败，HTTP ${match[1]}。`,
    en: (match) => `Health check failed with HTTP ${match[1]}.`,
  },
  {
    pattern: /^Health check failed\.$/,
    zh: () => "健康检查失败。",
    en: () => "Health check failed.",
  },
  {
    pattern: /^Health endpoint returned an invalid response\.$/,
    zh: () => "健康接口返回了无效响应。",
    en: () => "Health endpoint returned an invalid response.",
  },
  {
    pattern: /^API reachable$/,
    zh: () => "API 可访问",
    en: () => "API reachable",
  },
  {
    pattern: /^Service is degraded$/,
    zh: () => "服务处于降级状态",
    en: () => "Service is degraded",
  },
  {
    pattern: /^(Failed to fetch|Load failed|NetworkError when attempting to fetch resource\.)$/,
    zh: () => "无法连接服务。",
    en: (match) => match[1],
  },
  {
    pattern: /^Campaign creation failed with HTTP (\d+)\.$/,
    zh: (match) => `活动创建失败，HTTP ${match[1]}。`,
    en: (match) => `Campaign creation failed with HTTP ${match[1]}.`,
  },
  {
    pattern: /^Campaign detail failed with HTTP (\d+)\.$/,
    zh: (match) => `活动详情加载失败，HTTP ${match[1]}。`,
    en: (match) => `Campaign detail failed with HTTP ${match[1]}.`,
  },
  {
    pattern: /^Campaign rerun failed with HTTP (\d+)\.$/,
    zh: (match) => `活动重跑失败，HTTP ${match[1]}。`,
    en: (match) => `Campaign rerun failed with HTTP ${match[1]}.`,
  },
  {
    pattern: /^Campaign export failed with HTTP (\d+)\.$/,
    zh: (match) => `活动导出失败，HTTP ${match[1]}。`,
    en: (match) => `Campaign export failed with HTTP ${match[1]}.`,
  },
  {
    pattern: /^Campaign cancel failed with HTTP (\d+)\.$/,
    zh: (match) => `活动取消失败，HTTP ${match[1]}。`,
    en: (match) => `Campaign cancel failed with HTTP ${match[1]}.`,
  },
  {
    pattern: /^Progress stream failed with HTTP (\d+)\.$/,
    zh: (match) => `进度流连接失败，HTTP ${match[1]}。`,
    en: (match) => `Progress stream failed with HTTP ${match[1]}.`,
  },
  {
    pattern: /^This browser does not support resumable progress streaming\.$/,
    zh: () => "当前浏览器不支持可恢复进度流。",
    en: () => "This browser does not support resumable progress streaming.",
  },
  {
    pattern: /^Received an unreadable progress update\.$/,
    zh: () => "收到无法解析的进度更新。",
    en: () => "Received an unreadable progress update.",
  },
  {
    pattern: /^Received an unreadable campaign update\.$/,
    zh: () => "收到无法解析的活动更新。",
    en: () => "Received an unreadable campaign update.",
  },
  {
    pattern: /^Progress stream interrupted\. Reconnect will resume from the latest sequence\.$/,
    zh: () => "进度流中断，将从最新序列自动重连。",
    en: () => "Progress stream interrupted. Reconnect will resume from the latest sequence.",
  },
];

export function normalizeLocale(value: string | null | undefined): Locale {
  return value === "en" ? "en" : "zh-CN";
}

export function getStoredLocale(storage: Storage): Locale {
  try {
    return normalizeLocale(storage.getItem(LOCALE_STORAGE_KEY));
  } catch {
    return "zh-CN";
  }
}

export function persistLocale(storage: Storage, locale: Locale): void {
  try {
    storage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    // Locale persistence is optional; the language switch must keep working in memory.
  }
}

export function getBrowserLocale(host: BrowserStorageHost): Locale {
  return normalizeLocale(readBrowserStorageItem(host, LOCALE_STORAGE_KEY));
}

export function persistBrowserLocale(host: BrowserStorageHost, locale: Locale): void {
  writeBrowserStorageItem(host, LOCALE_STORAGE_KEY, locale);
}

export function readBrowserStorageItem(host: BrowserStorageHost, key: string): string | null {
  try {
    return host.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeBrowserStorageItem(host: BrowserStorageHost, key: string, value: string): boolean {
  try {
    host.localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function removeBrowserStorageItem(host: BrowserStorageHost, key: string): boolean {
  try {
    host.localStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function localeLabel(locale: Locale): string {
  return localeLabels[locale];
}

export function getLanguageLabels(locale: Locale): Record<LanguageCode, string> {
  return languageLabels[locale];
}

export function getStageText(locale: Locale, key: CampaignStageKey): { label: string; description: string } {
  return stageText[locale][key];
}

export function getStatusText(locale: Locale, status: CampaignStatus | StageState): string {
  return statusText[locale][status];
}

export function getApiStatusText(locale: Locale, status: HealthStatus["api"]): string {
  return apiStatusText[locale][status];
}

export function getModelStatusText(locale: Locale, status: HealthStatus["model"]): string {
  return modelStatusText[locale][status];
}

export function getArtifactKindText(locale: Locale, kind: Artifact["kind"]): string {
  return artifactKindText[locale][kind];
}

export function getQualityText(locale: Locale, quality: NonNullable<Artifact["quality"]>): string {
  return qualityText[locale][quality];
}

export function getArtifactTitle(locale: Locale, artifact: Artifact): string {
  const context = artifact.titleContext;
  if (!context) {
    return artifact.title;
  }

  const stage = getStageText(locale, context.stage).label;
  const key = artifactTitleKeyText[locale][context.key] ?? context.key.replaceAll("_", " ");
  const language = context.language ? getLanguageLabels(locale)[context.language] : "";
  const suffix = language ? (locale === "en" ? ` (${language})` : `（${language}）`) : "";
  return `${stage} · ${key}${suffix}`;
}

export function browserLanguage(locale: Locale): string {
  return locale === "en" ? "en" : "zh-CN";
}

export function streamMessage(locale: Locale, state: StreamMessageState): string {
  if (state.kind === "raw") {
    return localizeStableError(locale, state.text);
  }

  const copy = messages[locale];
  switch (state.key) {
    case "restoredCampaign":
      return copy.restoredCampaign(state.campaignId ?? "");
    case "restoreFailedWithDetail":
      return copy.restoreFailedWithDetail(state.message ? localizeStableError(locale, state.message) : "");
    case "progressUpdate":
      return copy.progressUpdate(state.sequence ?? 0);
    case "detailRefreshed":
      return copy.detailRefreshed(state.sequence ?? 0);
    default: {
      const value = copy[state.key];
      return typeof value === "string" ? value : "";
    }
  }
}

export function localizeStableError(locale: Locale, value: string): string {
  for (const entry of stableErrorPatterns) {
    const match = entry.pattern.exec(value);
    if (match) {
      return entry[locale === "en" ? "en" : "zh"](match);
    }
  }

  return value;
}
