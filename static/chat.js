const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const STORAGE_KEY = "relationship-gallup-chat-v1";
const MODEL_STORAGE_KEY = "relationship-ai-model-v1";
const SPEAKER_STORAGE_KEY = "relationship-chat-speaker-v1";
const PARTICIPANTS = [
  { id: "xiaoli", name: "小娌" },
  { id: "xiaoyuan", name: "小元" },
];
const PARTICIPANT_BY_ID = Object.fromEntries(PARTICIPANTS.map((item) => [item.id, item]));
const state = loadState();

document.addEventListener("DOMContentLoaded", () => {
  setupChatTabs();
  setupSpeakerPicker();
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

function setupSpeakerPicker() {
  const select = $("#chatSpeaker");
  const stored = localStorage.getItem(SPEAKER_STORAGE_KEY);
  select.value = PARTICIPANT_BY_ID[stored] ? stored : "xiaoli";
  select.addEventListener("change", () => {
    localStorage.setItem(SPEAKER_STORAGE_KEY, select.value);
  });
}

function currentSpeakerId() {
  return PARTICIPANT_BY_ID[$("#chatSpeaker")?.value]?.id || "xiaoli";
}

function setupChatTabs() {
  $$('[data-chat-view]').forEach((button) => {
    button.addEventListener("click", () => {
      $$('[data-chat-view]').forEach((item) => {
        const active = item.dataset.chatView === button.dataset.chatView;
        item.classList.toggle("active", active);
        item.setAttribute("aria-selected", String(active));
      });
      $$('[data-chat-panel]').forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.chatPanel === button.dataset.chatView);
      });
    });
  });
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("#chatInput");
  const message = input.value.trim();
  if (!message || state.pending) return;

  const priorHistory = state.history.slice(-12);
  const speakerId = currentSpeakerId();
  state.history.push({ role: "user", content: message, participant_id: speakerId });
  appendMessage("user", message, false, speakerId);
  input.value = "";
  setPending(true, "正在结合才干画像和历史案例分析……");
  persistState();

  const assistantArticle = appendMessage("assistant", "");
  let streamedReply = "";
  let finalData = null;
  try {
    await streamJsonEvents("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: state.conversationId,
        turn_id: makeId(),
        speaker_id: speakerId,
        message,
        history: priorHistory,
        model: $("#chatModel")?.value || "",
      }),
    }, (event) => {
      if (event.type === "meta") {
        state.conversationId = event.conversation_id || state.conversationId;
        setPending(true, "模型正在输出分析……");
      } else if (event.type === "delta") {
        streamedReply += event.text || "";
        updateMessage(assistantArticle, streamedReply);
      } else if (event.type === "status") {
        setPending(true, event.message || "正在整理结果……");
      } else if (event.type === "final") {
        finalData = event;
        streamedReply = event.reply || streamedReply;
        updateMessage(assistantArticle, streamedReply);
        if (event.analysis_saved) markMessageSaved(assistantArticle);
      } else if (event.type === "error") {
        throw new Error(event.error || "请求失败，请稍后重试。");
      }
    });

    if (!finalData) throw new Error("模型流式输出没有正常结束。");
    state.conversationId = finalData.conversation_id || state.conversationId;
    state.history.push({ role: "assistant", content: streamedReply });
    persistState();
    if (finalData.analysis_saved) {
      showToast("本次精炼分析已写入长期复盘库");
      await Promise.all([loadRecords(), loadProgress()]);
    }
  } catch (error) {
    if (!streamedReply) assistantArticle.remove();
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

function appendMessage(role, content, saved = false, participantId = "") {
  const article = document.createElement("article");
  const type = role === "user" ? "user" : role === "error" ? "error" : "assistant";
  article.className = `chat-message ${type}-message`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  const participant = PARTICIPANT_BY_ID[participantId] || PARTICIPANT_BY_ID.xiaoli;
  avatar.textContent = type === "user" ? participant.name.slice(-1) : type === "error" ? "!" : "析";
  if (type === "user") avatar.title = participant.name;

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  if (type === "user") {
    const author = document.createElement("span");
    author.className = "message-author";
    author.textContent = participant.name;
    bubble.appendChild(author);
  }
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
  return article;
}

function updateMessage(article, content) {
  const copy = $(".message-copy", article);
  if (!copy) return;
  copy.textContent = content || " ";
  article.scrollIntoView({ behavior: "smooth", block: "end" });
}

function markMessageSaved(article) {
  const bubble = $(".message-bubble", article);
  if (!bubble || $(".saved-badge", bubble)) return;
  const badge = document.createElement("span");
  badge.className = "saved-badge";
  badge.textContent = "已精炼入库";
  bubble.appendChild(badge);
}

function renderStoredConversation() {
  state.history.forEach((item) => appendMessage(item.role, item.content, false, item.participant_id));
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
  container.innerHTML = records.map(memoryCard).join("");
  $$('[data-delete-record]', container).forEach((button) => {
    button.addEventListener("click", () => deleteRecord(button.dataset.deleteRecord));
  });
}

function memoryCard(record) {
  const scores = (record.participants || [])
    .filter((item) => item.behavior?.score != null)
    .map((item) => `${escapeHtml(item.participant?.name)} ${Number(item.behavior.score)}`)
    .join(" · ");
  const participantDetails = (record.participants || []).map((item) => `
    <section class="participant-memory">
      <h4>${escapeHtml(item.participant?.name || "未命名")}</h4>
      ${detailRow("本次角色", item.role_in_event)}
      ${detailRow("内在期待", item.inner_expectation)}
      ${detailRow("才干状态", item.talent_state)}
      ${detailRow("行为反馈", item.behavior?.feedback)}
      ${detailRow("评分依据", item.behavior?.score_reason)}
    </section>
  `).join("");
  const interaction = record.interaction || {};
  return `
    <details class="memory-card">
      <summary>
        <span class="memory-title"><b>${escapeHtml(record.question_summary)}</b><small>${escapeHtml(formatDate(record.created_at))} · ${escapeHtml(record.scene_type || "其他")}</small></span>
        ${scores ? `<span class="score-badge">${scores}</span>` : ""}
      </summary>
      <div class="memory-detail">
        ${participantDetails}
        ${detailRow("互动循环", interaction.loop)}
        ${detailRow("建议怎么说", interaction.recommended_wording)}
        ${detailRow("进步判断", interaction.progress_assessment)}
        ${detailRow("下一步", interaction.next_action)}
        <div class="keyword-row">${(record.keywords || []).map((keyword) => `<span>${escapeHtml(keyword)}</span>`).join("")}</div>
        <button class="delete-memory" type="button" data-delete-record="${record.id}">删除这条</button>
      </div>
    </details>
  `;
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
  const participants = Array.isArray(data.participants) ? data.participants : [];
  if (!participants.some((item) => item.recent_average != null)) {
    summary.className = "progress-summary empty-state";
    summary.textContent = "小娌与小元还没有可评分的完整分析";
    $("#progressBars").innerHTML = "";
    return;
  }
  summary.className = "progress-summary participant-progress-summary";
  summary.innerHTML = participants.map((item) => {
    const delta = item.delta == null ? "基线建立中" : `${item.delta > 0 ? "+" : ""}${item.delta}`;
    return `<div><span>${escapeHtml(item.participant?.name)}</span><strong>${item.recent_average ?? "—"}</strong><small>${escapeHtml(item.trend)} · ${escapeHtml(delta)}</small></div>`;
  }).join("");
  $("#progressBars").innerHTML = participants.map((participant) => `
    <div class="participant-progress-row">
      <b>${escapeHtml(participant.participant?.name)}</b>
      <div class="progress-bars">${(participant.items || []).slice(-12).map((item) => `
        <span style="--score:${Number(item.score)}" title="${escapeHtml(formatDate(item.created_at))} · ${escapeHtml(item.question_summary)} · ${item.score}/10"></span>
      `).join("")}</div>
    </div>
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

async function streamJsonEvents(url, options, onEvent) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `请求失败：${response.status}`);
  }
  if (!response.body?.getReader) {
    const text = await response.text();
    text.split(/\r?\n/).filter(Boolean).forEach((line) => onEvent(JSON.parse(line)));
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex >= 0) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) onEvent(JSON.parse(line));
      newlineIndex = buffer.indexOf("\n");
    }
    if (done) break;
  }
  const line = buffer.trim();
  if (line) onEvent(JSON.parse(line));
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
