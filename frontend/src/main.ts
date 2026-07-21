import { ApiClient, type ProgressStream } from "./api.js";
import {
  LANGUAGE_LABELS,
  createEmptyCampaign,
  formatDateTime,
  mergeCampaignEvent,
  selectCampaignId,
  statusTone,
  validateDescription,
  validateProductImage,
} from "./campaign.js";
import type { CampaignDetail, CampaignFormData, CampaignStageKey, HealthStatus, LanguageCode } from "./types.js";
import "./styles.css";

const api = new ApiClient();
const LAST_CAMPAIGN_KEY = "overseaark.lastCampaignId";
const state: {
  form: CampaignFormData;
  campaign: CampaignDetail;
  health: HealthStatus | null;
  imagePreviewUrl: string;
  busy: boolean;
  stream: ProgressStream | null;
  streamMessage: string;
  selectedLanguage: LanguageCode;
  rerunStage: CampaignStageKey;
  refreshTimer: number | null;
} = {
  form: {
    name: "",
    description: "",
    sourceMarket: "",
    targetMarkets: "United States, Japan, Mainland China",
    transcription: "",
    targetLanguages: ["zh", "en", "ja"],
    imageFile: null,
  },
  campaign: createEmptyCampaign(),
  health: null,
  imagePreviewUrl: "",
  busy: false,
  stream: null,
  streamMessage: "No active stream.",
  selectedLanguage: "zh",
  rerunStage: "market_positioning",
  refreshTimer: null,
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
  app.innerHTML = `
    <main class="shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">OverseaArk</p>
          <h1>Cross-border campaign workbench</h1>
        </div>
        ${renderHealth()}
      </header>

      <section class="workspace" aria-label="Campaign workspace">
        <form class="panel composer" id="campaign-form">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Create</p>
              <h2>Product campaign</h2>
            </div>
            <button class="icon-button" type="button" id="refresh-health" aria-label="Refresh health and model status" title="Refresh status">↻</button>
          </div>

          <label class="field">
            <span>Campaign name</span>
            <input id="campaign-name" name="name" type="text" maxlength="120" placeholder="NVIDIA Jetson retail demo kit" value="${escapeHtml(state.form.name)}" />
          </label>

          <label class="field image-drop" for="product-image">
            <span>Product image</span>
            <input id="product-image" name="product_image" type="file" accept="image/jpeg,image/png,image/webp" />
            <div class="image-preview ${state.imagePreviewUrl ? "has-image" : ""}">
              ${
                state.imagePreviewUrl
                  ? `<img src="${state.imagePreviewUrl}" alt="Selected product preview" />`
                  : `<div><strong>Upload image</strong><small>PNG, JPG, or WebP product shot</small></div>`
              }
            </div>
          </label>

          <label class="field">
            <span>Product description <small>${state.form.description.trim().length}/2000</small></span>
            <textarea id="description" name="description" minlength="5" maxlength="2000" rows="8" placeholder="Describe product features, audience, price band, differentiators, and target region.">${escapeHtml(state.form.description)}</textarea>
          </label>

          <label class="field">
            <span>Audio transcription <small>optional</small></span>
            <textarea id="transcription" name="transcription" rows="4" placeholder="Paste voice note transcription or meeting summary.">${escapeHtml(state.form.transcription)}</textarea>
          </label>

          <label class="field">
            <span>Source market</span>
            <input id="source-market" name="sourceMarket" type="text" maxlength="120" placeholder="Mainland China" value="${escapeHtml(state.form.sourceMarket)}" />
          </label>

          <label class="field">
            <span>Target markets</span>
            <input id="target-markets" name="targetMarkets" type="text" maxlength="240" placeholder="United States, Japan, Mainland China" value="${escapeHtml(state.form.targetMarkets)}" />
          </label>

          <fieldset class="language-grid">
            <legend>Output languages</legend>
            ${(["zh", "en", "ja"] as LanguageCode[]).map(renderLanguageChoice).join("")}
          </fieldset>

          <div class="actions">
            <button class="primary" id="create-campaign" type="submit" ${state.busy ? "disabled" : ""}>Create campaign</button>
            <button type="button" id="load-detail" ${!state.campaign.id ? "disabled" : ""}>Load detail</button>
          </div>
          <p class="form-error" id="form-error" role="alert"></p>
        </form>

        <section class="panel progress-panel" aria-labelledby="progress-title">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Progress</p>
              <h2 id="progress-title">Six-stage pipeline</h2>
            </div>
            <span class="status ${statusTone(state.campaign.status)}">${state.campaign.status}</span>
          </div>
          <div class="stream-line" role="status" aria-live="polite">${escapeHtml(state.streamMessage)}</div>
          <ol class="stage-list">
            ${state.campaign.stages.map((stage, index) => `
              <li class="stage ${statusTone(stage.state)}">
                <div class="stage-index" aria-hidden="true">${index + 1}</div>
                <div>
                  <div class="stage-title">
                    <strong>${escapeHtml(stage.label)}</strong>
                    <span>${escapeHtml(stage.state)}</span>
                  </div>
                  <p>${escapeHtml(stage.description)}</p>
                  ${stage.detail ? `<small>${escapeHtml(stage.detail)}</small>` : ""}
                </div>
              </li>
            `).join("")}
          </ol>

          <div class="actions split">
            <select id="rerun-stage" aria-label="Stage to rerun" ${!canUseCampaignActions() ? "disabled" : ""}>
              ${state.campaign.stages.map((stage) => `
                <option value="${stage.key}" ${selectedRerunStage() === stage.key ? "selected" : ""}>${escapeHtml(stage.label)}</option>
              `).join("")}
            </select>
            <button type="button" id="rerun-campaign" ${!canUseCampaignActions() ? "disabled" : ""}>Rerun</button>
            <button type="button" id="cancel-campaign" ${!canCancel() ? "disabled" : ""}>Cancel</button>
            <button type="button" id="export-campaign" ${!canExport() ? "disabled" : ""}>Export</button>
          </div>
        </section>
      </section>

      <section class="detail-grid" aria-label="Campaign detail and artifacts">
        <article class="panel detail-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Detail</p>
              <h2>${state.campaign.id ? `Campaign ${escapeHtml(state.campaign.id)}` : "No campaign selected"}</h2>
            </div>
            <span class="sequence">Seq ${state.campaign.sequence}</span>
          </div>
          <dl class="meta-grid">
            <div><dt>Created</dt><dd>${escapeHtml(formatDateTime(state.campaign.createdAt))}</dd></div>
            <div><dt>Updated</dt><dd>${escapeHtml(formatDateTime(state.campaign.updatedAt))}</dd></div>
          </dl>
          <p class="summary">${escapeHtml(state.campaign.summary ?? "Campaign details will appear as the backend returns progress and artifacts.")}</p>
          ${renderStateMessages()}
        </article>

        <article class="panel artifacts-panel">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Artifacts</p>
              <h2>Localized outputs</h2>
            </div>
            <div class="tabs" role="tablist" aria-label="Artifact language">
              ${(["zh", "en", "ja"] as LanguageCode[]).map((language) => `
                <button type="button" class="${state.selectedLanguage === language ? "active" : ""}" data-language="${language}" role="tab" aria-selected="${state.selectedLanguage === language}">
                  ${LANGUAGE_LABELS[language]}
                </button>
              `).join("")}
            </div>
          </div>
          <div class="artifact-stack">
            ${renderArtifacts()}
          </div>
        </article>
      </section>
    </main>
  `;

  bindEvents();
}

function renderHealth(): string {
  if (!state.health) {
    return `<aside class="health unknown" aria-live="polite"><strong>Checking</strong><span>Model status pending</span></aside>`;
  }

  return `
    <aside class="health ${state.health.ok ? "online" : "offline"}" aria-live="polite">
      <strong>API ${state.health.api}</strong>
      <span>Model ${state.health.model}</span>
      <small>${escapeHtml(state.health.detail)}</small>
    </aside>
  `;
}

function renderLanguageChoice(language: LanguageCode): string {
  const checked = state.form.targetLanguages.includes(language) ? "checked" : "";
  return `
    <label>
      <input type="checkbox" name="language" value="${language}" ${checked} />
      <span>${LANGUAGE_LABELS[language]}</span>
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
  const artifacts = state.campaign.artifacts.filter((artifact) => artifact.language === state.selectedLanguage);

  if (artifacts.length === 0) {
    return `<p class="empty">No ${LANGUAGE_LABELS[state.selectedLanguage]} artifacts yet.</p>`;
  }

  return artifacts.map((artifact) => `
    <section class="artifact">
      <div>
        <strong>${escapeHtml(artifact.title)}</strong>
        <span>${escapeHtml(artifact.kind)} · ${escapeHtml(artifact.quality ?? "final")}</span>
      </div>
      <pre>${escapeHtml(artifact.content)}</pre>
    </section>
  `).join("");
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

  document.querySelector<HTMLInputElement>("#product-image")?.addEventListener("change", (event) => {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    state.form.imageFile = file;
    if (state.imagePreviewUrl) {
      URL.revokeObjectURL(state.imagePreviewUrl);
    }
    state.imagePreviewUrl = file ? URL.createObjectURL(file) : "";
    render();
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

  document.querySelector("#export-campaign")?.addEventListener("click", () => {
    void exportCampaign();
  });

  document.querySelectorAll<HTMLButtonElement>("[data-language]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedLanguage = button.dataset.language as LanguageCode;
      render();
    });
  });
}

async function refreshHealth(): Promise<void> {
  state.health = await api.getHealth();
  render();
}

async function restoreCampaignFromBrowserState(): Promise<void> {
  const queryValue = new URLSearchParams(window.location.search).get("campaign");
  const storedValue = window.localStorage.getItem(LAST_CAMPAIGN_KEY);
  const campaignId = selectCampaignId(queryValue, storedValue);
  if (!campaignId) {
    return;
  }

  try {
    state.campaign = await api.getCampaign(campaignId);
    persistCampaignId(campaignId);
    state.streamMessage = `Restored campaign ${campaignId}.`;
    if (["queued", "running"].includes(state.campaign.status)) {
      openProgressStream();
    }
  } catch (errorResponse) {
    if (!queryValue?.trim()) {
      window.localStorage.removeItem(LAST_CAMPAIGN_KEY);
    }
    state.streamMessage = errorResponse instanceof Error
      ? `Stored campaign could not be restored: ${errorResponse.message}`
      : "Stored campaign could not be restored.";
  }
  render();
}

function persistCampaignId(campaignId: string): void {
  window.localStorage.setItem(LAST_CAMPAIGN_KEY, campaignId);
  const url = new URL(window.location.href);
  url.searchParams.set("campaign", campaignId);
  window.history.replaceState({}, "", url);
}

async function createCampaign(): Promise<void> {
  const error = validateDescription(state.form.description);
  const imageError = validateProductImage(state.form.imageFile);
  const errorNode = document.querySelector<HTMLParagraphElement>("#form-error");

  if (error ?? imageError) {
    if (errorNode) {
      errorNode.textContent = error ?? imageError ?? "";
    }
    return;
  }

  state.busy = true;
  state.streamMessage = "Creating campaign...";
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
    state.streamMessage = "Campaign created. Opening progress stream...";
    openProgressStream();
  } catch (errorResponse) {
    const message = errorResponse instanceof Error ? errorResponse.message : "Campaign creation failed.";
    state.campaign = api.createConnectionFailure(message);
    state.streamMessage = "Connection failed. No local campaign was generated.";
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
  state.streamMessage = "Loading campaign detail...";
  render();

  try {
    state.campaign = await api.getCampaign(state.campaign.id);
    state.streamMessage = "Campaign detail loaded.";
    openProgressStream();
  } catch (errorResponse) {
    const message = errorResponse instanceof Error ? errorResponse.message : "Campaign detail failed.";
    state.campaign = {
      ...state.campaign,
      status: state.campaign.status === "complete" ? "complete" : "partial",
      warnings: [...state.campaign.warnings, message],
    };
    state.streamMessage = "Detail unavailable; existing progress is preserved.";
  } finally {
    state.busy = false;
    render();
  }
}

async function rerunCampaign(): Promise<void> {
  if (!state.campaign.id) {
    return;
  }

  state.streamMessage = "Requesting rerun...";
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
    addWarning(errorResponse instanceof Error ? errorResponse.message : "Rerun failed.");
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
    state.streamMessage = "Campaign cancelled.";
  } catch (errorResponse) {
    addWarning(errorResponse instanceof Error ? errorResponse.message : "Cancel failed.");
  }

  render();
}

async function exportCampaign(): Promise<void> {
  if (!state.campaign.id) {
    return;
  }

  try {
    const blob = await api.exportCampaign(state.campaign.id);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `overseaark-${state.campaign.id}.zip`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (errorResponse) {
    addWarning(errorResponse instanceof Error ? errorResponse.message : "Export failed.");
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
      state.campaign = mergeCampaignEvent(state.campaign, event);
      state.streamMessage = `Progress update received at sequence ${state.campaign.sequence}.`;
      if (isTerminalStatus()) {
        closeStream();
      }
      scheduleDetailRefresh(isTerminalStatus() ? 0 : 500);
      render();
    },
    (message) => {
      addWarning(message);
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

  try {
    state.campaign = await api.getCampaign(state.campaign.id);
    state.streamMessage = `Campaign detail refreshed at sequence ${state.campaign.sequence}.`;
    render();
  } catch (errorResponse) {
    addWarning(errorResponse instanceof Error ? errorResponse.message : "Detail refresh failed.");
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

  state.streamMessage = message;
  render();
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
