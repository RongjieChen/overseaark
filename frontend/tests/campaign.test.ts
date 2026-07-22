import assert from "node:assert/strict";
import test from "node:test";
import {
  createEmptyCampaign,
  createConnectionFailureCampaign,
  artifactsForStage,
  mergeCampaignEvent,
  normalizeCampaignStatus,
  normalizeStageState,
  selectLocalizedArtifacts,
  selectCampaignId,
  validateDescription,
  validateProductImage,
} from "../src/campaign.js";

test("validates product description bounds", () => {
  assert.equal(validateDescription("abcd"), "Description must contain at least 5 characters.");
  assert.equal(validateDescription("valid product description"), null);
  assert.equal(validateDescription("x".repeat(2001)), "Description must be 2000 characters or fewer.");
});

test("merges stage, artifact, warning, and sequence updates", () => {
  const campaign = mergeCampaignEvent(createEmptyCampaign(), {
    sequence: 7,
    type: "artifact",
    stage: {
      key: "multilingual_copy",
      state: "complete",
      detail: "Copy ready",
    },
    artifact: {
      id: "a1",
      title: "English Launch Copy",
      stage: "multilingual_copy",
      key: "copy",
      language: "en",
      kind: "copy",
      quality: "final",
      content: "Launch now",
    },
  });

  assert.equal(campaign.sequence, 7);
  assert.equal(campaign.stages.find((stage) => stage.key === "multilingual_copy")?.state, "complete");
  assert.equal(campaign.artifacts[0]?.content, "Launch now");

  const warned = mergeCampaignEvent(campaign, {
    sequence: 8,
    type: "warning",
    message: "Model returned partial output.",
  });

  assert.deepEqual(warned.warnings, ["Model returned partial output."]);
});

test("maps stage lifecycle event types without failing the whole campaign", () => {
  const running = mergeCampaignEvent(createEmptyCampaign(), {
    sequence: 1,
    type: "stage.started",
    status: "running",
    stage: "buyer_persona",
  });
  const completed = mergeCampaignEvent(running, {
    sequence: 2,
    type: "stage.succeeded",
    status: "running",
    stage: "buyer_persona",
  });
  const failed = mergeCampaignEvent(completed, {
    sequence: 3,
    type: "stage.failed",
    status: "running",
    stage: "visual_design",
    message: "image model error",
  });
  const skipped = mergeCampaignEvent(failed, {
    sequence: 4,
    type: "stage.skipped",
    status: "running",
    stage: "media_production",
  });

  assert.equal(running.stages.find((stage) => stage.key === "buyer_persona")?.state, "running");
  assert.equal(completed.stages.find((stage) => stage.key === "buyer_persona")?.state, "complete");
  assert.equal(failed.stages.find((stage) => stage.key === "visual_design")?.state, "failed");
  assert.equal(failed.status, "running");
  assert.equal(skipped.stages.find((stage) => stage.key === "media_production")?.state, "skipped");
});

test("ignores duplicate and out-of-order event sequences", () => {
  const current = mergeCampaignEvent(createEmptyCampaign(), {
    sequence: 10,
    type: "stage.succeeded",
    stage: "market_positioning",
  });
  const duplicate = mergeCampaignEvent(current, {
    sequence: 10,
    type: "stage.failed",
    stage: "market_positioning",
    message: "stale duplicate",
  });
  const outOfOrder = mergeCampaignEvent(current, {
    sequence: 9,
    type: "stage.started",
    stage: "market_positioning",
  });

  assert.strictEqual(duplicate, current);
  assert.strictEqual(outOfOrder, current);
  assert.equal(current.stages.find((stage) => stage.key === "market_positioning")?.state, "complete");
});

test("selects localized copy and matching audio without shared artifacts", () => {
  const artifacts = [
    {
      id: "copy-en",
      title: "Copy EN",
      stage: "multilingual_copy" as const,
      key: "copy",
      language: "en" as const,
      kind: "copy" as const,
      content: "English copy",
    },
    {
      id: "audio-en",
      title: "Audio EN",
      stage: "media_production" as const,
      key: "audio",
      language: "en" as const,
      kind: "audio" as const,
      content: "voice_en.wav",
      assetKey: "audio-en" as const,
    },
    {
      id: "poster",
      title: "Poster",
      stage: "visual_design" as const,
      key: "poster",
      kind: "poster" as const,
      content: "poster.png",
      assetKey: "poster" as const,
    },
  ];

  assert.deepEqual(selectLocalizedArtifacts(artifacts, "en").map((artifact) => artifact.id), ["copy-en", "audio-en"]);
  assert.deepEqual(artifactsForStage(artifacts, "visual_design").map((artifact) => artifact.id), ["poster"]);
});

test("creates connection failure campaign without fake artifacts", () => {
  const campaign = createConnectionFailureCampaign("HTTP 503", "活动创建请求未到达后端。");

  assert.equal(campaign.status, "failed");
  assert.equal(campaign.artifacts.length, 0);
  assert.equal(campaign.stages[0]?.state, "failed");
  assert.equal(campaign.error, "HTTP 503");
  assert.equal(campaign.summary, "活动创建请求未到达后端。");
});

test("normalizes backend success and skipped statuses", () => {
  assert.equal(normalizeCampaignStatus("completed"), "complete");
  assert.equal(normalizeCampaignStatus("succeeded"), "complete");
  assert.equal(normalizeStageState("completed"), "complete");
  assert.equal(normalizeStageState("skipped"), "skipped");
});

test("requires JPG, PNG, or WebP product image up to 20MB", () => {
  assert.equal(validateProductImage(null), "Product image is required.");

  const oversized = new File(["x".repeat(1024)], "large.png", { type: "image/png" });
  Object.defineProperty(oversized, "size", { value: 21 * 1024 * 1024 });

  assert.equal(validateProductImage(new File(["x"], "bad.gif", { type: "image/gif" })), "Product image must be JPG, PNG, or WebP.");
  assert.equal(validateProductImage(oversized), "Product image must be 20MB or smaller.");
  assert.equal(validateProductImage(new File(["x"], "good.webp", { type: "image/webp" })), null);
});

test("restores a campaign from a deep link before local browser state", () => {
  assert.equal(selectCampaignId("  campaign-from-url  ", "campaign-from-storage"), "campaign-from-url");
  assert.equal(selectCampaignId(null, "  campaign-from-storage  "), "campaign-from-storage");
  assert.equal(selectCampaignId("  ", "  "), "");
});
