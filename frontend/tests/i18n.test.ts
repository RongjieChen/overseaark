import assert from "node:assert/strict";
import test from "node:test";
import {
  browserLanguage,
  getBrowserLocale,
  getApiStatusText,
  getArtifactKindText,
  getArtifactTitle,
  getLanguageLabels,
  getModelStatusText,
  getQualityText,
  getStageText,
  getStatusText,
  getStoredLocale,
  localizeStableError,
  messages,
  normalizeLocale,
  persistLocale,
  persistBrowserLocale,
  readBrowserStorageItem,
  removeBrowserStorageItem,
  streamMessage,
  validationMessages,
  writeBrowserStorageItem,
} from "../src/i18n.js";
import { validateDescription, validateProductImage } from "../src/campaign.js";

test("defaults to Simplified Chinese and preserves explicit English", () => {
  assert.equal(normalizeLocale(null), "zh-CN");
  assert.equal(normalizeLocale("zh-CN"), "zh-CN");
  assert.equal(normalizeLocale("en"), "en");
  assert.equal(browserLanguage("zh-CN"), "zh-CN");
  assert.equal(browserLanguage("en"), "en");
});

test("persists locale selections through local storage", () => {
  const storage = new MapStorage();

  assert.equal(getStoredLocale(storage), "zh-CN");
  persistLocale(storage, "en");
  assert.equal(getStoredLocale(storage), "en");
});

test("falls back to Chinese when browser storage is unavailable", () => {
  const host = {
    get localStorage(): Storage {
      throw new Error("storage denied");
    },
  };

  assert.equal(getBrowserLocale(host), "zh-CN");
  assert.doesNotThrow(() => persistBrowserLocale(host, "en"));

  const storage = new ThrowingStorage();
  assert.equal(getStoredLocale(storage), "zh-CN");
  assert.doesNotThrow(() => persistLocale(storage, "en"));
  assert.equal(readBrowserStorageItem(host, "campaign"), null);
  assert.equal(writeBrowserStorageItem(host, "campaign", "cmp-1"), false);
  assert.equal(removeBrowserStorageItem(host, "campaign"), false);
});

test("translates primary stage, status, language, artifact, and validation labels", () => {
  assert.equal(messages["zh-CN"].appTitle, "DGX Spark一支不下班的本地多模态外贸营销团队");
  assert.equal(messages.en.appTitle, "DGX Spark: Your always-on local multimodal export marketing team");
  assert.equal(messages["zh-CN"].fillDemo, "一键填入示例");
  assert.equal(messages.en.fillDemo, "Fill demo");
  assert.equal(getStageText("zh-CN", "market_positioning").label, "市场定位");
  assert.equal(getStageText("en", "market_positioning").label, "Market Positioning");
  assert.equal(getStatusText("zh-CN", "running"), "运行中");
  assert.equal(getStatusText("en", "running"), "Running");
  assert.equal(getApiStatusText("zh-CN", "unknown"), "未知");
  assert.equal(getApiStatusText("en", "unknown"), "Unknown");
  assert.equal(getModelStatusText("zh-CN", "warming"), "加载中");
  assert.equal(getModelStatusText("en", "warming"), "Warming");
  assert.equal(getLanguageLabels("zh-CN").en, "英语");
  assert.equal(getLanguageLabels("en").en, "English");
  assert.equal(getArtifactKindText("zh-CN", "image_prompt"), "视觉提示词");
  assert.equal(getArtifactKindText("zh-CN", "video"), "视频");
  assert.equal(getArtifactKindText("en", "poster"), "Poster");
  assert.equal(getQualityText("zh-CN", "degraded"), "降级产物");
  const generatedArtifact = {
    id: "copy-zh",
    title: "Multilingual Copy copy ZH",
    stage: "multilingual_copy" as const,
    key: "copy",
    language: "zh" as const,
    kind: "copy" as const,
    content: "中文文案",
    titleContext: { stage: "multilingual_copy" as const, key: "copy", language: "zh" as const },
  };
  assert.equal(getArtifactTitle("zh-CN", generatedArtifact), "多语文案 · 文案（中文）");
  assert.equal(getArtifactTitle("en", generatedArtifact), "Multilingual Copy · Copy (Chinese)");
  assert.equal(messages["zh-CN"].emptyArtifacts("中文"), "还没有 中文 产物。");
  assert.equal(messages["zh-CN"].stageArtifacts, "阶段过程产物");
  assert.equal(messages.en.exportCurrent, "Export current language");
  assert.equal(messages["zh-CN"].defaultTargetMarkets, "美国,日本,中国大陆");
  assert.equal(messages.en.defaultTargetMarkets, "United States, Japan, Mainland China");
  assert.equal(validateDescription("abcd", validationMessages["zh-CN"]), "产品描述至少需要 5 个字符。");
  assert.equal(validateProductImage(null, validationMessages["zh-CN"]), "请上传产品图片。");
});

test("localizes stored stream message state after locale changes", () => {
  const message = { kind: "localized" as const, key: "progressUpdate" as const, sequence: 12 };

  assert.equal(streamMessage("zh-CN", message), "收到进度更新，序列 12。");
  assert.equal(streamMessage("en", message), "Progress update received at sequence 12.");
  assert.equal(streamMessage("zh-CN", { kind: "localized", key: "demoFilled" }), "演示内容和商品图片已填入，可以直接创建活动。");
  assert.equal(streamMessage("en", { kind: "localized", key: "demoFilled" }), "Demo content and product image are ready. You can create the campaign now.");
});

test("translates stable frontend API errors and preserves unknown backend text", () => {
  assert.equal(localizeStableError("zh-CN", "Campaign detail failed with HTTP 404."), "活动详情加载失败，HTTP 404。");
  assert.equal(localizeStableError("zh-CN", "Progress stream interrupted. Reconnect will resume from the latest sequence."), "进度流中断，将从最新序列自动重连。");
  assert.equal(localizeStableError("zh-CN", "Health endpoint returned an invalid response."), "健康接口返回了无效响应。");
  assert.equal(localizeStableError("zh-CN", "Failed to fetch"), "无法连接服务。");
  assert.equal(localizeStableError("zh-CN", "模型输出缺少日语脚本。"), "模型输出缺少日语脚本。");
  assert.equal(streamMessage("zh-CN", { kind: "raw", text: "Campaign export failed with HTTP 500." }), "活动导出失败，HTTP 500。");
});

class MapStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return Array.from(this.values.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

class ThrowingStorage implements Storage {
  get length(): number {
    throw new Error("storage denied");
  }

  clear(): void {
    throw new Error("storage denied");
  }

  getItem(): string | null {
    throw new Error("storage denied");
  }

  key(): string | null {
    throw new Error("storage denied");
  }

  removeItem(): void {
    throw new Error("storage denied");
  }

  setItem(): void {
    throw new Error("storage denied");
  }
}
