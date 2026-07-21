import assert from "node:assert/strict";
import test from "node:test";
import { normalizeCampaignDetail, normalizeCreateResponse } from "../src/api.js";

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
  assert.equal(detail.artifacts.some((artifact) => artifact.kind === "image_prompt" && artifact.content === "poster.png"), true);
  assert.equal(detail.artifacts.some((artifact) => artifact.kind === "audio" && artifact.content === "en.wav"), true);
  assert.equal(detail.artifacts.some((artifact) => artifact.kind === "export" && artifact.content === "demo.mp4"), true);
  assert.equal(detail.artifacts.some((artifact) => artifact.kind === "diagnostic" && artifact.content === "ok"), true);
});
