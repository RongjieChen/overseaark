import assert from "node:assert/strict";
import test from "node:test";
import { DEMO_IMAGE_FILENAME, DEMO_IMAGE_URL, fetchDemoImage, getDemoCampaignForm } from "../src/demo.js";

const PNG_BYTES = new Uint8Array(
  Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=", "base64"),
);
const SIGNATURE_ONLY = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00]);

function response(body: BodyInit | null, contentType: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { "content-type": contentType },
  });
}

test("provides complete Chinese and English demo campaigns", () => {
  const chinese = getDemoCampaignForm("zh-CN");
  const english = getDemoCampaignForm("en");

  assert.equal(chinese.name, "便携式智能浓缩咖啡机全球上市");
  assert.match(chinese.description, /USB-C/);
  assert.equal(chinese.sourceMarket, "中国大陆");
  assert.equal(chinese.targetMarkets, "美国,日本,新加坡");
  assert.deepEqual(chinese.targetLanguages, ["zh", "en", "ja"]);

  assert.equal(english.name, "Portable smart espresso maker global launch");
  assert.match(english.description, /USD 129/);
  assert.equal(english.sourceMarket, "Mainland China");
  assert.equal(english.targetMarkets, "United States, Japan, Singapore");
  assert.deepEqual(english.targetLanguages, ["zh", "en", "ja"]);
});

test("accepts only a non-empty PNG response with a valid signature", async () => {
  let decodeCalls = 0;
  const valid = await fetchDemoImage(
    async () => response(PNG_BYTES, "image/png") as Response,
    10_000,
    async () => {
      decodeCalls += 1;
    },
  );
  assert.equal(valid.size, PNG_BYTES.byteLength);
  assert.equal(decodeCalls, 1);

  await assert.rejects(
    fetchDemoImage(async () => response("<!doctype html>", "text/html") as Response, 10_000, async () => undefined),
    /not PNG/,
  );
  await assert.rejects(
    fetchDemoImage(async () => response(Uint8Array.from([1, 2, 3]), "image/png") as Response, 10_000, async () => undefined),
    /invalid PNG signature/,
  );
  await assert.rejects(
    fetchDemoImage(async () => response(null, "image/png", 404) as Response, 10_000, async () => undefined),
    /HTTP 404/,
  );
  await assert.rejects(
    fetchDemoImage(
      async () => response(SIGNATURE_ONLY, "image/png") as Response,
      10_000,
      async () => {
        throw new Error("decoder rejected truncated image");
      },
    ),
    /could not be decoded/,
  );
  await assert.rejects(
    fetchDemoImage(
      async () => response(PNG_BYTES, "image/png") as Response,
      20,
      () => new Promise<void>(() => undefined),
    ),
    /timed out/,
  );
});

test("returns isolated language arrays and a local bundled image path", () => {
  const first = getDemoCampaignForm("zh-CN");
  first.targetLanguages.pop();

  assert.deepEqual(getDemoCampaignForm("zh-CN").targetLanguages, ["zh", "en", "ja"]);
  assert.equal(DEMO_IMAGE_URL, "/demo/portable-smart-espresso-maker.png");
  assert.equal(DEMO_IMAGE_FILENAME, "portable-smart-espresso-maker.png");
});
