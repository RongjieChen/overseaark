import { ApiClient, type ProgressStream } from "./api.js";
import {
  createEmptyCampaign,
  artifactsForStage,
  formatDateTime,
  mergeCampaignEvent,
  selectCampaignId,
  selectLocalizedArtifacts,
  statusTone,
  validateDescription,
  validateProductImage,
} from "./campaign.js";
import {
  browserLanguage,
  getApiStatusText,
  getArtifactKindText,
  getArtifactTitle,
  getBrowserLocale,
  getLanguageLabels,
  getModelStatusText,
  getQualityText,
  getStageText,
  getStatusText,
  localizeStableError,
  localeLabel,
  messages,
  persistBrowserLocale,
  readBrowserStorageItem,
  removeBrowserStorageItem,
  streamMessage,
  validationMessages,
  writeBrowserStorageItem,
  type Locale,
  type StreamMessageKey,
  type StreamMessageState,
} from "./i18n.js";
import { DEMO_IMAGE_FILENAME, fetchDemoImage, getDemoCampaignForm } from "./demo.js";
import type { Artifact, CampaignDetail, CampaignFormData, CampaignStageKey, HealthStatus, LanguageCode } from "./types.js";
import "./styles.css";

const api = new ApiClient();
const LAST_CAMPAIGN_KEY = "overseaark.lastCampaignId";
const initialLocale = getBrowserLocale(window);
const state: {
  form: CampaignFormData;
  campaign: CampaignDetail;
  health: HealthStatus | null;
  imagePreviewUrl: string;
  busy: boolean;
  demoLoading: boolean;
  stream: ProgressStream | null;
  streamMessage: StreamMessageState;
  selectedLanguage: LanguageCode;
  rerunStage: CampaignStageKey;
  refreshTimer: number | null;
  locale: Locale;
} = {
  form: {
    name: "",
    description: "",
    sourceMarket: "",
    targetMarkets: messages[initialLocale].defaultTargetMarkets,
    transcription: "",
    targetLanguages: ["zh", "en", "ja"],
    imageFile: null,
  },
  campaign: createEmptyCampaign(),
  health: null,
  imagePreviewUrl: "",
  busy: false,
  demoLoading: false,
  stream: null,
  streamMessage: { kind: "localized", key: "noActiveStream" },
  selectedLanguage: "zh",
  rerunStage: "market_positioning",
  refreshTimer: null,
  locale: initialLocale,
};

const appRoot = document.querySelector<HTMLDivElement>("#app");

if (!appRoot) {
  throw new Error("App root not found.");
}

const app = appRoot;

render();
void initializeApp();

async function initializeApp(): Promise<void> {
  await refreshHealth();
  await restoreCampaignFromBrowserState();
}

function render(): void {
  syncDocumentLocale();
  const copy = t();
  const languageLabels = getLanguageLabels(state.locale);

  app.innerHTML = `
    <main class="shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">OverseaArk</p>
          <h1>${copy.appTitle}</h1>
        </div>
        <div class="topbar-tools">
          ${renderLocaleSwitcher()}
          ${renderHealth()}
          ${renderGpuGuide()}
        </div>
      </header>

      <section class="workspace" aria-label="${copy.workspaceLabel}">
        <form class="panel composer" id="campaign-form">
          <div class="section-heading">
            <div>
              <p class="eyebrow">${copy.createEyebrow}</p>
              <h2>${copy.productCampaign}</h2>
            </div>
            <button class="icon-button" type="button" id="refresh-health" aria-label="${copy.refreshAria}" title="${copy.refreshTitle}">↻</button>
          </div>

          <fieldset class="form-fields" aria-busy="${state.demoLoading}" ${state.demoLoading ? "disabled" : ""}>
          <div class="demo-callout" role="status" aria-live="polite">
            <div>
              <strong>${copy.demoTitle}</strong>
              <span>${copy.demoHint}</span>
            </div>
            <button type="button" id="fill-demo" aria-label="${copy.fillDemoAria}" ${state.busy || state.demoLoading ? "disabled" : ""}>
              ${state.demoLoading ? copy.fillingDemo : copy.fillDemo}
            </button>
          </div>

          <label class="field">
            <span>${copy.campaignName}</span>
            <input id="campaign-name" name="name" type="text" maxlength="120" placeholder="${copy.campaignNamePlaceholder}" value="${escapeHtml(state.form.name)}" />
          </label>

          <label class="field image-drop" for="product-image">
            <span>${copy.productImage}</span>
            <input id="product-image" name="product_image" type="file" accept="image/jpeg,image/png,image/webp" />
            <div class="image-preview ${state.imagePreviewUrl ? "has-image" : ""}">
              ${
                state.imagePreviewUrl
                  ? `<img src="${state.imagePreviewUrl}" alt="${copy.selectedProductPreview}" />`
                  : `<div><strong>${copy.uploadImage}</strong><small>${copy.uploadImageHint}</small></div>`
              }
            </div>
          </label>

          <label class="field">
            <span>${copy.productDescription} <small>${state.form.description.trim().length}/2000</small></span>
            <textarea id="description" name="description" minlength="5" maxlength="2000" rows="8" placeholder="${copy.descriptionPlaceholder}">${escapeHtml(state.form.description)}</textarea>
          </label>

          <label class="field">
            <span>${copy.audioTranscription} <small>${copy.optional}</small></span>
            <textarea id="transcription" name="transcription" maxlength="4000" rows="4" placeholder="${copy.transcriptionPlaceholder}">${escapeHtml(state.form.transcription)}</textarea>
          </label>

          <label class="field">
            <span>${copy.sourceMarket}</span>
            <input id="source-market" name="sourceMarket" type="text" maxlength="120" placeholder="${copy.sourceMarketPlaceholder}" value="${escapeHtml(state.form.sourceMarket)}" />
          </label>

          <label class="field">
            <span>${copy.targetMarkets}</span>
            <input id="target-markets" name="targetMarkets" type="text" maxlength="240" placeholder="${copy.targetMarketsPlaceholder}" value="${escapeHtml(state.form.targetMarkets)}" />
          </label>

          <fieldset class="language-grid">
            <legend>${copy.outputLanguages}</legend>
            ${(["zh", "en", "ja"] as LanguageCode[]).map(renderLanguageChoice).join("")}
          </fieldset>

          <div class="actions">
            <button class="primary" id="create-campaign" type="submit" ${state.busy || state.demoLoading ? "disabled" : ""}>${copy.createCampaign}</button>
            <button type="button" id="load-detail" ${!state.campaign.id ? "disabled" : ""}>${copy.loadDetail}</button>
          </div>
          </fieldset>
          <p class="form-error" id="form-error" role="alert"></p>
        </form>

        <section class="panel progress-panel" aria-labelledby="progress-title">
          <div class="section-heading">
            <div>
              <p class="eyebrow">${copy.progressEyebrow}</p>
              <h2 id="progress-title">${copy.pipelineTitle}</h2>
            </div>
            <span class="status ${statusTone(state.campaign.status)}">${getStatusText(state.locale, state.campaign.status)}</span>
          </div>
          <div class="stream-line" role="status" aria-live="polite">${escapeHtml(streamMessage(state.locale, state.streamMessage))}</div>
          <ol class="stage-list">
            ${state.campaign.stages.map((stage, index) => `
              <li class="stage ${statusTone(stage.state)}">
                <div class="stage-index" aria-hidden="true">${index + 1}</div>
                <div>
                  <div class="stage-title">
                    <strong>${escapeHtml(getStageText(state.locale, stage.key).label)}</strong>
                    <span>${escapeHtml(getStatusText(state.locale, stage.state))}</span>
                  </div>
                  <p>${escapeHtml(getStageText(state.locale, stage.key).description)}</p>
                  ${stage.detail ? `<small>${escapeHtml(stage.detail)}</small>` : ""}
                </div>
              </li>
            `).join("")}
          </ol>

          <div class="actions split">
            <select id="rerun-stage" aria-label="${copy.stageToRerun}" ${!canUseCampaignActions() ? "disabled" : ""}>
              ${state.campaign.stages.map((stage) => `
                <option value="${stage.key}" ${selectedRerunStage() === stage.key ? "selected" : ""}>${escapeHtml(getStageText(state.locale, stage.key).label)}</option>
              `).join("")}
            </select>
            <button type="button" id="rerun-campaign" ${!canUseCampaignActions() ? "disabled" : ""}>${copy.rerun}</button>
            <button type="button" id="cancel-campaign" ${!canCancel() ? "disabled" : ""}>${copy.cancel}</button>
            <button type="button" id="export-all-campaign" ${!canExport() ? "disabled" : ""}>${copy.exportAll}</button>
            <button type="button" id="export-current-campaign" ${!canExport() ? "disabled" : ""}>${copy.exportCurrent}</button>
          </div>
        </section>
      </section>

      <section class="detail-grid" aria-label="${copy.detailArtifactsLabel}">
        <article class="panel detail-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">${copy.detailEyebrow}</p>
              <h2>${state.campaign.id ? `${copy.campaign} ${escapeHtml(state.campaign.id)}` : copy.noCampaignSelected}</h2>
            </div>
            <span class="sequence">${copy.sequence} ${state.campaign.sequence}</span>
          </div>
          <dl class="meta-grid">
            <div><dt>${copy.created}</dt><dd>${escapeHtml(formatDateTime(state.campaign.createdAt, browserLanguage(state.locale), copy.notAvailable))}</dd></div>
            <div><dt>${copy.updated}</dt><dd>${escapeHtml(formatDateTime(state.campaign.updatedAt, browserLanguage(state.locale), copy.notAvailable))}</dd></div>
          </dl>
          <p class="summary">${escapeHtml(state.campaign.summary ?? copy.defaultSummary)}</p>
          ${renderStateMessages()}
        </article>

        <article class="panel artifacts-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">${copy.artifactsEyebrow}</p>
              <h2>${copy.localizedOutputs}</h2>
            </div>
            <div class="tabs" role="tablist" aria-label="${copy.artifactLanguage}">
              ${(["zh", "en", "ja"] as LanguageCode[]).map((language) => `
                <button type="button" class="${state.selectedLanguage === language ? "active" : ""}" data-language="${language}" role="tab" aria-selected="${state.selectedLanguage === language}">
                  ${languageLabels[language]}
                </button>
              `).join("")}
            </div>
          </div>
          <div class="artifact-stack">
            ${renderArtifacts()}
          </div>
        </article>

        <article class="panel artifacts-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">${copy.artifactsEyebrow}</p>
              <h2>${copy.stageArtifacts}</h2>
            </div>
          </div>
          <div class="stage-artifact-stack">
            ${renderStageArtifacts()}
          </div>
        </article>
      </section>
    </main>
  `;

  bindEvents();
}

function t(): (typeof messages)[Locale] {
  return messages[state.locale];
}

function syncDocumentLocale(): void {
  document.documentElement.lang = browserLanguage(state.locale);
  document.title = t().documentTitle;
}

function renderLocaleSwitcher(): string {
  return `
    <div class="locale-switch" role="group" aria-label="${t().languageSwitcherLabel}">
      ${(["zh-CN", "en"] as Locale[]).map((locale) => `
        <button type="button" class="${state.locale === locale ? "active" : ""}" data-locale="${locale}" aria-pressed="${state.locale === locale}" ${state.demoLoading ? "disabled" : ""}>
          ${localeLabel(locale)}
        </button>
      `).join("")}
    </div>
  `;
}

function renderHealth(): string {
  const copy = t();
  if (!state.health) {
    return `<aside class="health unknown" aria-live="polite"><strong>${copy.checking}</strong><span>${copy.modelStatusPending}</span></aside>`;
  }

  return `
    <aside class="health ${state.health.ok ? "online" : "offline"}" aria-live="polite">
      <strong>${copy.api} ${getApiStatusText(state.locale, state.health.api)}</strong>
      <span>${copy.model} ${getModelStatusText(state.locale, state.health.model)}</span>
      <small>${escapeHtml(localizeStableError(state.locale, state.health.detail))}</small>
    </aside>
  `;
}

function renderGpuGuide(): string {
  const copy = t();
  return `
    <details class="gpu-guide">
      <summary>${copy.gpuGuideTitle}</summary>
      <p>${copy.gpuGuideHint}</p>
      <div><span>${copy.gpuSnapshotLabel}</span><code>nvidia-smi</code></div>
      <div><span>${copy.gpuLiveLabel}</span><code>nvidia-smi dmon -s pucvmet</code></div>
    </details>
  `;
}

function renderLanguageChoice(language: LanguageCode): string {
  const checked = state.form.targetLanguages.includes(language) ? "checked" : "";
  const languageLabels = getLanguageLabels(state.locale);
  return `
    <label>
      <input type="checkbox" name="language" value="${language}" ${checked} />
      <span>${languageLabels[language]}</span>
    </label>
  `;
}

function renderStateMessages(): string {
  const messages = [
    ...state.campaign.warnings.map((warning) => ({ tone: "warn", text: warning })),
    ...(state.campaign.error ? [{ tone: "bad", text: state.campaign.error }] : []),
  ];

  if (messages.length === 0) {
    return "";
  }

  return `
    <div class="message-stack">
      ${messages.map((message) => `<p class="message ${message.tone}">${escapeHtml(message.text)}</p>`).join("")}
    </div>
  `;
}

function renderArtifacts(): string {
  const artifacts = selectLocalizedArtifacts(state.campaign.artifacts, state.selectedLanguage);
  const copy = t();
  const languageLabels = getLanguageLabels(state.locale);

  if (artifacts.length === 0) {
    return `<p class="empty">${copy.emptyArtifacts(languageLabels[state.selectedLanguage])}</p>`;
  }

  return artifacts.map((artifact) => renderArtifactCard(artifact)).join("");
}

function renderStageArtifacts(): string {
  const copy = t();
  const stageGroups = state.campaign.stages
    .map((stage) => ({ stage, artifacts: artifactsForStage(state.campaign.artifacts, stage.key) }))
    .filter((group) => group.artifacts.length > 0);

  if (stageGroups.length === 0) {
    return `<p class="empty">${copy.emptyStageArtifacts}</p>`;
  }

  return stageGroups.map(({ stage, artifacts }) => `
    <section class="stage-artifact-group">
      <div class="stage-artifact-heading">
        <strong>${escapeHtml(getStageText(state.locale, stage.key).label)}</strong>
        <span>${escapeHtml(getStatusText(state.locale, stage.state))}</span>
      </div>
      <div class="artifact-stack">
        ${artifacts.map((artifact) => renderArtifactCard(artifact)).join("")}
      </div>
    </section>
  `).join("");
}

function renderArtifactCard(artifact: Artifact): string {
  return `
    <section class="artifact">
      <div>
        <strong>${escapeHtml(getArtifactTitle(state.locale, artifact))}</strong>
        <span>${escapeHtml(getArtifactKindText(state.locale, artifact.kind))} · ${escapeHtml(getQualityText(state.locale, artifact.quality ?? "final"))}</span>
      </div>
      ${renderArtifactBody(artifact)}
    </section>
  `;
}

function renderArtifactBody(artifact: Artifact): string {
  const assetUrl = artifact.assetKey && state.campaign.id ? api.assetUrl(state.campaign.id, artifact.assetKey) : "";

  if (artifact.kind === "poster" && assetUrl) {
    return `<img class="artifact-media" src="${escapeAttribute(assetUrl)}" alt="${escapeAttribute(getArtifactTitle(state.locale, artifact))}" loading="lazy" />`;
  }

  if (artifact.kind === "audio" && assetUrl) {
    return `<audio controls preload="none" src="${escapeAttribute(assetUrl)}"></audio>${renderOptionalArtifactText(artifact)}`;
  }

  if (artifact.kind === "video" && assetUrl) {
    return `<video controls preload="metadata" src="${escapeAttribute(assetUrl)}"></video>${renderOptionalArtifactText(artifact)}`;
  }

  if (artifact.kind === "diagnostic") {
    return `<div class="structured-artifact">${renderStructuredArtifact(artifact.content)}</div>`;
  }

  return `<pre>${escapeHtml(artifact.content)}</pre>`;
}

function renderOptionalArtifactText(artifact: Artifact): string {
  return artifact.content.trim() ? `<pre>${escapeHtml(artifact.content)}</pre>` : "";
}

function renderStructuredArtifact(content: string): string {
  try {
    return renderStructuredValue(JSON.parse(content));
  } catch {
    return `<pre>${escapeHtml(content)}</pre>`;
  }
}

function renderStructuredValue(value: unknown): string {
  if (Array.isArray(value)) {
    return `<ul>${value.map((item) => `<li>${renderStructuredValue(item)}</li>`).join("")}</ul>`;
  }

  if (value && typeof value === "object") {
    return `
      <dl>
        ${Object.entries(value as Record<string, unknown>).map(([key, item]) => `
          <div>
            <dt>${escapeHtml(key.replaceAll("_", " "))}</dt>
            <dd>${renderStructuredValue(item)}</dd>
          </div>
        `).join("")}
      </dl>
    `;
  }

  return `<span>${escapeHtml(String(value ?? ""))}</span>`;
}

function bindEvents(): void {
  document.querySelector<HTMLFormElement>("#campaign-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    void createCampaign();
  });

  document.querySelector<HTMLInputElement>("#campaign-name")?.addEventListener("input", (event) => {
    state.form.name = (event.target as HTMLInputElement).value;
  });

  document.querySelector<HTMLTextAreaElement>("#description")?.addEventListener("input", (event) => {
    state.form.description = (event.target as HTMLTextAreaElement).value;
    render();
  });

  document.querySelector<HTMLTextAreaElement>("#transcription")?.addEventListener("input", (event) => {
    state.form.transcription = (event.target as HTMLTextAreaElement).value;
  });

  document.querySelector<HTMLInputElement>("#source-market")?.addEventListener("input", (event) => {
    state.form.sourceMarket = (event.target as HTMLInputElement).value;
  });

  document.querySelector<HTMLInputElement>("#target-markets")?.addEventListener("input", (event) => {
    state.form.targetMarkets = (event.target as HTMLInputElement).value;
  });

  document.querySelectorAll<HTMLButtonElement>("[data-locale]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextLocale = button.dataset.locale === "en" ? "en" : "zh-CN";
      if (state.form.targetMarkets === messages[state.locale].defaultTargetMarkets) {
        state.form.targetMarkets = messages[nextLocale].defaultTargetMarkets;
      }
      state.locale = nextLocale;
      persistBrowserLocale(window, state.locale);
      render();
    });
  });

  document.querySelector<HTMLInputElement>("#product-image")?.addEventListener("change", (event) => {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    state.form.imageFile = file;
    if (state.imagePreviewUrl) {
      URL.revokeObjectURL(state.imagePreviewUrl);
    }
    state.imagePreviewUrl = file ? URL.createObjectURL(file) : "";
    render();
  });

  document.querySelector("#fill-demo")?.addEventListener("click", () => {
    void fillDemoForm();
  });

  document.querySelectorAll<HTMLInputElement>("input[name='language']").forEach((input) => {
    input.addEventListener("change", () => {
      const values = Array.from(document.querySelectorAll<HTMLInputElement>("input[name='language']:checked")).map(
        (checked) => checked.value as LanguageCode,
      );
      state.form.targetLanguages = values.length > 0 ? values : ["en"];
      render();
    });
  });

  document.querySelector("#refresh-health")?.addEventListener("click", () => {
    void refreshHealth();
  });

  document.querySelector("#load-detail")?.addEventListener("click", () => {
    void loadDetail();
  });

  document.querySelector("#rerun-campaign")?.addEventListener("click", () => {
    void rerunCampaign();
  });

  document.querySelector<HTMLSelectElement>("#rerun-stage")?.addEventListener("change", (event) => {
    state.rerunStage = (event.target as HTMLSelectElement).value as CampaignStageKey;
  });

  document.querySelector("#cancel-campaign")?.addEventListener("click", () => {
    void cancelCampaign();
  });

  document.querySelector("#export-all-campaign")?.addEventListener("click", () => {
    void exportCampaign();
  });

  document.querySelector("#export-current-campaign")?.addEventListener("click", () => {
    void exportCampaign(state.selectedLanguage);
  });

  document.querySelectorAll<HTMLButtonElement>("[data-language]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedLanguage = button.dataset.language as LanguageCode;
      render();
    });
  });
}

async function fillDemoForm(): Promise<void> {
  if (state.busy || state.demoLoading) {
    return;
  }

  state.demoLoading = true;
  const demoLocale = state.locale;
  render();

  try {
    const imageBlob = await fetchDemoImage();
    const imageFile = new File([imageBlob], DEMO_IMAGE_FILENAME, { type: "image/png" });
    if (state.imagePreviewUrl) {
      URL.revokeObjectURL(state.imagePreviewUrl);
    }

    state.form = {
      ...getDemoCampaignForm(demoLocale),
      imageFile,
    };
    state.imagePreviewUrl = URL.createObjectURL(imageFile);
    setStreamMessage("demoFilled");
  } catch {
    setStreamMessage("demoFillFailed");
  } finally {
    state.demoLoading = false;
    render();
  }
}

async function refreshHealth(): Promise<void> {
  state.health = await api.getHealth();
  render();
}

async function restoreCampaignFromBrowserState(): Promise<void> {
  const queryValue = new URLSearchParams(window.location.search).get("campaign");
  const storedValue = readBrowserStorageItem(window, LAST_CAMPAIGN_KEY);
  const campaignId = selectCampaignId(queryValue, storedValue);
  if (!campaignId) {
    return;
  }

  try {
    state.campaign = await api.getCampaign(campaignId);
    persistCampaignId(campaignId);
    setStreamMessage("restoredCampaign", { campaignId });
    if (["queued", "running"].includes(state.campaign.status)) {
      openProgressStream();
    }
  } catch (errorResponse) {
    if (!queryValue?.trim()) {
      removeBrowserStorageItem(window, LAST_CAMPAIGN_KEY);
    }
    if (errorResponse instanceof Error) {
      setStreamMessage("restoreFailedWithDetail", { message: errorResponse.message });
    } else {
      setStreamMessage("restoreFailed");
    }
  }
  render();
}

function persistCampaignId(campaignId: string): void {
  writeBrowserStorageItem(window, LAST_CAMPAIGN_KEY, campaignId);
  try {
    const url = new URL(window.location.href);
    url.searchParams.set("campaign", campaignId);
    window.history.replaceState({}, "", url);
  } catch {
    // URL persistence is optional and must not turn a successful request into a failure.
  }
}

async function createCampaign(): Promise<void> {
  if (state.demoLoading) {
    return;
  }

  const error = validateDescription(state.form.description, validationMessages[state.locale]);
  const imageError = validateProductImage(state.form.imageFile, validationMessages[state.locale]);
  const errorNode = document.querySelector<HTMLParagraphElement>("#form-error");

  if (error ?? imageError) {
    if (errorNode) {
      errorNode.textContent = error ?? imageError ?? "";
    }
    return;
  }

  state.busy = true;
  setStreamMessage("creatingCampaign");
  render();

  try {
    const response = await api.createCampaign(state.form);
    state.campaign = {
      ...createEmptyCampaign(),
      id: response.id,
      status: response.status ?? "queued",
      sequence: response.sequence ?? 0,
      summary: response.message,
    };
    persistCampaignId(response.id);
    setStreamMessage("campaignCreated");
    openProgressStream();
  } catch (errorResponse) {
    const message = errorResponse instanceof Error ? localizeStableError(state.locale, errorResponse.message) : t().campaignCreationFailed;
    state.campaign = api.createConnectionFailure(message, t().connectionFailureSummary);
    setStreamMessage("connectionFailed");
  } finally {
    state.busy = false;
    render();
  }
}

async function loadDetail(): Promise<void> {
  if (!state.campaign.id) {
    return;
  }

  state.busy = true;
  setStreamMessage("loadingDetail");
  render();

  try {
    state.campaign = await api.getCampaign(state.campaign.id);
    setStreamMessage("detailLoaded");
    openProgressStream();
  } catch (errorResponse) {
    const message = errorResponse instanceof Error ? localizeStableError(state.locale, errorResponse.message) : t().detailFailed;
    state.campaign = {
      ...state.campaign,
      status: state.campaign.status === "complete" ? "complete" : "partial",
      warnings: [...state.campaign.warnings, message],
    };
    setStreamMessage("detailUnavailable");
  } finally {
    state.busy = false;
    render();
  }
}

async function rerunCampaign(): Promise<void> {
  if (!state.campaign.id) {
    return;
  }

  setStreamMessage("requestingRerun");
  render();

  try {
    const response = await api.rerunCampaign(state.campaign.id, selectedRerunStage());
    state.campaign = {
      ...state.campaign,
      id: response.id,
      status: response.status ?? "queued",
      sequence: response.sequence ?? state.campaign.sequence,
      summary: response.message ?? state.campaign.summary,
    };
    openProgressStream();
  } catch (errorResponse) {
    addWarning(errorResponse instanceof Error ? localizeStableError(state.locale, errorResponse.message) : t().rerunFailed);
  }
}

async function cancelCampaign(): Promise<void> {
  if (!state.campaign.id) {
    return;
  }

  try {
    await api.cancelCampaign(state.campaign.id);
    closeStream();
    state.campaign = { ...state.campaign, status: "cancelled" };
    setStreamMessage("campaignCancelled");
  } catch (errorResponse) {
    addWarning(errorResponse instanceof Error ? localizeStableError(state.locale, errorResponse.message) : t().cancelFailed);
  }

  render();
}

async function exportCampaign(language?: LanguageCode): Promise<void> {
  if (!state.campaign.id) {
    return;
  }

  try {
    const blob = await api.exportCampaign(state.campaign.id, language);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `overseaark-${state.campaign.id}-${language ?? "all"}.zip`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (errorResponse) {
    addWarning(errorResponse instanceof Error ? localizeStableError(state.locale, errorResponse.message) : t().exportFailed);
  }
}

function openProgressStream(): void {
  if (!state.campaign.id) {
    return;
  }

  closeStream();
  state.stream = api.streamCampaign(
    state.campaign.id,
    state.campaign.sequence,
    (event) => {
      const nextCampaign = mergeCampaignEvent(state.campaign, event);
      if (nextCampaign === state.campaign) {
        return;
      }

      state.campaign = nextCampaign;
      setStreamMessage("progressUpdate", { sequence: state.campaign.sequence });
      if (isTerminalStatus()) {
        closeStream();
      }
      scheduleDetailRefresh(isTerminalStatus() ? 0 : 500);
      render();
    },
    (message) => {
      addWarning(localizeStableError(state.locale, message));
      if (["running", "queued"].includes(state.campaign.status)) {
        window.setTimeout(openProgressStream, 1500);
      }
    },
  );
}

function scheduleDetailRefresh(delay: number): void {
  if (!state.campaign.id) {
    return;
  }

  if (state.refreshTimer !== null) {
    window.clearTimeout(state.refreshTimer);
  }

  state.refreshTimer = window.setTimeout(() => {
    state.refreshTimer = null;
    void refreshDetailFromBackend();
  }, delay);
}

async function refreshDetailFromBackend(): Promise<void> {
  if (!state.campaign.id) {
    return;
  }

  const campaignId = state.campaign.id;
  const sequenceAtRequest = state.campaign.sequence;
  try {
    const detail = await api.getCampaign(campaignId);
    if (state.campaign.id !== campaignId || state.campaign.sequence > sequenceAtRequest) {
      return;
    }

    state.campaign = {
      ...detail,
      sequence: Math.max(detail.sequence, sequenceAtRequest),
    };
    setStreamMessage("detailRefreshed", { sequence: state.campaign.sequence });
    render();
  } catch (errorResponse) {
    if (state.campaign.id !== campaignId || state.campaign.sequence > sequenceAtRequest) {
      return;
    }

    addWarning(errorResponse instanceof Error ? localizeStableError(state.locale, errorResponse.message) : t().detailRefreshFailed);
  }
}

function closeStream(): void {
  state.stream?.close();
  state.stream = null;
}

function isTerminalStatus(): boolean {
  return ["complete", "partial", "failed", "cancelled"].includes(state.campaign.status);
}

function addWarning(message: string): void {
  if (!state.campaign.warnings.includes(message)) {
    state.campaign = {
      ...state.campaign,
      status: state.campaign.status === "complete" ? "complete" : "partial",
      warnings: [...state.campaign.warnings, message],
    };
  }

  state.streamMessage = { kind: "raw", text: message };
  render();
}

function setStreamMessage(
  key: StreamMessageKey,
  payload: Omit<Extract<StreamMessageState, { kind: "localized" }>, "kind" | "key"> = {},
): void {
  state.streamMessage = { kind: "localized", key, ...payload };
}

function canUseCampaignActions(): boolean {
  return Boolean(state.campaign.id && !state.busy);
}

function canCancel(): boolean {
  return canUseCampaignActions() && ["queued", "running", "partial"].includes(state.campaign.status);
}

function canExport(): boolean {
  return canUseCampaignActions() && ["complete", "partial"].includes(state.campaign.status);
}

function firstRerunnableStage(): string {
  return (
    [...state.campaign.stages].reverse().find((stage) =>
      ["failed", "partial", "complete", "cancelled"].includes(stage.state),
    )?.key ?? state.campaign.stages[0]?.key ?? "market_positioning"
  );
}

function selectedRerunStage(): CampaignStageKey {
  if (state.campaign.stages.some((stage) => stage.key === state.rerunStage)) {
    return state.rerunStage;
  }

  return firstRerunnableStage() as CampaignStageKey;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value: string): string {
  return escapeHtml(value);
}
