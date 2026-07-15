const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const CATEGORY_LABELS = {
  talk: "需要沟通",
  let_go: "暂时放下",
  triggered: "情绪触发",
};

const ACTIONS = {
  me: [
    ["no_mockery", "没有嘲讽、挖苦"],
    ["no_personal_attack", "没有人格贬低"],
    ["no_old_score_dump", "没有翻旧账轰炸"],
    ["no_voice_escalation", "没有提高音量压人"],
    ["pause_when_triggered", "上头时有暂停"],
  ],
  partner: [
    ["reason_plus_action", "解释之后补了行动"],
    ["no_silent_avoidance", "没有沉默逃避"],
    ["no_personality_as_excuse", "没有把性格当终点"],
    ["ask_before_changing", "改动前有先询问"],
    ["give_specific_feedback", "给了具体正反馈"],
  ],
};

const state = {
  month: currentMonth(),
  date: localDateString(new Date()),
  history: [],
};

document.addEventListener("DOMContentLoaded", () => {
  setupScoreRows();
  setupTabs();
  setupDateAndMonth();
  setupForms();
  setupToolbar();
  loadAll();
});

function setupScoreRows() {
  renderScoreRows("me", $("#meScores"));
  renderScoreRows("partner", $("#partnerScores"));
}

function renderScoreRows(person, container) {
  container.innerHTML = ACTIONS[person].map(([key, label]) => `
    <div class="score-row">
      <label for="${person}-${key}">${escapeHtml(label)}</label>
      <select id="${person}-${key}" name="score_${key}" data-score-key="${key}">
        <option value="3">3</option>
        <option value="2">2</option>
        <option value="1">1</option>
        <option value="0">0</option>
      </select>
    </div>
  `).join("");
}

function setupTabs() {
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".tab").forEach((item) => item.classList.remove("active"));
      $$(".tab-panel").forEach((item) => item.classList.remove("active"));
      tab.classList.add("active");
      $(`#${tab.dataset.tab}`).classList.add("active");
      if (tab.dataset.tab === "history") loadHistory();
      if (tab.dataset.tab === "weekly") loadWeeks();
      if (tab.dataset.tab === "monthly") loadMonthlySummary();
    });
  });
}

function setupDateAndMonth() {
  const monthPicker = $("#monthPicker");
  const datePicker = $("#datePicker");
  monthPicker.value = state.month;
  datePicker.value = state.date;

  monthPicker.addEventListener("change", () => {
    state.month = monthPicker.value || currentMonth();
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
  const today = localDateString(new Date());
  state.date = today.startsWith(state.month) ? today : `${state.month}-01`;
  $("#datePicker").value = state.date;
  loadHistory();
  loadWeeks();
  loadMonthlySummary();
}

function setupForms() {
  $("#meForm").addEventListener("submit", (event) => saveEntry(event, "me"));
  $("#partnerForm").addEventListener("submit", (event) => saveEntry(event, "partner"));
  $$('[data-delete]').forEach((button) => {
    button.addEventListener("click", () => deleteEntry(button.dataset.delete));
  });
  $("#monthlyForm").addEventListener("submit", saveMonthlySummary);
}

function setupToolbar() {
  $("#loadDate").addEventListener("click", loadDay);
  let timer;
  $("#searchInput").addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(loadHistory, 250);
  });
  $("#filterCategory").addEventListener("change", loadHistory);
  $("#exportCsv").addEventListener("click", () => {
    window.location.href = `/api/export.csv?month=${encodeURIComponent(state.month)}`;
  });
  $("#backupJson").addEventListener("click", () => {
    window.location.href = "/api/backup.json";
  });
}

async function loadAll() {
  await loadDay();
  await Promise.all([loadHistory(), loadWeeks(), loadMonthlySummary()]);
}

async function loadDay() {
  state.date = $("#datePicker").value || localDateString(new Date());
  state.month = state.date.slice(0, 7);
  $("#monthPicker").value = state.month;

  const [me, partner] = await Promise.all([
    fetchJson(`/api/entries/${state.date}/me`),
    fetchJson(`/api/entries/${state.date}/partner`),
  ]);
  fillForm("me", me);
  fillForm("partner", partner);
  showToast(`已打开 ${state.date} 的记录`);
}

function fillForm(person, data) {
  const form = person === "me" ? $("#meForm") : $("#partnerForm");
  ["positive", "dissatisfaction", "category", "feeling", "need", "better_wording", "tomorrow_request"].forEach((name) => {
    form.elements[name].value = data[name] ?? "";
  });
  ACTIONS[person].forEach(([key]) => {
    const select = $(`[data-score-key="${key}"]`, form);
    select.value = String(data.action_scores?.[key] ?? 3);
  });
  setSaveState(person, data.updated_at ? `已保存 ${formatTime(data.updated_at)}` : "未保存", Boolean(data.updated_at));
}

async function saveEntry(event, person) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    entry_date: $("#datePicker").value,
    person,
    positive: form.elements.positive.value,
    dissatisfaction: form.elements.dissatisfaction.value,
    category: form.elements.category.value,
    feeling: form.elements.feeling.value,
    need: form.elements.need.value,
    better_wording: form.elements.better_wording.value,
    tomorrow_request: form.elements.tomorrow_request.value,
    action_scores: Object.fromEntries(
      ACTIONS[person].map(([key]) => [key, Number($(`[data-score-key="${key}"]`, form).value)])
    ),
  };
  try {
    const saved = await fetchJson("/api/entries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setSaveState(person, `已保存 ${formatTime(saved.updated_at)}`, true);
    showToast(person === "me" ? "我的记录已保存" : "他的记录已保存");
    await loadHistory();
  } catch (error) {
    showToast(error.message || "保存失败");
  }
}

async function deleteEntry(person) {
  const label = person === "me" ? "我的" : "他的";
  if (!confirm(`确定清空 ${state.date} ${label}记录吗？`)) return;
  await fetchJson(`/api/entries/${state.date}/${person}`, { method: "DELETE" });
  const empty = await fetchJson(`/api/entries/${state.date}/${person}`);
  fillForm(person, empty);
  await loadHistory();
  showToast("已清空当天记录");
}

async function loadHistory() {
  if (!$("#historyList")) return;
  const q = $("#searchInput").value.trim();
  const category = $("#filterCategory").value;
  const params = new URLSearchParams({ month: state.month });
  if (q) params.set("q", q);
  if (category) params.set("category", category);
  state.history = await fetchJson(`/api/entries?${params}`);
  renderHistory(state.history);
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
  container.innerHTML = entries.map((entry) => {
    const personLabel = entry.person === "me" ? "我写的" : "他写的";
    const score = actionScore(entry.action_scores);
    return `
      <article class="history-card">
        <div class="history-head">
          <strong>${escapeHtml(entry.entry_date)} · ${personLabel}</strong>
          <span class="category-pill category-${entry.category}">${CATEGORY_LABELS[entry.category]} · 行动 ${score}/15</span>
        </div>
        <div class="history-body">
          ${historyPair("看见的好", entry.positive)}
          ${historyPair("今天不满", entry.dissatisfaction)}
          ${historyPair("真实感受", entry.feeling)}
          ${historyPair("真正需求", entry.need)}
          ${historyPair("更好表达", entry.better_wording)}
          ${historyPair("明日请求", entry.tomorrow_request)}
          <button class="button subtle" onclick="openHistoryDate('${entry.entry_date}')">打开这一天</button>
        </div>
      </article>
    `;
  }).join("");
}

function historyPair(label, value) {
  return `<div class="history-pair"><b>${label}</b><span>${escapeHtml(value || "—")}</span></div>`;
}

window.openHistoryDate = async function openHistoryDate(entryDate) {
  $("#datePicker").value = entryDate;
  state.date = entryDate;
  await loadDay();
  $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === 'daily'));
  $$('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === 'daily'));
  window.scrollTo({ top: 0, behavior: "smooth" });
};

async function loadWeeks() {
  const existing = await fetchJson(`/api/weeks?month=${encodeURIComponent(state.month)}`);
  const byWeek = Object.fromEntries(existing.map((item) => [item.week_no, item]));
  const grid = $("#weeklyGrid");
  if (!grid) return;
  grid.innerHTML = [1, 2, 3, 4, 5].map((week) => weekForm(week, byWeek[week] || {})).join("");
  $$(".week-form", grid).forEach((form) => {
    form.addEventListener("submit", saveWeek);
  });
}

function weekForm(week, data) {
  return `
    <form class="panel week-form" data-week="${week}">
      <div class="panel-heading">
        <div><span class="eyebrow">${state.month}</span><h3>第 ${week} 周小结</h3></div>
        <span class="save-state">${data.updated_at ? `已保存 ${formatTime(data.updated_at)}` : "未保存"}</span>
      </div>
      <div class="week-fields">
        <label>这周有没有少伤害一点<textarea name="less_harm" rows="3">${escapeHtml(data.less_harm || "")}</textarea></label>
        <label>我做得有进步的地方<textarea name="my_progress" rows="3">${escapeHtml(data.my_progress || "")}</textarea></label>
        <label>他做得有进步的地方<textarea name="partner_progress" rows="3">${escapeHtml(data.partner_progress || "")}</textarea></label>
        <label>这周最大的冲突或触发<textarea name="biggest_conflict" rows="3">${escapeHtml(data.biggest_conflict || "")}</textarea></label>
        <label>下周只改一个点<textarea name="next_focus" rows="3" placeholder="只写一个重点">${escapeHtml(data.next_focus || "")}</textarea></label>
      </div>
      <div class="form-actions"><button class="button primary" type="submit">保存第 ${week} 周</button></div>
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
    less_harm: form.elements.less_harm.value,
    my_progress: form.elements.my_progress.value,
    partner_progress: form.elements.partner_progress.value,
    biggest_conflict: form.elements.biggest_conflict.value,
    next_focus: form.elements.next_focus.value,
  };
  const saved = await fetchJson("/api/weeks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  $(".save-state", form).textContent = `已保存 ${formatTime(saved.updated_at)}`;
  $(".save-state", form).classList.add("saved");
  showToast(`第 ${weekNo} 周小结已保存`);
}

async function loadMonthlySummary() {
  const data = await fetchJson(`/api/monthly-summary?month=${encodeURIComponent(state.month)}`);
  const form = $("#monthlyForm");
  if (!form) return;
  ["relationship_change", "what_worked", "unresolved", "next_month_plan"].forEach((name) => {
    form.elements[name].value = data[name] || "";
  });
  const label = data.updated_at ? `已保存 ${formatTime(data.updated_at)}` : "未保存";
  const el = $("#monthlySaveState");
  el.textContent = label;
  el.classList.toggle("saved", Boolean(data.updated_at));
}

async function saveMonthlySummary(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    month_key: state.month,
    relationship_change: form.elements.relationship_change.value,
    what_worked: form.elements.what_worked.value,
    unresolved: form.elements.unresolved.value,
    next_month_plan: form.elements.next_month_plan.value,
  };
  const saved = await fetchJson("/api/monthly-summary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const el = $("#monthlySaveState");
  el.textContent = `已保存 ${formatTime(saved.updated_at)}`;
  el.classList.add("saved");
  showToast("月度复盘已保存");
}

function setSaveState(person, text, saved) {
  const el = person === "me" ? $("#meSaveState") : $("#partnerSaveState");
  el.textContent = text;
  el.classList.toggle("saved", saved);
}

function actionScore(scores = {}) {
  return Object.values(scores).reduce((sum, value) => sum + Number(value || 0), 0);
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
