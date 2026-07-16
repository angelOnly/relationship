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
const WEEKDAY_NAMES = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];
const TODAY = localDateString(new Date());

const state = {
  month: TODAY.slice(0, 7),
  date: TODAY,
  calendar: { days: {}, weeks: {} },
  dayView: "xiaoli",
};

document.addEventListener("DOMContentLoaded", () => {
  setupCalendarControls();
  setupDayWorkspace();
  setupEntryStepTabs();
  setupForms();
  setupPeriodControls();
  setupDataTools();
  void refreshMonth();
});

function setupCalendarControls() {
  const monthPicker = $("#monthPicker");
  monthPicker.value = state.month;
  monthPicker.addEventListener("change", () => {
    const month = monthPicker.value;
    if (isMonthKey(month)) void setMonth(month);
  });
  $("#prevMonth").addEventListener("click", () => void shiftMonth(-1));
  $("#nextMonth").addEventListener("click", () => void shiftMonth(1));
  $("#goToday").addEventListener("click", () => void setMonth(TODAY.slice(0, 7), TODAY));
  $("#openMonthlySummary").addEventListener("click", () => void openMonthlySummary());
  $("#closeMonthlySummary").addEventListener("click", () => {
    $("#monthlySummarySection").hidden = true;
  });
}

function setupDayWorkspace() {
  $$('[data-day-view]').forEach((button) => {
    button.addEventListener("click", () => activateDayView(button.dataset.dayView));
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

function activateDayView(name) {
  state.dayView = name;
  $$('[data-day-view]').forEach((item) => {
    const active = item.dataset.dayView === name;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  $$('[data-day-panel]').forEach((panel) => {
    const active = panel.dataset.dayPanel === name;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
}

function setupForms() {
  PARTICIPANTS.forEach((participant) => {
    $(participant.formId).addEventListener("submit", (event) => void saveEntry(event, participant.id));
  });
  $$('[data-delete]').forEach((button) => {
    button.addEventListener("click", () => void deleteEntry(button.dataset.delete));
  });
}

function setupPeriodControls() {
  $("#weeklyForm").addEventListener("submit", (event) => void saveWeek(event));
  $("#weeklyAiReview").addEventListener("click", () => {
    const weekEnd = $("#weeklyForm").dataset.weekEnd;
    if (weekEnd) void generateAiReview("weekly", weekEnd, "#weeklyAiReviewResult", $("#weeklyAiReview"));
  });
  $("#monthlyForm").addEventListener("submit", (event) => void saveMonthlySummary(event));
  $("#monthlyAiReview").addEventListener("click", () => {
    void generateAiReview("monthly", state.month, "#monthlyAiReviewResult", $("#monthlyAiReview"));
  });
  $("#dailyAiReview").addEventListener("click", () => {
    void generateAiReview("daily", state.date, "#dailyAiReviewResult", $("#dailyAiReview"));
  });
}

function setupDataTools() {
  $("#exportCsv").addEventListener("click", () => {
    window.location.href = `/api/export.csv?month=${encodeURIComponent(state.month)}`;
  });
  $("#backupJson").addEventListener("click", () => {
    window.location.href = "/api/backup.json";
  });
}

async function setMonth(month, preferredDate = "") {
  if (!isMonthKey(month)) return;
  state.month = month;
  state.date = preferredDate || (state.date.startsWith(month) ? state.date : defaultDateForMonth(month));
  $("#monthPicker").value = state.month;
  await refreshMonth();
}

async function shiftMonth(delta) {
  const [year, month] = state.month.split("-").map(Number);
  const shifted = new Date(year, month - 1 + delta, 1, 12);
  const target = `${shifted.getFullYear()}-${String(shifted.getMonth() + 1).padStart(2, "0")}`;
  await setMonth(target, defaultDateForMonth(target));
}

function defaultDateForMonth(month) {
  if (month === TODAY.slice(0, 7)) return TODAY;
  const selectedDay = Number(state.date.slice(8, 10)) || 1;
  const day = Math.min(selectedDay, daysInMonth(month));
  return `${month}-${String(day).padStart(2, "0")}`;
}

async function refreshMonth({ reloadDay = true } = {}) {
  updateCalendarLabels();
  try {
    state.calendar = await fetchJson(`/api/calendar?month=${encodeURIComponent(state.month)}`);
  } catch (error) {
    state.calendar = { month: state.month, days: {}, weeks: {} };
    showToast(error.message || "日历状态读取失败");
  }
  renderCalendar();
  if (reloadDay) await loadDay();
  if (!$("#monthlySummarySection").hidden) await loadMonthlySummary();
}

function updateCalendarLabels() {
  $("#calendarMonthLabel").textContent = formatMonth(state.month);
  $("#calendarStatus").textContent = `${formatMonth(state.month)} · 点选任意日期记录，周日可写本周小结。`;
}

function renderCalendar() {
  const grid = $("#calendarGrid");
  const [year, month] = state.month.split("-").map(Number);
  const firstWeekday = new Date(year, month - 1, 1, 12).getDay();
  const totalDays = daysInMonth(state.month);
  const cells = [];

  for (let blank = 0; blank < firstWeekday; blank += 1) {
    cells.push('<div class="calendar-day-slot calendar-day-empty" aria-hidden="true"></div>');
  }
  for (let day = 1; day <= totalDays; day += 1) {
    const entryDate = `${state.month}-${String(day).padStart(2, "0")}`;
    const info = state.calendar.days?.[entryDate] || {};
    const participantIds = Array.isArray(info.participants) ? info.participants : [];
    const hasDailyReview = Boolean(info.daily_review);
    const hasWeeklySummary = Boolean(state.calendar.weeks?.[entryDate]);
    const weekday = new Date(year, month - 1, day, 12).getDay();
    const statuses = [];
    if (participantIds.includes("xiaoli")) statuses.push("小娌已记录");
    if (participantIds.includes("xiaoyuan")) statuses.push("小元已记录");
    if (hasDailyReview) statuses.push("AI 当日反馈已生成");
    if (hasWeeklySummary) statuses.push("本周小结已保存");
    const dots = [
      participantIds.includes("xiaoli") ? '<i class="calendar-day-dot xiaoli-dot"></i>' : "",
      participantIds.includes("xiaoyuan") ? '<i class="calendar-day-dot xiaoyuan-dot"></i>' : "",
      hasDailyReview ? '<i class="calendar-day-dot review-dot"></i>' : "",
    ].join("");
    const classes = [
      "calendar-day",
      entryDate === state.date ? "selected" : "",
      entryDate === TODAY ? "today" : "",
      hasWeeklySummary ? "has-weekly-summary" : "",
    ].filter(Boolean).join(" ");
    const weekLabel = weekday === 0
      ? `<span class="calendar-week-label">${hasWeeklySummary ? "已小结" : "周小结"}</span>`
      : "";
    const ariaStatus = statuses.length ? `，${statuses.join("，")}` : "，尚未记录";
    cells.push(`
      <div class="calendar-day-slot">
        <button class="${classes}" type="button" data-calendar-date="${entryDate}" aria-label="${formatDateTitle(entryDate)}${ariaStatus}">
          <span class="calendar-day-number">${day}</span>
          <span class="calendar-day-dots" aria-hidden="true">${dots}</span>
          ${weekLabel}
        </button>
      </div>
    `);
  }
  grid.innerHTML = cells.join("");
  $$('[data-calendar-date]', grid).forEach((button) => {
    button.addEventListener("click", () => void selectDate(button.dataset.calendarDate, true));
  });
}

async function selectDate(entryDate, shouldScroll = false) {
  if (!isDateInMonth(entryDate, state.month)) return;
  state.date = entryDate;
  renderCalendar();
  await loadDay();
  if (shouldScroll) {
    $("#dayWorkspace").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

async function loadDay() {
  updateSelectedDateHeading();
  try {
    const entries = await Promise.all(
      PARTICIPANTS.map((participant) => fetchJson(`/api/entries/${state.date}/${participant.id}`)),
    );
    entries.forEach((entry) => fillForm(entry.participant.id, entry));
  } catch (error) {
    showToast(error.message || "当天记录读取失败");
  }
  await Promise.all([loadAiReview("daily", state.date, "#dailyAiReviewResult"), loadWeeklySummary()]);
}

function updateSelectedDateHeading() {
  const title = formatDateTitle(state.date);
  const isToday = state.date === TODAY;
  $("#selectedDateLabel").textContent = isToday ? `今天 · ${title}` : title;
  $("#selectedDateHeading").textContent = isToday ? "今天的记录" : "这一天的记录";
  $("#selectedDateHint").textContent = isSunday(state.date)
    ? "今天是周日：先记录当天，也可以展开下方的小结，统一回看这一周。"
    : "分别写下双方所见，再让 AI 反馈可观察的互动。";
}

function fillForm(participantId, data) {
  const participant = PARTICIPANT_BY_ID[participantId];
  const form = $(participant.formId);
  ["appreciation", "event", "feeling", "need", "response", "repair_request", "follow_up"].forEach((name) => {
    form.elements[name].value = data[name] ?? (name === "follow_up" ? "none" : "");
  });
  setSaveState(
    participantId,
    data.updated_at ? `已保存 ${formatTime(data.updated_at)} · 修订 ${Number(data.revision || 1)}` : "未保存",
    Boolean(data.updated_at),
  );
}

async function saveEntry(event, participantId) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    entry_date: state.date,
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
    await refreshMonth({ reloadDay: false });
    showToast(`${PARTICIPANT_BY_ID[participantId].name}的记录已保存`);
  } catch (error) {
    showToast(error.message || "保存失败");
  }
}

async function deleteEntry(participantId) {
  const name = PARTICIPANT_BY_ID[participantId].name;
  if (!confirm(`确定清空 ${state.date} ${name}的记录吗？历史修订仍会保留在备份中。`)) return;
  try {
    await fetchJson(`/api/entries/${state.date}/${participantId}`, { method: "DELETE" });
    fillForm(participantId, await fetchJson(`/api/entries/${state.date}/${participantId}`));
    await refreshMonth({ reloadDay: false });
    showToast("已清空这一天的记录");
  } catch (error) {
    showToast(error.message || "清空失败");
  }
}

async function loadWeeklySummary() {
  const section = $("#weeklySummarySection");
  const disclosure = $("#weeklySummaryDisclosure");
  const form = $("#weeklyForm");
  if (!isSunday(state.date)) {
    section.hidden = true;
    disclosure.open = false;
    form.dataset.weekEnd = "";
    return;
  }

  const weekEnd = state.date;
  const previousWeekEnd = form.dataset.weekEnd;
  form.dataset.weekEnd = weekEnd;
  if (previousWeekEnd && previousWeekEnd !== weekEnd) disclosure.open = false;
  section.hidden = false;
  $("#weekRange").textContent = `${formatWeekRange(weekEnd)} · 周日统一记录`;

  try {
    const data = await fetchJson(`/api/weeks/${weekEnd}`);
    if (form.dataset.weekEnd !== weekEnd) return;
    fillWeeklyForm(data);
    await loadAiReview("weekly", weekEnd, "#weeklyAiReviewResult");
  } catch (error) {
    $("#weeklyAiReviewResult").className = "ai-review-result error-state";
    $("#weeklyAiReviewResult").textContent = error.message || "本周小结读取失败";
  }
}

function fillWeeklyForm(data) {
  const form = $("#weeklyForm");
  ["highlights", "recurring_pattern", "observed_adjustment", "participant_signals", "next_focus"].forEach((name) => {
    form.elements[name].value = data[name] || "";
  });
  const saveState = $("#weeklySaveState");
  saveState.textContent = data.updated_at ? `已保存 ${formatTime(data.updated_at)} · 修订 ${Number(data.revision || 1)}` : "未保存";
  saveState.classList.toggle("saved", Boolean(data.updated_at));
}

async function saveWeek(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const weekEnd = form.dataset.weekEnd;
  if (!weekEnd || !isSunday(weekEnd)) return;
  const payload = {
    week_end: weekEnd,
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
    fillWeeklyForm(saved);
    await refreshMonth({ reloadDay: false });
    showToast("本周小结已保存");
  } catch (error) {
    showToast(error.message || "本周小结保存失败");
  }
}

async function openMonthlySummary() {
  const section = $("#monthlySummarySection");
  section.hidden = false;
  $("#monthlyPeriodLabel").textContent = formatMonth(state.month);
  await loadMonthlySummary();
  section.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadMonthlySummary() {
  const section = $("#monthlySummarySection");
  if (section.hidden) return;
  try {
    const data = await fetchJson(`/api/monthly-summary?month=${encodeURIComponent(state.month)}`);
    const form = $("#monthlyForm");
    ["overall_change", "what_helped", "recurring_patterns", "needs_attention", "next_focus"].forEach((name) => {
      form.elements[name].value = data[name] || "";
    });
    await loadAiReview("monthly", state.month, "#monthlyAiReviewResult");
  } catch (error) {
    $("#monthlyAiReviewResult").className = "ai-review-result error-state";
    $("#monthlyAiReviewResult").textContent = error.message || "月度复盘读取失败";
  }
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
    await fetchJson("/api/monthly-summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await refreshMonth({ reloadDay: false });
    showToast("月度复盘已保存");
  } catch (error) {
    showToast(error.message || "月度复盘保存失败");
  }
}

async function generateAiReview(periodType, periodKey, targetSelector, button) {
  const target = $(targetSelector);
  if (!target || !button || button.disabled) return;
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
        model: localStorage.getItem(MODEL_STORAGE_KEY) || "",
      }),
    });
    renderAiReview(review, target);
    await refreshMonth({ reloadDay: false });
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
      target.textContent = periodType === "daily" ? "还没有生成当日复盘" : periodType === "weekly" ? "还没有生成本周复盘" : "还没有生成月度复盘";
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
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2400);
}

function isMonthKey(value) {
  return /^\d{4}-\d{2}$/.test(String(value || "")) && daysInMonth(String(value)) > 0;
}

function isDateInMonth(value, month) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || "")) && String(value).startsWith(`${month}-`) && Boolean(dateFromIso(value));
}

function isSunday(value) {
  const item = dateFromIso(value);
  return Boolean(item) && item.getDay() === 0;
}

function daysInMonth(month) {
  const match = /^(\d{4})-(\d{2})$/.exec(String(month || ""));
  if (!match) return 0;
  const year = Number(match[1]);
  const monthIndex = Number(match[2]);
  if (monthIndex < 1 || monthIndex > 12) return 0;
  return new Date(year, monthIndex, 0, 12).getDate();
}

function dateFromIso(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  if (!match) return null;
  const year = Number(match[1]);
  const monthIndex = Number(match[2]);
  const day = Number(match[3]);
  const result = new Date(year, monthIndex - 1, day, 12);
  return result.getFullYear() === year && result.getMonth() === monthIndex - 1 && result.getDate() === day ? result : null;
}

function formatMonth(month) {
  const [year, monthNumber] = String(month).split("-").map(Number);
  return `${year}年${monthNumber}月`;
}

function formatDateTitle(value) {
  const item = dateFromIso(value);
  if (!item) return String(value || "");
  return `${item.getFullYear()}年${item.getMonth() + 1}月${item.getDate()}日 · ${WEEKDAY_NAMES[item.getDay()]}`;
}

function formatWeekRange(weekEnd) {
  const end = dateFromIso(weekEnd);
  if (!end) return "本周";
  const start = new Date(end);
  start.setDate(start.getDate() - 6);
  const startLabel = `${start.getFullYear()}年${start.getMonth() + 1}月${start.getDate()}日`;
  const endLabel = start.getFullYear() === end.getFullYear() && start.getMonth() === end.getMonth()
    ? `${end.getDate()}日`
    : `${end.getFullYear()}年${end.getMonth() + 1}月${end.getDate()}日`;
  return `${startLabel}—${endLabel}`;
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
