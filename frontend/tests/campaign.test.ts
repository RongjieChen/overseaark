import assert from "node:assert/strict";
import test from "node:test";
import {
  createEmptyCampaign,
  createConnectionFailureCampaign,
  mergeCampaignEvent,
  normalizeCampaignStatus,
  normalizeStageState,
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

test("creates connection failure campaign without fake artifacts", () => {
  const campaign = createConnectionFailureCampaign("HTTP 503");

  assert.equal(campaign.status, "failed");
  assert.equal(campaign.artifacts.length, 0);
  assert.equal(campaign.stages[0]?.state, "failed");
  assert.equal(campaign.error, "HTTP 503");
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
