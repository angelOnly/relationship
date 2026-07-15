const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const STORAGE_KEY = "relationship-gallup-chat-v1";
const MODEL_STORAGE_KEY = "relationship-ai-model-v1";
const state = loadState();

document.addEventListener("DOMContentLoaded", () => {
  bindChat();
  renderStoredConversation();
  setupModelPicker();
  Promise.all([loadRecords(), loadProgress()]);
});

function bindChat() {
  $("#chatForm").addEventListener("submit", sendMessage);
  $("#newChat").addEventListener("click", resetConversation);
  $$("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      $("#chatInput").value = button.dataset.prompt;
      $("#chatInput").focus();
    });
  });

  let searchTimer;
  $("#memorySearch").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadRecords, 250);
  });
  $("#sceneFilter").addEventListener("change", loadRecords);
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("#chatInput");
  const message = input.value.trim();
  if (!message || state.pending) return;

  const priorHistory = state.history.slice(-12);
  state.history.push({ role: "user", content: message });
  appendMessage("user", message);
  input.value = "";
  setPending(true, "正在结合才干画像和历史案例分析……");
  persistState();

  try {
    const data = await fetchJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: state.conversationId,
        turn_id: makeId(),
        message,
        history: priorHistory,
        model: $("#chatModel")?.value || "",
      }),
    });
    state.conversationId = data.conversation_id;
    state.history.push({ role: "assistant", content: data.reply });
    appendMessage("assistant", data.reply, data.analysis_saved);
    persistState();
    if (data.analysis_saved) {
      showToast("本次精炼分析已写入长期复盘库");
      await Promise.all([loadRecords(), loadProgress()]);
    }
  } catch (error) {
    appendMessage("error", error.message || "请求失败，请稍后重试。");
  } finally {
    setPending(false, "一次只分析一个具体事件");
    input.focus();
  }
}

async function setupModelPicker() {
  const select = $("#chatModel");
  const hint = $("#chatModelHint");
  try {
    const catalog = await fetchJson("/api/models");
    select.innerHTML = catalog.models.map((item) => (
      `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)} · ${escapeHtml(item.description || "")}</option>`
    )).join("");
    const stored = localStorage.getItem(MODEL_STORAGE_KEY);
    select.value = catalog.models.some((item) => item.key === stored) ? stored : catalog.default;
    updateModelHint(catalog, select.value, hint);
    select.addEventListener("change", () => {
      localStorage.setItem(MODEL_STORAGE_KEY, select.value);
      updateModelHint(catalog, select.value, hint);
    });
    if (!catalog.configured) hint.textContent = "服务端尚未完成模型密钥配置";
  } catch (error) {
    select.innerHTML = '<option value="">使用服务端默认模型</option>';
    hint.textContent = error.message || "模型列表读取失败";
  }
}

function updateModelHint(catalog, key, target) {
  const item = catalog.models.find((model) => model.key === key);
  if (!item) return;
  target.textContent = item.key === item.model ? `模型标识：${item.model}` : `接口实际调用：${item.model}`;
}

function appendMessage(role, content, saved = false) {
  const article = document.createElement("article");
  const type = role === "user" ? "user" : role === "error" ? "error" : "assistant";
  article.className = `chat-message ${type}-message`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = type === "user" ? "我" : type === "error" ? "!" : "析";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  const copy = document.createElement("div");
  copy.className = "message-copy";
  copy.textContent = content;
  bubble.appendChild(copy);
  if (saved) {
    const badge = document.createElement("span");
    badge.className = "saved-badge";
    badge.textContent = "已精炼入库";
    bubble.appendChild(badge);
  }
  article.append(avatar, bubble);
  $("#chatMessages").appendChild(article);
  article.scrollIntoView({ behavior: "smooth", block: "end" });
}

function renderStoredConversation() {
  state.history.forEach((item) => appendMessage(item.role, item.content));
}

function resetConversation() {
  if (state.history.length && !confirm("开始新场景？当前原始对话会从浏览器会话中清除，已精炼记录不受影响。")) return;
  state.conversationId = makeId();
  state.history = [];
  sessionStorage.removeItem(STORAGE_KEY);
  $$("#chatMessages .chat-message:not(.welcome-message)").forEach((item) => item.remove());
  $("#chatInput").value = "";
  $("#chatInput").focus();
}

async function loadRecords() {
  const params = new URLSearchParams({ limit: "40" });
  const q = $("#memorySearch")?.value.trim();
  const scene = $("#sceneFilter")?.value;
  if (q) params.set("q", q);
  if (scene) params.set("scene", scene);
  try {
    const records = await fetchJson(`/api/analysis-records?${params}`);
    renderRecords(records);
  } catch (error) {
    $("#memoryList").className = "memory-list empty-state";
    $("#memoryList").textContent = error.message;
  }
}

function renderRecords(records) {
  $("#recordCount").textContent = `${records.length} 条`;
  const container = $("#memoryList");
  if (!records.length) {
    container.className = "memory-list empty-state";
    container.textContent = "没有匹配的精炼案例";
    return;
  }
  container.className = "memory-list";
  container.innerHTML = records.map((record) => `
    <details class="memory-card">
      <summary>
        <span class="memory-title"><b>${escapeHtml(record.question_summary)}</b><small>${escapeHtml(formatDate(record.created_at))} · ${escapeHtml(record.scene_type || "其他")}</small></span>
        ${record.behavior_score ? `<span class="score-badge">${record.behavior_score}/10</span>` : ""}
      </summary>
      <div class="memory-detail">
        ${detailRow("你的期待", record.inner_expectation_me)}
        ${detailRow("对方期待", record.inner_expectation_partner)}
        ${detailRow("你的才干状态", record.talent_state_me)}
        ${detailRow("对方才干状态", record.talent_state_partner)}
        ${detailRow("建议怎么说", record.recommended_wording)}
        ${detailRow("行为反馈", record.behavior_feedback)}
        ${detailRow("进步判断", record.progress_assessment)}
        ${detailRow("下一步", record.next_action)}
        <div class="keyword-row">${(record.keywords || []).map((keyword) => `<span>${escapeHtml(keyword)}</span>`).join("")}</div>
        <button class="delete-memory" type="button" data-delete-record="${record.id}">删除这条</button>
      </div>
    </details>
  `).join("");
  $$('[data-delete-record]', container).forEach((button) => {
    button.addEventListener("click", () => deleteRecord(button.dataset.deleteRecord));
  });
}

async function deleteRecord(id) {
  if (!confirm("确定删除这条精炼分析吗？此操作不能撤销。")) return;
  await fetchJson(`/api/analysis-records/${id}`, { method: "DELETE" });
  await Promise.all([loadRecords(), loadProgress()]);
  showToast("记录已删除");
}

async function loadProgress() {
  try {
    const data = await fetchJson("/api/progress");
    renderProgress(data);
  } catch (error) {
    $("#progressSummary").textContent = error.message;
  }
}

function renderProgress(data) {
  const summary = $("#progressSummary");
  if (data.recent_average == null) {
    summary.className = "progress-summary empty-state";
    summary.textContent = "还没有可评分的完整分析";
    $("#progressBars").innerHTML = "";
    return;
  }
  summary.className = "progress-summary";
  const delta = data.delta == null ? "基线建立中" : `${data.delta > 0 ? "+" : ""}${data.delta}`;
  summary.innerHTML = `<strong>${data.recent_average}</strong><span>最近平均 / 10</span><b>${escapeHtml(data.trend)} · ${escapeHtml(delta)}</b>`;
  $("#progressBars").innerHTML = (data.items || []).slice(-12).map((item) => `
    <span style="--score:${Number(item.behavior_score)}" title="${escapeHtml(formatDate(item.created_at))} · ${escapeHtml(item.question_summary)} · ${item.behavior_score}/10"></span>
  `).join("");
}

function detailRow(label, value) {
  if (!value) return "";
  return `<div class="memory-row"><b>${label}</b><p>${escapeHtml(value)}</p></div>`;
}

function setPending(pending, message) {
  state.pending = pending;
  $("#sendChat").disabled = pending;
  $("#chatInput").disabled = pending;
  $("#chatStatus").textContent = message;
  $("#chatStatus").classList.toggle("thinking", pending);
}

function loadState() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
    if (saved && Array.isArray(saved.history) && saved.conversationId) {
      return { conversationId: saved.conversationId, history: saved.history.slice(-12), pending: false };
    }
  } catch (_) {}
  return { conversationId: makeId(), history: [], pending: false };
}

function persistState() {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
    conversationId: state.conversationId,
    history: state.history.slice(-12),
  }));
}

function makeId() {
  return globalThis.crypto?.randomUUID?.().replaceAll("-", "") || `${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `请求失败：${response.status}`);
  return body;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2200);
}

function formatDate(value) {
  return String(value || "").replace("T", " ").slice(0, 16);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
