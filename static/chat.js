const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const CHAT_STORAGE_KEY = "relationship-coach-chat-v2";
const MODE_STORAGE_KEY = "relationship-coach-mode-v2";
const MODEL_STORAGE_KEY = "relationship-ai-model-v1";
const FAST_MODEL_KEY = "gemini-3.5-flash-high";
const SPEAKER_STORAGE_KEY = "relationship-chat-speaker-v1";
const ACTIVE_PRACTICE_KEY = "relationship-active-practice-v1";
const PARTICIPANTS = [
  { id: "xiaoli", name: "小娌" },
  { id: "xiaoyuan", name: "小元" },
];
const PARTICIPANT_BY_ID = Object.fromEntries(PARTICIPANTS.map((item) => [item.id, item]));
const MODE_CONFIG = {
  qa: {
    title: "直接问答",
    eyebrow: "直接回答 · 不强套画像 · 不入库",
    speakerLabel: "当前提问者",
    status: "先直接问一个具体问题",
    placeholder: "例如：为什么我明明想被安慰，却总是把话说成指责？",
    button: "发送",
    newLabel: "新问题",
    welcomeTitle: "直接问你真正想知道的",
    welcome: "只想知道这件事怎么看、怎么办，就在这里问。AI 会直接回答；只有明确问到盖洛普或才干时才使用画像。回答仅保留在当前浏览器会话。",
    prompts: [
      ["为什么越解释越生气？", "为什么我们一有分歧，我越解释，对方反而越生气？"],
      ["怎么表达边界？", "我想拒绝一件事，又不想变成指责，应该怎么表达边界？"],
      ["先安慰还是解决？", "伴侣倾诉时，怎么判断对方此刻需要共情还是解决方案？"],
    ],
  },
};

const state = loadChatState();
const practiceState = { session: null, pending: false };
let modelCatalog = null;

document.addEventListener("DOMContentLoaded", async () => {
  setupChatTabs();
  setupSpeakerPicker();
  bindCommonEvents();
  setCoachMode(localStorage.getItem(MODE_STORAGE_KEY) || "qa", { restore: true });
  await setupModelPicker();
  await Promise.all([loadPracticeHistory(), loadStrategyStats()]);
  await restoreActivePractice();
});

function bindCommonEvents() {
  $("#chatForm").addEventListener("submit", sendMessage);
  $("#newChat").addEventListener("click", resetConversation);
  $$('[data-coach-mode]').forEach((button) => button.addEventListener("click", () => setCoachMode(button.dataset.coachMode)));
  $("#startPractice").addEventListener("click", startPractice);
  $("#outcomeForm").addEventListener("submit", submitOutcome);
  $$('[data-close-dialog]').forEach((button) => button.addEventListener("click", () => $("#outcomeDialog").close()));

}

function setupSpeakerPicker() {
  const select = $("#chatSpeaker");
  const stored = localStorage.getItem(SPEAKER_STORAGE_KEY);
  select.value = PARTICIPANT_BY_ID[stored] ? stored : "xiaoli";
  select.addEventListener("change", () => localStorage.setItem(SPEAKER_STORAGE_KEY, select.value));
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
      $$('[data-chat-panel]').forEach((panel) => panel.classList.toggle("active", panel.dataset.chatPanel === button.dataset.chatView));
    });
  });
}

function setCoachMode(mode, { restore = false } = {}) {
  if (!MODE_CONFIG[mode] && mode !== "practice") mode = "qa";
  state.mode = mode;
  localStorage.setItem(MODE_STORAGE_KEY, mode);
  syncModelPicker();
  $$('[data-coach-mode]').forEach((button) => {
    const active = button.dataset.coachMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const isPractice = mode === "practice";
  $("#chatWorkspace").hidden = isPractice;
  $("#practiceWorkspace").hidden = !isPractice;
  $("#newChat").hidden = isPractice;

  if (isPractice) {
    $("#coachModeTitle").textContent = "表达练习";
    $("#coachModeEyebrow").textContent = "写下原话 · 换位理解 · 学会改写";
    $("#speakerLabel").textContent = "练习者";
    if (practiceState.session) renderPracticeSession(practiceState.session);
    else showPracticeSetup();
    return;
  }
  const config = MODE_CONFIG[mode];
  $("#coachModeTitle").textContent = config.title;
  $("#coachModeEyebrow").textContent = config.eyebrow;
  $("#speakerLabel").textContent = config.speakerLabel;
  $("#chatInput").placeholder = config.placeholder;
  $("#sendChat").textContent = config.button;
  $("#newChat").textContent = config.newLabel;
  $("#chatStatus").textContent = config.status;
  renderPromptChips(config.prompts);
  renderConversation();
  if (!restore) $("#chatInput").focus();
}

function renderPromptChips(prompts) {
  const container = $("#promptChips");
  container.innerHTML = prompts.map(([label, prompt]) => `<button type="button" data-prompt="${escapeHtml(prompt)}">${escapeHtml(label)}</button>`).join("");
  $$('[data-prompt]', container).forEach((button) => button.addEventListener("click", () => {
    $("#chatInput").value = button.dataset.prompt;
    $("#chatInput").focus();
  }));
}

function currentConversation() {
  return state.conversations[state.mode];
}

function renderConversation() {
  const config = MODE_CONFIG[state.mode];
  const container = $("#chatMessages");
  container.innerHTML = `
    <article class="chat-message assistant-message welcome-message">
      <div class="message-avatar">${state.mode === "qa" ? "问" : "析"}</div>
      <div class="message-bubble"><b>${escapeHtml(config.welcomeTitle)}</b><div class="message-copy">${escapeHtml(config.welcome)}</div></div>
    </article>`;
  currentConversation().history.forEach((item) => appendMessage(item.role, item.content, false, item.participant_id, item.sources));
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("#chatInput");
  const message = input.value.trim();
  if (!message || state.pending || state.mode === "practice") return;
  const requestMode = state.mode;
  const conversation = currentConversation();
  const priorHistory = conversation.history.slice(-12);
  const speakerId = currentSpeakerId();
  conversation.history.push({ role: "user", content: message, participant_id: speakerId });
  appendMessage("user", message, false, speakerId);
  input.value = "";
  setChatPending(true, "正在整理依据并回答……");
  persistChatState();

  const assistantArticle = appendMessage("assistant", "");
  let streamedReply = "";
  let finalData = null;
  try {
    await streamJsonEvents("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: requestMode,
        conversation_id: conversation.id,
        turn_id: makeId(),
        speaker_id: speakerId,
        message,
        history: priorHistory,
        model: $("#chatModel")?.value || "",
      }),
    }, (streamEvent) => {
      if (streamEvent.type === "meta") {
        conversation.id = streamEvent.conversation_id || conversation.id;
      } else if (streamEvent.type === "delta") {
        streamedReply += streamEvent.text || "";
        updateMessage(assistantArticle, streamedReply);
      } else if (streamEvent.type === "status") {
        setChatPending(true, streamEvent.message || "正在整理结果……");
      } else if (streamEvent.type === "final") {
        finalData = streamEvent;
        streamedReply = streamEvent.reply || streamedReply;
        updateMessage(assistantArticle, streamedReply);
        renderSourceLabels(assistantArticle, streamEvent.source_labels || []);
      } else if (streamEvent.type === "error") {
        throw new Error(streamEvent.error || "请求失败，请稍后重试。");
      }
    });
    if (!finalData) throw new Error("模型输出没有正常结束。");
    conversation.id = finalData.conversation_id || conversation.id;
    conversation.history.push({ role: "assistant", content: streamedReply, sources: finalData.source_labels || [] });
    persistChatState();
  } catch (error) {
    if (!streamedReply) assistantArticle.remove();
    appendMessage("error", error.message || "请求失败，请稍后重试。");
  } finally {
    setChatPending(false, MODE_CONFIG[requestMode].status);
    input.focus();
  }
}

async function setupModelPicker() {
  const select = $("#chatModel");
  const hint = $("#chatModelHint");
  try {
    modelCatalog = await fetchJson("/api/models");
    select.innerHTML = modelCatalog.models.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)} · ${escapeHtml(item.description || "")}</option>`).join("");
    syncModelPicker();
    select.addEventListener("change", () => {
      localStorage.setItem(`${MODEL_STORAGE_KEY}-${state.mode}`, select.value);
      updateModelHint(modelCatalog, select.value, hint);
    });
    if (!modelCatalog.configured) hint.textContent = "服务端尚未完成模型密钥配置";
  } catch (error) {
    select.innerHTML = '<option value="">使用服务端默认模型</option>';
    hint.textContent = error.message || "模型列表读取失败";
  }
}

function syncModelPicker() {
  if (!modelCatalog) return;
  const select = $("#chatModel");
  const stored = localStorage.getItem(`${MODEL_STORAGE_KEY}-${state.mode}`);
  const fallback = modelCatalog.models.some((item) => item.key === FAST_MODEL_KEY)
    ? FAST_MODEL_KEY
    : modelCatalog.default;
  select.value = modelCatalog.models.some((item) => item.key === stored) ? stored : fallback;
  updateModelHint(modelCatalog, select.value, $("#chatModelHint"));
}

function updateModelHint(catalog, key, target) {
  const item = catalog.models.find((model) => model.key === key);
  if (item) target.textContent = item.key === item.model ? `模型标识：${item.model}` : `接口实际调用：${item.model}`;
}

function appendMessage(role, content, saved = false, participantId = "", sources = []) {
  const article = document.createElement("article");
  const type = role === "user" ? "user" : role === "error" ? "error" : "assistant";
  article.className = `chat-message ${type}-message`;
  const participant = PARTICIPANT_BY_ID[participantId] || PARTICIPANT_BY_ID.xiaoli;
  article.innerHTML = `
    <div class="message-avatar">${type === "user" ? escapeHtml(participant.name.slice(-1)) : type === "error" ? "!" : state.mode === "qa" ? "问" : "析"}</div>
    <div class="message-bubble">
      ${type === "user" ? `<span class="message-author">${escapeHtml(participant.name)}</span>` : ""}
      <div class="message-copy">${escapeHtml(content)}</div>
      ${saved ? '<span class="saved-badge">已精炼入库</span>' : ""}
    </div>`;
  $("#chatMessages").appendChild(article);
  renderSourceLabels(article, sources);
  article.scrollIntoView({ behavior: "smooth", block: "end" });
  return article;
}

function updateMessage(article, content) {
  const copy = $(".message-copy", article);
  if (copy) copy.textContent = content || " ";
  article.scrollIntoView({ behavior: "smooth", block: "end" });
}

function renderSourceLabels(article, sources) {
  if (!Array.isArray(sources) || !sources.length) return;
  const bubble = $(".message-bubble", article);
  const previous = $(".source-labels", bubble);
  if (previous) previous.remove();
  const labels = document.createElement("div");
  labels.className = "source-labels";
  labels.innerHTML = sources.map((item) => `<span title="${escapeHtml(item.reference_id || "")}">${escapeHtml(item.label || sourceTypeLabel(item.type))}</span>`).join("");
  bubble.appendChild(labels);
}

function sourceTypeLabel(type) {
  return ({ confirmed_success: "现实验证有效", gallup_profile: "盖洛普画像假设", communication_method: "沟通方法", regulation_method: "情绪调节方法", current_event: "本次事实", model_hypothesis: "待验证推测" })[type] || "回答依据";
}

function resetConversation() {
  const conversation = currentConversation();
  if (conversation.history.length && !confirm("开始新问题？当前原始对话会从浏览器会话中清除。")) return;
  conversation.id = makeId();
  conversation.history = [];
  persistChatState();
  renderConversation();
  $("#chatInput").value = "";
  $("#chatInput").focus();
}

async function startPractice() {
  const topic = $("#practiceTopic").value.trim();
  const expression = $("#practiceExpression").value.trim();
  const goal = $("#practiceGoal").value;
  if (!topic) return showToast("请先写下你想练习表达的那件事");
  if (!expression) return showToast("请先写下你当时说的话，或平时会怎么说");
  setPracticePending(true);
  try {
    const session = await fetchJson("/api/practice-sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        speaker_id: currentSpeakerId(),
        scene_type: $("#practiceScene").value,
        topic_summary: topic,
        goal,
        initial_expression: expression,
        model: $("#chatModel").value,
      }),
    });
    practiceState.session = session;
    localStorage.setItem(ACTIVE_PRACTICE_KEY, String(session.id));
    renderPracticeSession(session);
    await Promise.all([loadPracticeHistory(), loadStrategyStats()]);
  } catch (error) {
    showToast(error.message);
  } finally {
    setPracticePending(false);
  }
}

async function restoreActivePractice() {
  const id = localStorage.getItem(ACTIVE_PRACTICE_KEY);
  if (!id) return;
  try {
    const session = await fetchJson(`/api/practice-sessions/${id}`);
    if (session.goal !== "练习表达") {
      localStorage.removeItem(ACTIVE_PRACTICE_KEY);
      return;
    }
    practiceState.session = session;
    if (state.mode === "practice") renderPracticeSession(session);
  } catch (_) {
    localStorage.removeItem(ACTIVE_PRACTICE_KEY);
  }
}

function showPracticeSetup({ clear = false } = {}) {
  practiceState.session = null;
  $("#practiceSetup").hidden = false;
  $("#practiceActive").hidden = true;
  if (clear) {
    $("#practiceTopic").value = "";
    $("#practiceExpression").value = "";
  }
  $("#practiceScene").value = "其他";
}

function renderPracticeSession(session) {
  if (session.goal !== "练习表达") {
    localStorage.removeItem(ACTIVE_PRACTICE_KEY);
    showPracticeSetup();
    return;
  }
  practiceState.session = session;
  $("#practiceSetup").hidden = true;
  $("#practiceActive").hidden = false;
  const speaker = PARTICIPANT_BY_ID[session.speaker_id];
  $("#practiceContext").innerHTML = `
    <div><span>练习者</span><b>${escapeHtml(speaker?.name || "")}</b></div>
    <div class="practice-context-topic"><span>针对这个问题</span><b>${escapeHtml(session.topic_summary)}</b></div>
    <span class="saved-session-state">${session.status === "paused" ? "已暂停" : session.status === "completed" ? "练习已保存" : session.status === "safety_stop" ? "已安全停止" : "自动保存中"}</span>`;
  renderPracticeStage(session);
}

function renderPracticeStage(session) {
  const container = $("#practiceStage");
  const feedback = latestActionFeedback(session);
  if (session.status === "safety_stop") {
    container.innerHTML = stageShell("先处理现实安全", "这段内容涉及需要优先处理的安全问题，AI 已停止普通话术优化。", '<button class="button subtle" data-practice-new>返回新练习</button>');
  } else if (session.stage === "completed" && feedback) {
    const attempt = latestActionAttempt(session);
    container.innerHTML = stageShell("这次表达对照", "重点不是背标准答案，而是看懂一句话为什么容易引发防御，以及怎样说清真正需要。", `
      <div class="practice-final-copy">
        ${detailRow("你平时会说", attempt)}
        ${detailRow("主要问题", feedback?.one_priority_tip)}
        ${detailRow("对方可能听到", feedback?.listener_perspective)}
        ${detailRow("可以这样说", session.final_expression)}
        ${detailRow("为什么更容易被听见", feedback?.why_it_works)}
      </div>
      <div class="practice-actions">
        <button class="button primary" data-record-outcome="${session.id}">我在现实中试过了</button>
        <button class="button subtle" data-practice-new>再练一件事</button>
      </div>`);
  } else {
    container.innerHTML = stageShell("这次练习未完成", "没有找到完整的表达对照，请返回后重新提交原话。", '<button class="button danger-outline" data-practice-delete>删除这条记录</button><button class="button subtle" data-practice-new>返回新练习</button>');
  }
  bindPracticeStageEvents();
}

function stageShell(title, description, body) {
  return `<div class="practice-stage-heading"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></div><div class="practice-stage-body">${body}</div>`;
}

function latestActionFeedback(session) {
  const turn = [...(session.turns || [])].reverse().find((item) => item.structured?.attempt_feedback && item.structured?.status === "complete");
  return turn?.structured?.attempt_feedback || null;
}

function latestActionAttempt(session) {
  const turn = [...(session.turns || [])].reverse().find((item) => item.actor === "user" && item.structured?.action === "submit_action_attempt");
  return turn?.content || "";
}

function bindPracticeStageEvents() {
  const deleteButton = $("[data-practice-delete]", $("#practiceStage"));
  if (deleteButton) deleteButton.addEventListener("click", () => deletePractice(practiceState.session.id));
  $$('[data-practice-new]', $("#practiceStage")).forEach((button) => button.addEventListener("click", () => {
    localStorage.removeItem(ACTIVE_PRACTICE_KEY);
    showPracticeSetup({ clear: true });
  }));
  const outcome = $("[data-record-outcome]", $("#practiceStage"));
  if (outcome) outcome.addEventListener("click", () => openOutcomeDialog(outcome.dataset.recordOutcome));
}

async function deletePractice(id) {
  if (!confirm("确定删除这次练习及其现实结果记录吗？此操作不能撤销。")) return;
  try {
    await fetchJson(`/api/practice-sessions/${id}`, { method: "DELETE" });
    if (String(practiceState.session?.id) === String(id)) {
      practiceState.session = null;
      localStorage.removeItem(ACTIVE_PRACTICE_KEY);
      showPracticeSetup({ clear: true });
    }
    await Promise.all([loadPracticeHistory(), loadStrategyStats()]);
    showToast("练习已删除");
  } catch (error) { showToast(error.message); }
}

function setPracticePending(pending) {
  practiceState.pending = pending;
  const startButton = $("#startPractice");
  startButton.disabled = pending;
  startButton.textContent = pending ? "正在生成表达对照…" : "开始表达练习";
  $("#practiceSetup").setAttribute("aria-busy", String(pending));
  $$("textarea", $("#practiceSetup")).forEach((item) => { item.disabled = pending; });
  $$('button, textarea, select', $("#practiceStage")).forEach((item) => { item.disabled = pending; });
  $("#practiceActive").classList.toggle("is-pending", pending);
}

async function loadPracticeHistory() {
  try {
    const sessions = await fetchJson(`/api/practice-sessions?goal=${encodeURIComponent("练习表达")}&limit=40`);
    $("#practiceCount").textContent = sessions.length;
    renderPracticeHistory(sessions);
  } catch (error) {
    $("#practiceList").textContent = error.message;
  }
}

function renderPracticeHistory(sessions) {
  const container = $("#practiceList");
  if (!sessions.length) {
    container.className = "memory-list practice-history-list empty-state";
    container.textContent = "还没有表达练习";
    return;
  }
  container.className = "memory-list practice-history-list";
  container.innerHTML = sessions.map((session) => `
    <article class="practice-history-card">
      <button class="practice-history-main" type="button" data-open-practice="${session.id}">
        <span><b>${escapeHtml((session.topic_summary || "未命名练习").slice(0, 90))}</b><small>${escapeHtml(formatDate(session.updated_at))}</small></span>
        <em class="practice-status status-${escapeHtml(session.status)}">${practiceStatusLabel(session)}</em>
      </button>
      <div class="practice-history-actions">
        ${session.final_expression ? `<button type="button" data-record-outcome="${session.id}">记录现实结果</button>` : ""}
        <button type="button" data-delete-practice="${session.id}">删除</button>
      </div>
    </article>`).join("");
  $$('[data-open-practice]', container).forEach((button) => button.addEventListener("click", () => openPractice(button.dataset.openPractice)));
  $$('[data-delete-practice]', container).forEach((button) => button.addEventListener("click", () => deletePractice(button.dataset.deletePractice)));
  $$('[data-record-outcome]', container).forEach((button) => button.addEventListener("click", () => openOutcomeDialog(button.dataset.recordOutcome)));
}

function practiceStatusLabel(session) {
  if (session.status === "completed") return "已练习";
  if (session.status === "paused") return "已暂停";
  if (session.status === "abandoned") return "已结束";
  if (session.status === "safety_stop") return "安全停止";
  return "未完成";
}

async function openPractice(id) {
  try {
    const session = await fetchJson(`/api/practice-sessions/${id}`);
    if (session.goal !== "练习表达") return showToast("这条记录不属于表达练习");
    localStorage.setItem(ACTIVE_PRACTICE_KEY, String(id));
    setCoachMode("practice");
    renderPracticeSession(session);
    $$("[data-chat-view]").find((item) => item.dataset.chatView === "conversation")?.click();
  } catch (error) { showToast(error.message); }
}

function openOutcomeDialog(sessionId) {
  $("#outcomeForm").reset();
  $("#outcomeSessionId").value = sessionId;
  $("#outcomeUsedAt").value = new Date().toISOString().slice(0, 10);
  $("#outcomeDialog").showModal();
}

async function submitOutcome(event) {
  event.preventDefault();
  const result = $("input[name='outcomeResult']:checked")?.value;
  if (!result) return showToast("请选择现实结果");
  const id = $("#outcomeSessionId").value;
  try {
    await fetchJson(`/api/practice-sessions/${id}/outcomes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        used_at: $("#outcomeUsedAt").value,
        result,
        partner_reaction: $("#outcomeReaction").value.trim(),
        agreement_reached: $("#outcomeAgreement").checked,
        pause_returned: $("#outcomeReturned").checked,
        note: $("#outcomeNote").value.trim(),
      }),
    });
    $("#outcomeDialog").close();
    if (String(practiceState.session?.id) === String(id)) {
      practiceState.session = await fetchJson(`/api/practice-sessions/${id}`);
      renderPracticeSession(practiceState.session);
    }
    await Promise.all([loadPracticeHistory(), loadStrategyStats()]);
    showToast("现实使用结果已由你确认并记录");
  } catch (error) { showToast(error.message); }
}

async function loadStrategyStats() {
  try { renderStrategyStats(await fetchJson("/api/practice-strategy-stats")); }
  catch (error) { $("#strategyStats").textContent = error.message; }
}

function renderStrategyStats(data) {
  const container = $("#strategyStats");
  const strategies = data.strategies || [];
  if (!strategies.length) {
    container.className = "strategy-stat-list empty-state";
    container.textContent = "由你记录现实使用结果后统计";
    return;
  }
  container.className = "strategy-stat-list";
  container.innerHTML = strategies.map((item) => `<div><span>${escapeHtml(item.label)}</span><b>${escapeHtml(item.display)}</b>${item.helpful_rate == null ? '<small>样本不足 5 次，不显示百分比</small>' : `<small>有帮助率 ${Math.round(item.helpful_rate * 100)}%</small>`}</div>`).join("");
}

function detailRow(label, value) {
  if (!value) return "";
  return `<div class="memory-row"><b>${escapeHtml(label)}</b><p>${escapeHtml(value)}</p></div>`;
}

function setChatPending(pending, message) {
  state.pending = pending;
  $$('[data-coach-mode]').forEach((button) => { button.disabled = pending; });
  $("#sendChat").disabled = pending;
  $("#chatInput").disabled = pending;
  $("#chatStatus").textContent = message;
  $("#chatStatus").classList.toggle("thinking", pending);
}

function loadChatState() {
  const fresh = () => ({ id: makeId(), history: [] });
  try {
    const saved = JSON.parse(sessionStorage.getItem(CHAT_STORAGE_KEY) || "null");
    if (saved?.conversations?.qa) {
      return { mode: "qa", conversations: { qa: saved.conversations.qa }, pending: false };
    }
  } catch (_) {}
  return { mode: "qa", conversations: { qa: fresh() }, pending: false };
}

function persistChatState() {
  sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify({ conversations: state.conversations }));
}

function makeId() {
  return globalThis.crypto?.randomUUID?.().replaceAll("-", "") || `${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.error || `请求失败：${response.status}`);
    error.body = body;
    throw error;
  }
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
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2600);
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
