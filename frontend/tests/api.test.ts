import assert from "node:assert/strict";
import test from "node:test";
import {
  buildCampaignAssetUrl,
  buildCampaignExportUrl,
  normalizeCampaignDetail,
  normalizeCampaignEvent,
  normalizeCreateResponse,
  splitMarkets,
} from "../src/api.js";
import { createEmptyCampaign, mergeCampaignEvent } from "../src/campaign.js";

test("normalizes snake_case create response", () => {
  const response = normalizeCreateResponse({
    campaign_id: "cmp_123",
    status: "succeeded",
    last_sequence: 42,
    message: "ready",
  });

  assert.deepEqual(response, {
    id: "cmp_123",
    status: "complete",
    sequence: 42,
    message: "ready",
  });
});

test("normalizes stage name records and object-keyed artifacts", () => {
  const detail = normalizeCampaignDetail({
    campaign_id: "cmp_123",
    status: "completed",
    last_sequence: 9,
    stages: [
      { name: "market_positioning", status: "completed", message: "Positioned" },
      { name: "quality_packaging", status: "skipped", message: "No export requested" },
    ],
    artifacts: {
      multilingual_copy: {
        copy: {
          zh: "中文文案",
          en: "English copy",
          ja: "日本語コピー",
        },
      },
      visual_design: {
        poster: "poster.png",
      },
      media_production: {
        wav_zh: "zh.wav",
        wav_en: "en.wav",
        video: "demo.mp4",
      },
      quality_packaging: {
        qc_report: "ok",
        export_package: "bundle.zip",
      },
    },
  });

  assert.equal(detail.status, "complete");
  assert.equal(detail.stages.find((stage) => stage.key === "market_positioning")?.state, "complete");
  assert.equal(detail.stages.find((stage) => stage.key === "quality_packaging")?.state, "skipped");
  assert.equal(detail.artifacts.some((artifact) => artifact.language === "zh" && artifact.content === "中文文案"), true);
  assert.equal(detail.artifacts.some((artifact) => artifact.kind === "poster" && artifact.assetKey === "poster"), true);
  assert.equal(detail.artifacts.some((artifact) => artifact.kind === "audio" && artifact.content === "en.wav" && artifact.assetKey === "audio-en"), true);
  assert.equal(detail.artifacts.some((artifact) => artifact.kind === "video" && artifact.content === "demo.mp4" && artifact.assetKey === "video"), true);
  assert.equal(detail.artifacts.some((artifact) => artifact.kind === "diagnostic" && artifact.content === "ok"), true);
  assert.equal(detail.artifacts.find((artifact) => artifact.key === "poster")?.language, undefined);
  assert.equal(detail.artifacts.find((artifact) => artifact.key === "video")?.language, undefined);
  assert.deepEqual(
    detail.artifacts.find((artifact) => artifact.content === "中文文案")?.titleContext,
    { stage: "multilingual_copy", key: "copy", language: "zh" },
  );
});

test("normalizes object artifacts without treating object fields as languages", () => {
  const detail = normalizeCampaignDetail({
    id: "cmp_object",
    artifacts: {
      media_production: {
        audio: {
          zh: { audio_path: "voice_zh.wav", duration: 2.4 },
        },
        video: { video_path: "campaign_video.mp4", quality: "standard" },
      },
      quality_packaging: {
        qc: { passed: true, audio: { zh: { similarity: 0.96 } } },
      },
    },
  });

  const video = detail.artifacts.find((artifact) => artifact.key === "video");
  const qc = detail.artifacts.find((artifact) => artifact.key === "qc");

  assert.equal(video?.language, undefined);
  assert.equal(video?.kind, "video");
  assert.equal(video?.assetKey, "video");
  assert.equal(qc?.kind, "diagnostic");
  assert.equal(qc?.assetKey, "qc");
});

test("renders a completed stage and its artifacts from SSE alone", () => {
  const event = normalizeCampaignEvent({
    sequence: 17,
    type: "stage.succeeded",
    status: "running",
    stage: "multilingual_copy",
    message: "multilingual_copy succeeded",
    payload: {
      copy: {
        zh: { title: "本地增长团队", cta: "立即启航" },
        en: { title: "Your local growth team", cta: "Launch now" },
        ja: { title: "ローカル成長チーム", cta: "今すぐ開始" },
      },
    },
  });
  const campaign = mergeCampaignEvent(createEmptyCampaign(), event);

  assert.equal(event.stage && typeof event.stage === "object" ? event.stage.state : undefined, "complete");
  assert.equal(campaign.sequence, 17);
  assert.equal(campaign.stages.find((stage) => stage.key === "multilingual_copy")?.state, "complete");
  assert.equal(campaign.artifacts.length, 3);
  assert.equal(campaign.artifacts.find((artifact) => artifact.language === "en")?.content.includes("Launch now"), true);
});

test("accepts a stage result wrapped in payload.output", () => {
  const event = normalizeCampaignEvent({
    sequence: "18",
    type: "stage.succeeded",
    stage: "visual_design",
    payload: {
      output: {
        image_path: "/tmp/poster.png",
      },
    },
  });

  assert.equal(event.sequence, 18);
  assert.equal(event.artifacts?.[0]?.kind, "poster");
  assert.equal(event.artifacts?.[0]?.assetKey, "poster");
});

test("builds contracted campaign asset and export URLs", () => {
  assert.equal(
    buildCampaignAssetUrl("/api/v1/", "cmp 123", "audio-en"),
    "/api/v1/campaigns/cmp%20123/assets/audio-en",
  );
  assert.equal(buildCampaignExportUrl("/api/v1", "cmp_123"), "/api/v1/campaigns/cmp_123/export");
  assert.equal(buildCampaignExportUrl("/api/v1", "cmp_123", "ja"), "/api/v1/campaigns/cmp_123/export?language=ja");
});

test("splits target markets written with English or Chinese punctuation", () => {
  assert.deepEqual(splitMarkets("美国，日本、德国, France"), ["美国", "日本", "德国", "France"]);
});
