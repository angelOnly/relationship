const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const CHAT_STORAGE_KEY = "relationship-coach-chat-v2";
const MODE_STORAGE_KEY = "relationship-coach-mode-v2";
const MODEL_STORAGE_KEY = "relationship-ai-model-v1";
const SPEAKER_STORAGE_KEY = "relationship-chat-speaker-v1";
const ACTIVE_PRACTICE_KEY = "relationship-active-practice-v1";
const PARTICIPANTS = [
  { id: "xiaoli", name: "小娌" },
  { id: "xiaoyuan", name: "小元" },
];
const PARTICIPANT_BY_ID = Object.fromEntries(PARTICIPANTS.map((item) => [item.id, item]));
const STAGE_ORDER = ["narrowing_topic", "expression_draft", "paraphrase_confirmation", "partner_response", "debrief"];
const MODE_CONFIG = {
  qa: {
    title: "关系问答",
    eyebrow: "不评分 · 不入真实复盘库",
    speakerLabel: "当前提问者",
    status: "先直接问一个具体问题",
    placeholder: "例如：为什么我明明想被安慰，却总是把话说成指责？",
    button: "发送",
    newLabel: "新问题",
    welcomeTitle: "可以直接问，不需要先填完整场景",
    welcome: "AI 会区分本次事实、画像假设、通用方法和你亲自确认过的成功做法。问答不会产生关系评分，也不会写入真实复盘库。",
    prompts: [
      ["为什么越解释越生气？", "为什么我们一有分歧，我越解释，对方反而越生气？"],
      ["怎么表达边界？", "我想拒绝一件事，又不想变成指责，应该怎么表达边界？"],
      ["先安慰还是解决？", "伴侣倾诉时，怎么判断对方此刻需要共情还是解决方案？"],
    ],
  },
  review: {
    title: "真实场景复盘",
    eyebrow: "完成分析后保存一条精炼真实记录",
    speakerLabel: "本次记录者",
    status: "一次只复盘一个真实发生的具体事件",
    placeholder: "例如：昨晚小娌想聊工作上的委屈，小元很快给了解决方案，然后去做别的事。小娌当时说……",
    button: "发送并分析",
    newLabel: "新场景",
    welcomeTitle: "从一件真实发生的小事开始",
    welcome: "写下小娌与小元实际说了什么、做了什么。信息足够时直接分析；信息不足时只追问必要内容。",
    prompts: [
      ["复盘刚才的冲突", "刚才小娌与小元因为一件小事起了冲突，事情是……"],
      ["看双方内在期待", "请分析这件真实发生的小事中，小娌与小元各自真正期待什么。事情是……"],
      ["看双方行为变化", "这次小娌说了……小元回应了……请分别反馈两个人的行为变化。"],
    ],
  },
};

const state = loadChatState();
const practiceState = { session: null, pending: false };

document.addEventListener("DOMContentLoaded", async () => {
  setupChatTabs();
  setupRecordTabs();
  setupSpeakerPicker();
  bindCommonEvents();
  await setupModelPicker();
  setCoachMode(localStorage.getItem(MODE_STORAGE_KEY) || "qa", { restore: true });
  await Promise.all([loadRecords(), loadProgress(), loadPracticeHistory(), loadPracticeProgress(), loadStrategyStats()]);
  await restoreActivePractice();
});

function bindCommonEvents() {
  $("#chatForm").addEventListener("submit", sendMessage);
  $("#newChat").addEventListener("click", resetConversation);
  $$('[data-coach-mode]').forEach((button) => button.addEventListener("click", () => setCoachMode(button.dataset.coachMode)));
  $("#startPractice").addEventListener("click", startPractice);
  $("#outcomeForm").addEventListener("submit", submitOutcome);
  $$('[data-close-dialog]').forEach((button) => button.addEventListener("click", () => $("#outcomeDialog").close()));

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

function setupRecordTabs() {
  $$('[data-record-view]').forEach((button) => button.addEventListener("click", () => {
    $$('[data-record-view]').forEach((item) => item.classList.toggle("active", item === button));
    $$('[data-record-panel]').forEach((panel) => { panel.hidden = panel.dataset.recordPanel !== button.dataset.recordView; });
  }));
}

function setCoachMode(mode, { restore = false } = {}) {
  if (!MODE_CONFIG[mode] && mode !== "practice") mode = "qa";
  state.mode = mode;
  localStorage.setItem(MODE_STORAGE_KEY, mode);
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
    $("#coachModeTitle").textContent = "单人沟通练习";
    $("#coachModeEyebrow").textContent = "步骤卡 · AI 扮演另一方 · 自动保存";
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
  const conversation = currentConversation();
  const priorHistory = conversation.history.slice(-12);
  const speakerId = currentSpeakerId();
  conversation.history.push({ role: "user", content: message, participant_id: speakerId });
  appendMessage("user", message, false, speakerId);
  input.value = "";
  setChatPending(true, state.mode === "qa" ? "正在整理依据并回答……" : "正在结合才干画像和相关历史分析……");
  persistChatState();

  const assistantArticle = appendMessage("assistant", "");
  let streamedReply = "";
  let finalData = null;
  try {
    await streamJsonEvents("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: state.mode,
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
        if (streamEvent.analysis_saved) markMessageSaved(assistantArticle, streamEvent.record?.id);
      } else if (streamEvent.type === "error") {
        throw new Error(streamEvent.error || "请求失败，请稍后重试。");
      }
    });
    if (!finalData) throw new Error("模型输出没有正常结束。");
    conversation.id = finalData.conversation_id || conversation.id;
    conversation.history.push({ role: "assistant", content: streamedReply, sources: finalData.source_labels || [] });
    persistChatState();
    if (finalData.analysis_saved) {
      showToast("本次真实场景已写入长期复盘库");
      await Promise.all([loadRecords(), loadProgress()]);
    }
  } catch (error) {
    if (!streamedReply) assistantArticle.remove();
    appendMessage("error", error.message || "请求失败，请稍后重试。");
  } finally {
    setChatPending(false, MODE_CONFIG[state.mode].status);
    input.focus();
  }
}

async function setupModelPicker() {
  const select = $("#chatModel");
  const hint = $("#chatModelHint");
  try {
    const catalog = await fetchJson("/api/models");
    select.innerHTML = catalog.models.map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)} · ${escapeHtml(item.description || "")}</option>`).join("");
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

function markMessageSaved(article) {
  const bubble = $(".message-bubble", article);
  if (!bubble || $(".saved-badge", bubble)) return;
  bubble.insertAdjacentHTML("beforeend", '<span class="saved-badge">已精炼入库</span>');
}

function resetConversation() {
  const conversation = currentConversation();
  if (conversation.history.length && !confirm(`开始${state.mode === "qa" ? "新问题" : "新场景"}？当前原始对话会从浏览器会话中清除。`)) return;
  conversation.id = makeId();
  conversation.history = [];
  persistChatState();
  renderConversation();
  $("#chatInput").value = "";
  $("#chatInput").focus();
}

async function startPractice() {
  const topic = $("#practiceTopic").value.trim();
  const goal = $("#practiceGoal").value;
  if (!topic) return showToast("请先写下一件具体小事");
  if (!goal) return showToast("请选择这轮练习目标");
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
        source_scene_analysis_id: $("#practiceSourceId").value || null,
        model: $("#chatModel").value,
      }),
    });
    practiceState.session = session;
    localStorage.setItem(ACTIVE_PRACTICE_KEY, String(session.id));
    renderPracticeSession(session);
    await loadPracticeHistory();
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
    practiceState.session = session;
    if (state.mode === "practice") renderPracticeSession(session);
  } catch (_) {
    localStorage.removeItem(ACTIVE_PRACTICE_KEY);
  }
}

function showPracticeSetup(prefill = null) {
  practiceState.session = null;
  $("#practiceSetup").hidden = false;
  $("#practiceActive").hidden = true;
  if (prefill) {
    $("#practiceTopic").value = prefill.topic || "";
    $("#practiceScene").value = prefill.scene || "其他";
    $("#practiceSourceId").value = prefill.sourceId || "";
  }
}

function renderPracticeSession(session) {
  practiceState.session = session;
  $("#practiceSetup").hidden = true;
  $("#practiceActive").hidden = false;
  const speaker = PARTICIPANT_BY_ID[session.speaker_id];
  const aiRole = PARTICIPANT_BY_ID[session.ai_role_id];
  $("#practiceContext").innerHTML = `
    <div><span>表达者</span><b>${escapeHtml(speaker?.name || "")}</b></div>
    <div><span>AI 扮演</span><b>${escapeHtml(aiRole?.name || "")}</b></div>
    <div><span>场景／目标</span><b>${escapeHtml(session.scene_type)} · ${escapeHtml(session.goal)}</b></div>
    <div class="practice-context-topic"><span>这次只谈</span><b>${escapeHtml(session.topic_summary)}</b></div>
    <span class="saved-session-state">${session.status === "paused" ? "已暂停" : session.status === "completed" ? "已完成并保存" : session.status === "safety_stop" ? "已安全停止" : "自动保存中"}</span>`;
  renderStepCards(session.stage, session.status);
  renderPracticeStage(session);
}

function renderStepCards(stage, status) {
  let currentIndex = STAGE_ORDER.indexOf(stage);
  if (stage === "setup") currentIndex = 0;
  if (stage === "completed") currentIndex = STAGE_ORDER.length;
  $$("[data-step-stage]", $("#practiceStepCards")).forEach((card, index) => {
    card.classList.toggle("current", status === "active" && index === currentIndex);
    card.classList.toggle("done", index < currentIndex || stage === "completed");
  });
}

function renderPracticeStage(session) {
  const container = $("#practiceStage");
  if (session.status === "paused") {
    container.innerHTML = stageShell("练习已暂停", "当前内容已保存，恢复后从原步骤继续。", '<button class="button primary" data-practice-resume>恢复练习</button>');
  } else if (["safety_stop", "abandoned"].includes(session.status)) {
    const title = session.status === "safety_stop" ? "普通练习已停止" : "练习已结束";
    const copy = session.status === "safety_stop" ? "当前内容涉及需要优先处理的现实安全问题，AI 不再继续角色扮演或普通话术优化。" : "这次会话保留在历史中，你可以删除它或新建练习。";
    container.innerHTML = stageShell(title, copy, '<button class="button danger-outline" data-practice-delete>删除会话</button><button class="button subtle" data-practice-new>新建练习</button>');
  } else if (session.stage === "setup") {
    container.innerHTML = stageShell("确认练习设置", "确认后先把事情缩小为摄像头能拍到的一件小事。", `
      <div class="practice-confirmation"><p><b>${escapeHtml(session.topic_summary)}</b></p><small>目标：${escapeHtml(session.goal)}</small></div>
      <button class="button primary" data-practice-action="confirm_setup">确认，进入步骤 1</button>`);
  } else if (session.stage === "narrowing_topic") {
    const feedback = latestPracticeResult(session)?.attempt_feedback;
    container.innerHTML = stageShell("步骤 1 · 把事情说小", "只写时间、动作或原话，不写“总是／根本／自私／故意”。", `
      ${feedbackHtml(feedback)}
      <textarea id="practiceInput" rows="4" maxlength="5000" placeholder="例如：刚才我说工作上的事情时，你连续看了几次手机。">${escapeHtml(feedback?.result === "revise" ? "" : session.topic_summary)}</textarea>
      <div class="practice-actions"><button class="button primary" data-practice-action="submit_topic">检查这件小事</button><button class="button subtle" data-practice-pause>暂停</button></div>`);
  } else if (session.stage === "expression_draft") {
    const feedback = latestPracticeResult(session)?.attempt_feedback;
    container.innerHTML = stageShell("步骤 2 · 20 秒表达", "按事实＋感受＋需要＋具体请求写一段话。这里没有计时器。", `
      ${feedbackHtml(feedback)}
      <textarea id="practiceInput" rows="5" maxlength="5000" placeholder="刚才发生了……我感到……我需要……你能不能……"></textarea>
      <div class="practice-actions"><button class="button primary" data-practice-action="submit_expression">提交表达</button>${feedback?.suggested_version ? '<button class="button subtle" data-use-suggestion>使用建议版本</button>' : ""}<button class="button subtle" data-practice-pause>暂停</button></div>`);
  } else if (session.stage === "paraphrase_confirmation") {
    container.innerHTML = stageShell("步骤 3 · AI 复述", "AI 此时只做倾听者。是否准确只能由你确认。", `
      <blockquote class="practice-roleplay"><span>AI 复述</span>${escapeHtml(session.final_paraphrase)}</blockquote>
      <label class="correction-field">如果不准确，用一句话纠正<textarea id="practiceCorrection" rows="2" maxlength="2000" placeholder="例如：我更在意的是被认真听完，而不是马上解决。"></textarea></label>
      <div class="practice-actions confirmation-actions"><button class="button primary" data-practice-action="confirm_accurate">准确</button><button class="button subtle" data-practice-action="confirm_partial">部分准确</button><button class="button subtle" data-practice-action="confirm_inaccurate">不准确</button><button class="button subtle" data-practice-pause>暂停</button></div>`);
  } else if (session.stage === "partner_response") {
    container.innerHTML = stageShell("步骤 4 · AI 回应", "这是用于练习的可能回应，不是对现实中另一方的预测。", `
      <blockquote class="practice-roleplay partner"><span>${escapeHtml(PARTICIPANT_BY_ID[session.ai_role_id]?.name)}（AI 扮演）</span>${escapeHtml(session.final_response)}</blockquote>
      <div class="practice-actions"><button class="button primary" data-practice-action="continue_to_debrief">进入本轮总结</button><button class="button subtle" data-practice-action="practice_again">再练一轮表达</button><button class="button subtle" data-practice-pause>暂停</button></div>`);
  } else if (["debrief", "completed"].includes(session.stage)) {
    const completed = session.stage === "completed";
    container.innerHTML = stageShell(completed ? "练习已完成" : "步骤 5 · 本轮总结", completed ? "练习结果已保存。现实是否有效，仍以你实际使用后的记录为准。" : "只看技能状态，不计入真实关系评分。", `
      ${practiceSummaryHtml(session)}
      <div class="practice-actions">
        ${completed ? `<button class="button primary" data-record-outcome="${session.id}">我在现实中用过这次表达</button>` : '<button class="button primary" data-practice-action="complete_practice">完成并保存</button>'}
        <button class="button subtle" data-practice-action="practice_again">再练一轮</button>
        <button class="button subtle" data-practice-new>新建练习</button>
      </div>`);
  }
  bindPracticeStageEvents();
}

function stageShell(title, description, body) {
  return `<div class="practice-stage-heading"><span class="eyebrow">当前步骤</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></div><div class="practice-stage-body">${body}</div>`;
}

function feedbackHtml(feedback) {
  if (!feedback) return "";
  const passed = feedback.result === "pass";
  return `<div class="attempt-feedback ${passed ? "pass" : "revise"}"><b>${passed ? "这一步已做到" : "这一步需调整"}</b><p>${escapeHtml(feedback.one_priority_tip || "")}</p>${feedback.suggested_version ? `<small>建议版本：${escapeHtml(feedback.suggested_version)}</small>` : ""}</div>`;
}

function practiceSummaryHtml(session) {
  const skills = session.skill_results || {};
  const finalSummary = [...(session.turns || [])].reverse().find((turn) => turn.structured?.final_summary)?.structured?.final_summary || {};
  return `<div class="practice-final-copy">
      ${detailRow("最终表达", session.final_expression)}
      ${detailRow("AI 复述", session.final_paraphrase)}
      ${detailRow("AI 回应", session.final_response)}
      ${detailRow("下次只练", finalSummary.one_practice_focus)}
    </div>
    <div class="skill-result-grid">${Object.entries(skills).map(([name, value]) => `<div class="skill-${value === "已做到" ? "done" : value === "需调整" ? "revise" : "empty"}"><span>${escapeHtml(name)}</span><b>${escapeHtml(value)}</b></div>`).join("") || '<span class="muted">总结生成后显示技能状态</span>'}</div>`;
}

function latestPracticeResult(session) {
  return [...(session.turns || [])].reverse().find((turn) => turn.actor === "ai_coach" && turn.structured && Object.keys(turn.structured).length)?.structured || null;
}

function bindPracticeStageEvents() {
  $$('[data-practice-action]', $("#practiceStage")).forEach((button) => button.addEventListener("click", () => {
    const action = button.dataset.practiceAction;
    let content = $("#practiceInput")?.value.trim() || "";
    const correction = $("#practiceCorrection")?.value.trim() || "";
    if (["confirm_partial", "confirm_inaccurate"].includes(action) && !correction) return showToast("请用一句话说明哪里需要修正");
    advancePractice(action, content, { correction });
  }));
  const suggestionButton = $("[data-use-suggestion]", $("#practiceStage"));
  if (suggestionButton) suggestionButton.addEventListener("click", () => {
    const suggestion = latestPracticeResult(practiceState.session)?.attempt_feedback?.suggested_version || "";
    if (suggestion) advancePractice("use_suggestion", suggestion);
  });
  const pauseButton = $("[data-practice-pause]", $("#practiceStage"));
  if (pauseButton) pauseButton.addEventListener("click", pausePractice);
  const resumeButton = $("[data-practice-resume]", $("#practiceStage"));
  if (resumeButton) resumeButton.addEventListener("click", resumePractice);
  const deleteButton = $("[data-practice-delete]", $("#practiceStage"));
  if (deleteButton) deleteButton.addEventListener("click", () => deletePractice(practiceState.session.id));
  $$('[data-practice-new]', $("#practiceStage")).forEach((button) => button.addEventListener("click", () => {
    localStorage.removeItem(ACTIVE_PRACTICE_KEY);
    showPracticeSetup();
  }));
  const outcome = $("[data-record-outcome]", $("#practiceStage"));
  if (outcome) outcome.addEventListener("click", () => openOutcomeDialog(outcome.dataset.recordOutcome));
}

async function advancePractice(action, content = "", extras = {}) {
  const session = practiceState.session;
  if (!session || practiceState.pending) return;
  setPracticePending(true);
  let final = null;
  try {
    await streamJsonEvents(`/api/practice-sessions/${session.id}/advance/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_stage: session.stage, action, turn_id: makeId(), content, ...extras }),
    }, (streamEvent) => {
      if (streamEvent.type === "status") setPracticeStatus(streamEvent.message);
      if (streamEvent.type === "final") final = streamEvent;
      if (streamEvent.type === "error") throw new Error(streamEvent.error);
    });
    if (!final?.session) throw new Error("练习结果没有正常保存。");
    practiceState.session = final.session;
    localStorage.setItem(ACTIVE_PRACTICE_KEY, String(final.session.id));
    renderPracticeSession(final.session);
    if (final.reply) showToast(final.reply.slice(0, 80));
    await Promise.all([loadPracticeHistory(), loadPracticeProgress(), loadStrategyStats()]);
  } catch (error) {
    showToast(error.message || "当前步骤处理失败，请重试。");
  } finally {
    setPracticePending(false);
  }
}

async function pausePractice() {
  const session = practiceState.session;
  if (!session) return;
  try {
    const updated = await fetchJson(`/api/practice-sessions/${session.id}/pause`, { method: "POST" });
    renderPracticeSession(updated);
    await loadPracticeHistory();
  } catch (error) { showToast(error.message); }
}

async function resumePractice() {
  const session = practiceState.session;
  if (!session) return;
  try {
    const updated = await fetchJson(`/api/practice-sessions/${session.id}/resume`, { method: "POST" });
    renderPracticeSession(updated);
    await loadPracticeHistory();
  } catch (error) { showToast(error.message); }
}

async function deletePractice(id) {
  if (!confirm("确定删除这次练习及其现实结果记录吗？此操作不能撤销。")) return;
  try {
    await fetchJson(`/api/practice-sessions/${id}`, { method: "DELETE" });
    if (String(practiceState.session?.id) === String(id)) {
      practiceState.session = null;
      localStorage.removeItem(ACTIVE_PRACTICE_KEY);
      showPracticeSetup();
    }
    await Promise.all([loadPracticeHistory(), loadPracticeProgress(), loadStrategyStats()]);
    showToast("练习已删除");
  } catch (error) { showToast(error.message); }
}

function setPracticePending(pending) {
  practiceState.pending = pending;
  $("#startPractice").disabled = pending;
  $$('button, textarea, select', $("#practiceStage")).forEach((item) => { item.disabled = pending; });
  $("#practiceActive").classList.toggle("is-pending", pending);
}

function setPracticeStatus(message) {
  const heading = $(".practice-stage-heading p", $("#practiceStage"));
  if (heading) heading.textContent = message;
}

async function loadPracticeHistory() {
  try {
    const sessions = await fetchJson("/api/practice-sessions?limit=40");
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
    container.textContent = "还没有练习会话";
    return;
  }
  container.className = "memory-list practice-history-list";
  container.innerHTML = sessions.map((session) => `
    <article class="practice-history-card">
      <button class="practice-history-main" type="button" data-open-practice="${session.id}">
        <span><b>${escapeHtml(session.topic_summary || "未命名练习")}</b><small>${escapeHtml(formatDate(session.updated_at))} · ${escapeHtml(session.scene_type)} · 第 ${session.current_round} 轮</small></span>
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
  if (session.status === "completed") return "已完成";
  if (session.status === "paused") return "已暂停";
  if (session.status === "abandoned") return "已结束";
  if (session.status === "safety_stop") return "安全停止";
  return session.step_card?.title || "进行中";
}

async function openPractice(id) {
  try {
    const session = await fetchJson(`/api/practice-sessions/${id}`);
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

async function loadRecords() {
  const params = new URLSearchParams({ limit: "40" });
  const q = $("#memorySearch")?.value.trim();
  const scene = $("#sceneFilter")?.value;
  if (q) params.set("q", q);
  if (scene) params.set("scene", scene);
  try {
    renderRecords(await fetchJson(`/api/analysis-records?${params}`));
  } catch (error) {
    $("#memoryList").className = "memory-list empty-state";
    $("#memoryList").textContent = error.message;
  }
}

function renderRecords(records) {
  $("#recordCount").textContent = records.length;
  const container = $("#memoryList");
  if (!records.length) {
    container.className = "memory-list empty-state";
    container.textContent = "没有匹配的精炼案例";
    return;
  }
  container.className = "memory-list";
  container.innerHTML = records.map(memoryCard).join("");
  $$('[data-delete-record]', container).forEach((button) => button.addEventListener("click", () => deleteRecord(button.dataset.deleteRecord)));
  $$('[data-practice-from-record]', container).forEach((button) => button.addEventListener("click", () => startPracticeFromRecord(button)));
}

function memoryCard(record) {
  const scores = (record.participants || []).filter((item) => item.behavior?.score != null).map((item) => `${escapeHtml(item.participant?.name)} ${Number(item.behavior.score)}`).join(" · ");
  const participantDetails = (record.participants || []).map((item) => `
    <section class="participant-memory"><h4>${escapeHtml(item.participant?.name || "未命名")}</h4>
      ${detailRow("本次角色", item.role_in_event)}${detailRow("内在期待", item.inner_expectation)}${detailRow("才干状态", item.talent_state)}${detailRow("行为反馈", item.behavior?.feedback)}${detailRow("评分依据", item.behavior?.score_reason)}
    </section>`).join("");
  const interaction = record.interaction || {};
  return `<details class="memory-card"><summary><span class="memory-title"><b>${escapeHtml(record.question_summary)}</b><small>${escapeHtml(formatDate(record.created_at))} · ${escapeHtml(record.scene_type || "其他")}</small></span>${scores ? `<span class="score-badge">${scores}</span>` : ""}</summary>
    <div class="memory-detail">${participantDetails}${detailRow("互动循环", interaction.loop)}${detailRow("建议怎么说", interaction.recommended_wording)}${detailRow("进步判断", interaction.progress_assessment)}${detailRow("下一步", interaction.next_action)}
      <div class="keyword-row">${(record.keywords || []).map((keyword) => `<span>${escapeHtml(keyword)}</span>`).join("")}</div>
      <div class="memory-card-actions"><button class="button subtle" type="button" data-practice-from-record="${record.id}" data-topic="${escapeHtml(record.question_summary)}" data-scene="${escapeHtml(record.scene_type)}">用这件事开始单人练习</button><button class="delete-memory" type="button" data-delete-record="${record.id}">删除这条</button></div>
    </div></details>`;
}

function startPracticeFromRecord(button) {
  localStorage.removeItem(ACTIVE_PRACTICE_KEY);
  setCoachMode("practice");
  showPracticeSetup({ sourceId: button.dataset.practiceFromRecord, topic: button.dataset.topic, scene: button.dataset.scene });
  $("#practiceGoal").focus();
  $$("[data-chat-view]").find((item) => item.dataset.chatView === "conversation")?.click();
}

async function deleteRecord(id) {
  if (!confirm("确定删除这条精炼分析吗？此操作不能撤销。")) return;
  await fetchJson(`/api/analysis-records/${id}`, { method: "DELETE" });
  await Promise.all([loadRecords(), loadProgress()]);
  showToast("记录已删除");
}

async function loadProgress() {
  try { renderProgress(await fetchJson("/api/progress")); }
  catch (error) { $("#progressSummary").textContent = error.message; }
}

function renderProgress(data) {
  const summary = $("#progressSummary");
  const participants = Array.isArray(data.participants) ? data.participants : [];
  if (!participants.some((item) => item.recent_average != null)) {
    summary.className = "progress-summary empty-state";
    summary.textContent = "小娌与小元还没有可评分的真实复盘";
    $("#progressBars").innerHTML = "";
    return;
  }
  summary.className = "progress-summary participant-progress-summary";
  summary.innerHTML = participants.map((item) => {
    const delta = item.delta == null ? "基线建立中" : `${item.delta > 0 ? "+" : ""}${item.delta}`;
    return `<div><span>${escapeHtml(item.participant?.name)}</span><strong>${item.recent_average ?? "—"}</strong><small>${escapeHtml(item.trend)} · ${escapeHtml(delta)}</small></div>`;
  }).join("");
  $("#progressBars").innerHTML = participants.map((participant) => `<div class="participant-progress-row"><b>${escapeHtml(participant.participant?.name)}</b><div class="progress-bars">${(participant.items || []).slice(-12).map((item) => `<span style="--score:${Number(item.score)}" title="${escapeHtml(formatDate(item.created_at))} · ${escapeHtml(item.question_summary)} · ${item.score}/10"></span>`).join("")}</div></div>`).join("");
}

async function loadPracticeProgress() {
  try { renderPracticeProgress(await fetchJson("/api/practice-progress")); }
  catch (error) { $("#practiceProgress").textContent = error.message; }
}

function renderPracticeProgress(data) {
  const container = $("#practiceProgress");
  if (!data.completed_sessions) {
    container.className = "practice-progress-list empty-state";
    container.textContent = "完成第一轮练习后显示";
    return;
  }
  container.className = "practice-progress-list";
  container.innerHTML = (data.skills || []).map((skill) => `<div class="practice-progress-row"><span>${escapeHtml(skill.name)}</span><div><i class="done" style="--count:${skill.counts?.["已做到"] || 0}" title="已做到 ${skill.counts?.["已做到"] || 0} 次"></i><i class="revise" style="--count:${skill.counts?.["需调整"] || 0}" title="需调整 ${skill.counts?.["需调整"] || 0} 次"></i></div><b>${skill.counts?.["已做到"] || 0} 次做到</b></div>`).join("");
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
  $("#sendChat").disabled = pending;
  $("#chatInput").disabled = pending;
  $("#chatStatus").textContent = message;
  $("#chatStatus").classList.toggle("thinking", pending);
}

function loadChatState() {
  const fresh = () => ({ id: makeId(), history: [] });
  try {
    const saved = JSON.parse(sessionStorage.getItem(CHAT_STORAGE_KEY) || "null");
    if (saved?.conversations?.qa && saved?.conversations?.review) {
      return { mode: "qa", conversations: saved.conversations, pending: false };
    }
  } catch (_) {}
  return { mode: "qa", conversations: { qa: fresh(), review: fresh() }, pending: false };
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
