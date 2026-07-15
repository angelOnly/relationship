const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const MODEL_STORAGE_KEY = "relationship-ai-model-v1";
const PARTICIPANTS = [
  { id: "xiaoli", name: "小娌", formId: "#xiaoliForm", stateId: "#xiaoliSaveState" },
  { id: "xiaoyuan", name: "小元", formId: "#xiaoyuanForm", stateId: "#xiaoyuanSaveState" },
];
const PARTICIPANT_BY_ID = Object.fromEntries(PARTICIPANTS.map((item) => [item.id, item]));
const FOLLOW_UP_LABELS = {
  none: "只记录",
  communicate: "需要表达或倾听",
  coordinate: "需要共同协商",
  repair: "需要修复连接",
  pause: "先暂停再谈",
  resolved: "已经处理",
};

const state = {
  month: currentMonth(),
  date: localDateString(new Date()),
  history: [],
};

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupDailyTabs();
  setupEntryStepTabs();
  setupMobileDisclosures();
  setupDateAndMonth();
  setupForms();
  setupToolbar();
  setupModelPicker();
  loadAll();
});

function setupTabs() {
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.tab));
  });
}

function setupDailyTabs() {
  $$('[data-daily-view]').forEach((button) => {
    button.addEventListener("click", () => activateDailyView(button.dataset.dailyView));
  });
}

function setupEntryStepTabs() {
  $$('[data-entry-view]').forEach((button) => {
    button.addEventListener("click", () => activateEntryStep(button));
  });
}

function activateEntryStep(button) {
  const form = button.closest(".entry-form");
  if (!form) return;
  $$('[data-entry-view]', form).forEach((item) => {
    const active = item.dataset.entryView === button.dataset.entryView;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  $$('[data-entry-panel]', form).forEach((panel) => {
    const active = panel.dataset.entryPanel === button.dataset.entryView;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
}

function setupMobileDisclosures() {
  if (!window.matchMedia("(max-width: 660px)").matches) return;
  ["#monthController", "#journalUtilities"].forEach((selector) => {
    const disclosure = $(selector);
    if (disclosure) disclosure.open = false;
  });
}

function activateDailyView(name) {
  $$('[data-daily-view]').forEach((item) => {
    const active = item.dataset.dailyView === name;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  $$('[data-daily-panel]').forEach((panel) => {
    const active = panel.dataset.dailyPanel === name;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
}

function activateTab(name) {
  $$(".tab").forEach((item) => item.classList.toggle("active", item.dataset.tab === name));
  $$(".tab-panel").forEach((item) => item.classList.toggle("active", item.id === name));
  if (name === "history") loadHistory();
  if (name === "weekly") loadWeeks();
  if (name === "monthly") loadMonthlySummary();
}

function setupDateAndMonth() {
  const monthPicker = $("#monthPicker");
  const datePicker = $("#datePicker");
  monthPicker.value = state.month;
  datePicker.value = state.date;
  updateMonthSummary();

  monthPicker.addEventListener("change", () => {
    state.month = monthPicker.value || currentMonth();
    updateMonthSummary();
    if (!datePicker.value.startsWith(state.month)) {
      const today = localDateString(new Date());
      datePicker.value = today.startsWith(state.month) ? today : `${state.month}-01`;
      state.date = datePicker.value;
    }
    loadHistory();
    loadWeeks();
    loadMonthlySummary();
  });

  datePicker.addEventListener("change", () => {
    state.date = datePicker.value;
    if (state.date) {
      state.month = state.date.slice(0, 7);
      monthPicker.value = state.month;
      updateMonthSummary();
    }
  });

  $("#prevMonth").addEventListener("click", () => shiftMonth(-1));
  $("#nextMonth").addEventListener("click", () => shiftMonth(1));
}

function shiftMonth(delta) {
  const [year, month] = state.month.split("-").map(Number);
  const d = new Date(year, month - 1 + delta, 1);
  state.month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  $("#monthPicker").value = state.month;
  updateMonthSummary();
  const today = localDateString(new Date());
  state.date = today.startsWith(state.month) ? today : `${state.month}-01`;
  $("#datePicker").value = state.date;
  loadHistory();
  loadWeeks();
  loadMonthlySummary();
}

function setupForms() {
  PARTICIPANTS.forEach((participant) => {
    $(participant.formId).addEventListener("submit", (event) => saveEntry(event, participant.id));
  });
  $$('[data-delete]').forEach((button) => {
    button.addEventListener("click", () => deleteEntry(button.dataset.delete));
  });
  $("#monthlyForm").addEventListener("submit", saveMonthlySummary);
  $("#dailyAiReview").addEventListener("click", () => {
    generateAiReview("daily", state.date, "#dailyAiReviewResult", $("#dailyAiReview"));
  });
  $("#monthlyAiReview").addEventListener("click", () => {
    generateAiReview("monthly", state.month, "#monthlyAiReviewResult", $("#monthlyAiReview"));
  });
}

function setupToolbar() {
  $("#loadDate").addEventListener("click", loadDay);
  let timer;
  $("#searchInput").addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(loadHistory, 250);
  });
  $("#filterFollowUp").addEventListener("change", loadHistory);
  $("#exportCsv").addEventListener("click", () => {
    window.location.href = `/api/export.csv?month=${encodeURIComponent(state.month)}`;
  });
  $("#backupJson").addEventListener("click", () => {
    window.location.href = "/api/backup.json";
  });
}

async function setupModelPicker() {
  const select = $("#reviewModel");
  const hint = $("#reviewModelHint");
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

async function loadAll() {
  await loadDay();
  await Promise.all([loadHistory(), loadWeeks(), loadMonthlySummary()]);
}

async function loadDay() {
  state.date = $("#datePicker").value || localDateString(new Date());
  state.month = state.date.slice(0, 7);
  $("#monthPicker").value = state.month;
  updateMonthSummary();
  try {
    const entries = await Promise.all(
      PARTICIPANTS.map((participant) => fetchJson(`/api/entries/${state.date}/${participant.id}`)),
    );
    entries.forEach((entry) => fillForm(entry.participant.id, entry));
    await loadAiReview("daily", state.date, "#dailyAiReviewResult");
    showToast(`已打开 ${state.date} 的记录`);
  } catch (error) {
    showToast(error.message || "当天记录读取失败");
  }
}

function updateMonthSummary() {
  const label = $("#monthSummaryLabel");
  if (label) label.textContent = state.month;
}

function fillForm(participantId, data) {
  const participant = PARTICIPANT_BY_ID[participantId];
  const form = $(participant.formId);
  ["appreciation", "event", "feeling", "need", "response", "repair_request", "follow_up"].forEach((name) => {
    form.elements[name].value = data[name] ?? (name === "follow_up" ? "none" : "");
  });
  const revision = Number(data.revision || 0);
  setSaveState(
    participantId,
    data.updated_at ? `已保存 ${formatTime(data.updated_at)} · 修订 ${revision}` : "未保存",
    Boolean(data.updated_at),
  );
}

async function saveEntry(event, participantId) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    entry_date: $("#datePicker").value,
    participant_id: participantId,
    appreciation: form.elements.appreciation.value,
    event: form.elements.event.value,
    feeling: form.elements.feeling.value,
    need: form.elements.need.value,
    response: form.elements.response.value,
    repair_request: form.elements.repair_request.value,
    follow_up: form.elements.follow_up.value,
  };
  try {
    const saved = await fetchJson("/api/entries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setSaveState(participantId, `已保存 ${formatTime(saved.updated_at)} · 修订 ${saved.revision}`, true);
    showToast(`${PARTICIPANT_BY_ID[participantId].name}的记录已保存`);
    await loadHistory();
  } catch (error) {
    showToast(error.message || "保存失败");
  }
}

async function deleteEntry(participantId) {
  const name = PARTICIPANT_BY_ID[participantId].name;
  if (!confirm(`确定清空 ${state.date} ${name}的记录吗？历史修订仍会保留在备份中。`)) return;
  await fetchJson(`/api/entries/${state.date}/${participantId}`, { method: "DELETE" });
  fillForm(participantId, await fetchJson(`/api/entries/${state.date}/${participantId}`));
  await loadHistory();
  showToast("已清空当天记录");
}

async function loadHistory() {
  if (!$("#historyList")) return;
  const params = new URLSearchParams({ month: state.month });
  const q = $("#searchInput").value.trim();
  const followUp = $("#filterFollowUp").value;
  if (q) params.set("q", q);
  if (followUp) params.set("follow_up", followUp);
  try {
    state.history = await fetchJson(`/api/entries?${params}`);
    renderHistory(state.history);
  } catch (error) {
    $("#historyList").className = "history-list empty-state";
    $("#historyList").textContent = error.message || "历史记录读取失败";
  }
}

function renderHistory(entries) {
  $("#historyTitle").textContent = `${state.month} 历史记录`;
  $("#historyCount").textContent = `${entries.length} 条`;
  const container = $("#historyList");
  if (!entries.length) {
    container.className = "history-list empty-state";
    container.textContent = "没有匹配的记录。";
    return;
  }
  container.className = "history-list";
  container.innerHTML = entries.map((entry) => `
    <article class="history-card">
      <div class="history-head">
        <strong>${escapeHtml(entry.entry_date)} · ${escapeHtml(entry.participant?.name || "未命名")}</strong>
        <span class="category-pill follow-${escapeHtml(entry.follow_up)}">${escapeHtml(FOLLOW_UP_LABELS[entry.follow_up] || entry.follow_up)} · 修订 ${Number(entry.revision || 1)}</span>
      </div>
      <div class="history-body">
        ${historyPair("值得肯定", entry.appreciation)}
        ${historyPair("关键事件", entry.event)}
        ${historyPair("感受", entry.feeling)}
        ${historyPair("需要", entry.need)}
        ${historyPair("双方回应", entry.response)}
        ${historyPair("下一步", entry.repair_request)}
        <button class="button subtle" onclick="openHistoryDate('${entry.entry_date}')">打开这一天</button>
      </div>
    </article>
  `).join("");
}

function historyPair(label, value) {
  return `<div class="history-pair"><b>${label}</b><span>${escapeHtml(value || "—")}</span></div>`;
}

window.openHistoryDate = async function openHistoryDate(entryDate) {
  $("#datePicker").value = entryDate;
  state.date = entryDate;
  await loadDay();
  activateTab("daily");
  window.scrollTo({ top: 0, behavior: "smooth" });
};

async function loadWeeks() {
  const existing = await fetchJson(`/api/weeks?month=${encodeURIComponent(state.month)}`);
  const byWeek = Object.fromEntries(existing.map((item) => [item.week_no, item]));
  const grid = $("#weeklyGrid");
  if (!grid) return;
  const activeWeek = currentWeekForMonth();
  grid.innerHTML = `
    <nav class="section-tabs week-section-tabs" aria-label="选择周次" role="tablist">
      ${[1, 2, 3, 4, 5].map((week) => `<button class="section-tab ${week === activeWeek ? "active" : ""}" type="button" data-week-view="${week}" role="tab" aria-selected="${week === activeWeek}">第 ${week} 周</button>`).join("")}
    </nav>
    ${[1, 2, 3, 4, 5].map((week) => weekForm(week, byWeek[week] || {}, week === activeWeek)).join("")}
  `;
  $$('[data-week-view]', grid).forEach((button) => {
    button.addEventListener("click", () => activateWeekView(Number(button.dataset.weekView), grid));
  });
  $$(".week-form", grid).forEach((form) => form.addEventListener("submit", saveWeek));
  $$('[data-ai-week]', grid).forEach((button) => {
    const week = Number(button.dataset.aiWeek);
    button.addEventListener("click", () => {
      generateAiReview("weekly", `${state.month}-W${week}`, `[data-week-review="${week}"]`, button);
    });
  });
  await Promise.all([1, 2, 3, 4, 5].map((week) => (
    loadAiReview("weekly", `${state.month}-W${week}`, `[data-week-review="${week}"]`)
  )));
}

function currentWeekForMonth() {
  const current = state.date.startsWith(state.month) ? Number(state.date.slice(8, 10)) : 1;
  return Math.min(5, Math.max(1, Math.floor((current - 1) / 7) + 1));
}

function activateWeekView(week, root) {
  $$('[data-week-view]', root).forEach((button) => {
    const active = Number(button.dataset.weekView) === week;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  $$('[data-week-panel]', root).forEach((panel) => {
    const active = Number(panel.dataset.weekPanel) === week;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
}

function weekForm(week, data, active) {
  return `
    <form class="panel week-form compact-tab-panel ${active ? "active" : ""}" data-week="${week}" data-week-panel="${week}" ${active ? "" : "hidden"}>
      <div class="panel-heading">
        <div><span class="eyebrow">${state.month}</span><h3>第 ${week} 周小结</h3></div>
        <span class="save-state">${data.updated_at ? `已保存 ${formatTime(data.updated_at)} · 修订 ${Number(data.revision || 1)}` : "未保存"}</span>
      </div>
      <div class="week-fields">
        <label>本周值得保留的时刻<textarea name="highlights" rows="3">${escapeHtml(data.highlights || "")}</textarea></label>
        <label>重复出现的互动模式<textarea name="recurring_pattern" rows="3">${escapeHtml(data.recurring_pattern || "")}</textarea></label>
        <label>本周出现的觉察或调整<textarea name="observed_adjustment" rows="3">${escapeHtml(data.observed_adjustment || "")}</textarea></label>
        <label>看见小娌与小元各自的努力或需要<textarea name="participant_signals" rows="3">${escapeHtml(data.participant_signals || "")}</textarea></label>
        <label>下周唯一关注点<textarea name="next_focus" rows="3" placeholder="只写一个重点">${escapeHtml(data.next_focus || "")}</textarea></label>
      </div>
      <div class="form-actions">
        <button class="button subtle" type="button" data-ai-week="${week}">生成本周 AI 反馈</button>
        <button class="button primary" type="submit">保存第 ${week} 周</button>
      </div>
      <div class="ai-review-result empty-state" data-week-review="${week}">还没有生成本周复盘</div>
    </form>
  `;
}

async function saveWeek(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const weekNo = Number(form.dataset.week);
  const payload = {
    month_key: state.month,
    week_no: weekNo,
    highlights: form.elements.highlights.value,
    recurring_pattern: form.elements.recurring_pattern.value,
    observed_adjustment: form.elements.observed_adjustment.value,
    participant_signals: form.elements.participant_signals.value,
    next_focus: form.elements.next_focus.value,
  };
  try {
    const saved = await fetchJson("/api/weeks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $(".save-state", form).textContent = `已保存 ${formatTime(saved.updated_at)} · 修订 ${saved.revision}`;
    $(".save-state", form).classList.add("saved");
    showToast(`第 ${weekNo} 周小结已保存`);
  } catch (error) {
    showToast(error.message || "每周小结保存失败");
  }
}

async function loadMonthlySummary() {
  const data = await fetchJson(`/api/monthly-summary?month=${encodeURIComponent(state.month)}`);
  const form = $("#monthlyForm");
  if (!form) return;
  ["overall_change", "what_helped", "recurring_patterns", "needs_attention", "next_focus"].forEach((name) => {
    form.elements[name].value = data[name] || "";
  });
  const el = $("#monthlySaveState");
  el.textContent = data.updated_at ? `已保存 ${formatTime(data.updated_at)} · 修订 ${Number(data.revision || 1)}` : "未保存";
  el.classList.toggle("saved", Boolean(data.updated_at));
  await loadAiReview("monthly", state.month, "#monthlyAiReviewResult");
}

async function saveMonthlySummary(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    month_key: state.month,
    overall_change: form.elements.overall_change.value,
    what_helped: form.elements.what_helped.value,
    recurring_patterns: form.elements.recurring_patterns.value,
    needs_attention: form.elements.needs_attention.value,
    next_focus: form.elements.next_focus.value,
  };
  try {
    const saved = await fetchJson("/api/monthly-summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const el = $("#monthlySaveState");
    el.textContent = `已保存 ${formatTime(saved.updated_at)} · 修订 ${saved.revision}`;
    el.classList.add("saved");
    showToast("月度复盘已保存");
  } catch (error) {
    showToast(error.message || "月度复盘保存失败");
  }
}

async function generateAiReview(periodType, periodKey, targetSelector, button) {
  const target = $(targetSelector);
  if (!target || button.disabled) return;
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "分析中……";
  target.className = "ai-review-result loading-state";
  target.textContent = "正在结合盖洛普画像、长期背景和相似历史生成反馈……";
  try {
    const review = await fetchJson("/api/ai-reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        period_type: periodType,
        period_key: periodKey,
        model: $("#reviewModel")?.value || "",
      }),
    });
    renderAiReview(review, target);
    showToast("AI 复盘已保存，调整目标已进入行动清单");
  } catch (error) {
    target.className = "ai-review-result error-state";
    target.textContent = error.message || "AI 复盘生成失败";
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function loadAiReview(periodType, periodKey, targetSelector) {
  const target = $(targetSelector);
  if (!target) return;
  try {
    const params = new URLSearchParams({ period_type: periodType, period_key: periodKey });
    const review = await fetchJson(`/api/ai-reviews?${params}`);
    if (review.id) renderAiReview(review, target);
    else {
      target.className = "ai-review-result empty-state";
      target.textContent = periodType === "daily" ? "还没有生成今日复盘" : periodType === "weekly" ? "还没有生成本周复盘" : "还没有生成月度复盘";
    }
  } catch (error) {
    target.className = "ai-review-result error-state";
    target.textContent = error.message || "复盘读取失败";
  }
}

function renderAiReview(review, target) {
  const score = (label, value) => `
    <div class="ai-score-card"><span>${label}</span><strong>${value ?? "—"}</strong><small>/ 10</small></div>
  `;
  const section = (label, value) => value ? `
    <div class="ai-review-section"><b>${label}</b><p>${escapeHtml(value)}</p></div>
  ` : "";
  const participants = Array.isArray(review.participants) ? review.participants : [];
  const interaction = review.interaction || {};
  const actions = Array.isArray(interaction.actions) && interaction.actions.length
    ? `<div class="ai-review-section"><b>接下来这样做</b><ol>${interaction.actions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol></div>`
    : "";
  target.className = "ai-review-result completed";
  target.innerHTML = `
    <div class="ai-score-grid">
      ${participants.map((item) => score(`${escapeHtml(item.participant?.name)}行为`, item.score)).join("")}
      ${score("互动质量", interaction.score)}
    </div>
    ${section("本期结论", interaction.summary)}
    <div class="ai-review-columns">
      ${participants.map((item) => section(`给${escapeHtml(item.participant?.name)}的反馈`, item.feedback)).join("")}
    </div>
    ${section("进步证据", interaction.what_improved)}
    ${section("需要警惕", interaction.risk_pattern)}
    <div class="adjustment-goal"><span>下期唯一目标</span><strong>${escapeHtml(interaction.adjustment_goal || "暂无")}</strong><a href="/actions">在行动清单中管理</a></div>
    ${actions}
    ${section("可以直接这样说", interaction.conversation_example)}
    <p class="review-meta">${escapeHtml(interaction.confidence || "")} · ${escapeHtml(review.model_name || "默认模型")} · 第 ${Number(review.revision || 1)} 版 · ${escapeHtml(formatTime(review.updated_at))}</p>
  `;
}

function setSaveState(participantId, text, saved) {
  const el = $(PARTICIPANT_BY_ID[participantId].stateId);
  el.textContent = text;
  el.classList.toggle("saved", saved);
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
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2400);
}

function currentMonth() {
  return localDateString(new Date()).slice(0, 7);
}

function localDateString(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function formatTime(value) {
  if (!value) return "";
  return String(value).replace("T", " ").slice(5, 16);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
