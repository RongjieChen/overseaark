import type { Locale } from "./i18n.js";
import type { CampaignFormData } from "./types.js";

export const DEMO_IMAGE_URL = "/demo/portable-smart-espresso-maker.png";
export const DEMO_IMAGE_FILENAME = "portable-smart-espresso-maker.png";
const MAX_DEMO_IMAGE_BYTES = 20 * 1024 * 1024;
const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a] as const;

type DemoCampaignForm = Omit<CampaignFormData, "imageFile">;
type DemoImageDecoder = (blob: Blob) => Promise<void>;

const demoCampaigns: Record<Locale, DemoCampaignForm> = {
  "zh-CN": {
    name: "便携式智能浓缩咖啡机全球上市",
    description:
      "一款面向差旅人士和精品咖啡爱好者的便携式智能浓缩咖啡机，支持 USB-C 充电、冷水快速加热、15 bar 萃取和可拆洗水仓。建议零售价 129 美元，整机重量约 780 克，适合办公室、露营和酒店场景。核心卖点是轻巧、即热、稳定出杯与容易清洁。",
    sourceMarket: "中国大陆",
    targetMarkets: "美国,日本,新加坡",
    transcription:
      "请重点突出便携、快速加热和容易清洁，面向经常出差的都市白领；文案语气要专业、可信，不要夸大续航或萃取效果。",
    targetLanguages: ["zh", "en", "ja"],
  },
  en: {
    name: "Portable smart espresso maker global launch",
    description:
      "A portable smart espresso maker for frequent travelers and specialty-coffee enthusiasts. It supports USB-C charging, rapid heating from cold water, 15-bar extraction, and a removable washable reservoir. With a suggested retail price of USD 129 and a weight of about 780 grams, it is designed for offices, campsites, and hotel rooms. Its core selling points are portability, fast heating, consistent extraction, and easy cleaning.",
    sourceMarket: "Mainland China",
    targetMarkets: "United States, Japan, Singapore",
    transcription:
      "Emphasize portability, rapid heating, and easy cleaning for urban professionals who travel often. Keep the claims professional and credible without exaggerating battery life or extraction quality.",
    targetLanguages: ["zh", "en", "ja"],
  },
};

export function getDemoCampaignForm(locale: Locale): DemoCampaignForm {
  const demo = demoCampaigns[locale];
  return {
    ...demo,
    targetLanguages: [...demo.targetLanguages],
  };
}

export async function fetchDemoImage(
  fetcher: typeof fetch = fetch,
  timeoutMs = 10_000,
  decoder: DemoImageDecoder = decodeImageBlob,
): Promise<Blob> {
  const controller = new AbortController();
  const operation = async (): Promise<Blob> => {
    const response = await fetcher(DEMO_IMAGE_URL, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`Demo image returned HTTP ${response.status}.`);
    }

    const contentType = response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
    if (contentType !== "image/png") {
      throw new Error("Demo image response is not PNG.");
    }

    const declaredSize = Number(response.headers.get("content-length"));
    if (Number.isFinite(declaredSize) && declaredSize > MAX_DEMO_IMAGE_BYTES) {
      throw new Error("Demo image response is too large.");
    }

    const imageBlob = await response.blob();
    if (imageBlob.size === 0 || imageBlob.size > MAX_DEMO_IMAGE_BYTES) {
      throw new Error("Demo image size is invalid.");
    }

    const signature = new Uint8Array(await imageBlob.slice(0, PNG_SIGNATURE.length).arrayBuffer());
    if (signature.length !== PNG_SIGNATURE.length || PNG_SIGNATURE.some((byte, index) => signature[index] !== byte)) {
      throw new Error("Demo image has an invalid PNG signature.");
    }

    try {
      await decoder(imageBlob);
    } catch {
      throw new Error("Demo image could not be decoded.");
    }

    return imageBlob;
  };
  let timeout: ReturnType<typeof globalThis.setTimeout> | undefined;
  const timeoutPromise = new Promise<never>((_resolve, reject) => {
    timeout = globalThis.setTimeout(() => {
      controller.abort();
      reject(new Error("Demo image loading timed out."));
    }, timeoutMs);
  });

  try {
    return await Promise.race([operation(), timeoutPromise]);
  } finally {
    if (timeout !== undefined) {
      globalThis.clearTimeout(timeout);
    }
  }
}

async function decodeImageBlob(imageBlob: Blob): Promise<void> {
  if (typeof globalThis.createImageBitmap === "function") {
    const bitmap = await globalThis.createImageBitmap(imageBlob);
    try {
      if (bitmap.width < 1 || bitmap.height < 1) {
        throw new Error("Decoded demo image has no pixels.");
      }
    } finally {
      bitmap.close();
    }
    return;
  }

  const imageUrl = URL.createObjectURL(imageBlob);
  try {
    const image = new Image();
    image.src = imageUrl;
    await image.decode();
    if (image.naturalWidth < 1 || image.naturalHeight < 1) {
      throw new Error("Decoded demo image has no pixels.");
    }
  } finally {
    URL.revokeObjectURL(imageUrl);
  }
}
