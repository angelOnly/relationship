const $ = (selector, root = document) => root.querySelector(selector);

const OWNER_LABELS = { both: "共同", me: "我", partner: "他" };
const STATUS_LABELS = {
  suggested: "AI 建议",
  active: "进行中",
  paused: "已暂停",
  completed: "已完成",
  archived: "已归档",
};

document.addEventListener("DOMContentLoaded", () => {
  $("#actionForm").addEventListener("submit", createGoal);
  document.addEventListener("click", handleActionClick);
  loadActions();
});

async function loadActions() {
  try {
    const items = await fetchJson("/api/action-items");
    renderBaseline($("#boundaryList"), items.filter((item) => item.source === "baseline" && item.kind === "boundary"));
    renderBaseline($("#practiceList"), items.filter((item) => item.source === "baseline" && item.kind === "practice"));

    const goals = items.filter((item) => item.kind === "goal");
    const current = goals.filter((item) => ["suggested", "active"].includes(item.status));
    const history = goals.filter((item) => !["suggested", "active"].includes(item.status));
    $("#activeGoalCount").textContent = `${current.length} 项`;
    renderGoals($("#goalList"), current, "还没有当前目标。可手动添加，或从 AI 复盘中生成。");
    renderGoals($("#actionHistory"), history, "还没有历史目标");
  } catch (error) {
    ["#boundaryList", "#practiceList", "#goalList"].forEach((selector) => {
      $(selector).className = "dynamic-action-list error-state";
      $(selector).textContent = error.message || "行动清单读取失败";
    });
  }
}

function renderBaseline(container, items) {
  if (!items.length) {
    container.className = "action-list empty-state";
    container.textContent = "暂无长期规则";
    return;
  }
  container.className = "action-list";
  container.innerHTML = items.map((item) => `
    <article class="action-item">
      <b>${escapeHtml(item.title)}</b>
      <p>${escapeHtml(item.detail)}</p>
    </article>
  `).join("");
}

function renderGoals(container, items, emptyText) {
  if (!items.length) {
    container.className = "dynamic-action-list empty-state";
    container.textContent = emptyText;
    return;
  }
  container.className = "dynamic-action-list";
  container.innerHTML = items.map(goalCard).join("");
}

function goalCard(item) {
  return `
    <article class="goal-card status-${escapeHtml(item.status)}">
      <div class="goal-meta">
        <span>${escapeHtml(OWNER_LABELS[item.owner] || item.owner)}</span>
        <span>${escapeHtml(STATUS_LABELS[item.status] || item.status)}</span>
        <span>${escapeHtml(sourceLabel(item.source))}</span>
      </div>
      <h3>${escapeHtml(item.title)}</h3>
      ${item.detail ? `<p>${escapeHtml(item.detail)}</p>` : ""}
      <div class="goal-actions">${goalButtons(item)}</div>
    </article>
  `;
}

function goalButtons(item) {
  const button = (status, label, style = "subtle") => (
    `<button class="button ${style}" type="button" data-action-id="${item.id}" data-next-status="${status}">${label}</button>`
  );
  if (item.status === "suggested") return button("active", "采纳", "primary") + button("archived", "忽略");
  if (item.status === "active") return button("completed", "标记完成", "primary") + button("paused", "暂停");
  if (item.status === "paused") return button("active", "恢复", "primary") + button("archived", "归档");
  if (item.status === "completed") return button("active", "重新开始") + button("archived", "归档");
  return button("active", "恢复为当前目标");
}

async function createGoal(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = $("button[type='submit']", form);
  submit.disabled = true;
  try {
    await fetchJson("/api/action-items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        owner: form.elements.owner.value,
        kind: "goal",
        title: form.elements.title.value,
        detail: form.elements.detail.value,
      }),
    });
    form.reset();
    showToast("已加入当前目标");
    await loadActions();
  } catch (error) {
    showToast(error.message || "目标添加失败");
  } finally {
    submit.disabled = false;
  }
}

async function handleActionClick(event) {
  const button = event.target.closest("[data-action-id]");
  if (!button) return;
  button.disabled = true;
  try {
    await fetchJson(`/api/action-items/${button.dataset.actionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: button.dataset.nextStatus }),
    });
    showToast(`目标已更新为“${STATUS_LABELS[button.dataset.nextStatus]}”`);
    await loadActions();
  } catch (error) {
    showToast(error.message || "目标状态更新失败");
    button.disabled = false;
  }
}

function sourceLabel(source) {
  if (source === "manual") return "手动添加";
  if (source === "ai_daily") return "每日 AI";
  if (source === "ai_weekly") return "每周 AI";
  if (source === "ai_monthly") return "每月 AI";
  return source;
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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
