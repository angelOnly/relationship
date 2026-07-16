const $ = (selector, root = document) => root.querySelector(selector);

document.addEventListener("DOMContentLoaded", () => {
  const now = new Date();
  $("#happinessDate").value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  $("#happinessForm").addEventListener("submit", saveHappiness);
  $("#happinessList").addEventListener("click", deleteHappiness);
  loadHappiness();
});

async function loadHappiness() {
  try {
    renderHappiness(await fetchJson("/api/happiness-events"));
  } catch (error) {
    $("#happinessList").textContent = error.message || "幸福记录读取失败";
  }
}

async function saveHappiness(event) {
  event.preventDefault();
  const button = $("#saveHappiness");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "保存中…";
  try {
    await fetchJson("/api/happiness-events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_date: $("#happinessDate").value,
        content: $("#happinessContent").value.trim(),
      }),
    });
    $("#happinessContent").value = "";
    showToast("幸福事件已保存");
    await loadHappiness();
  } catch (error) {
    showToast(error.message || "保存失败");
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function deleteHappiness(event) {
  const button = event.target.closest("[data-delete-happiness]");
  if (!button || !confirm("删除这条幸福记录？")) return;
  button.disabled = true;
  try {
    await fetchJson(`/api/happiness-events/${button.dataset.deleteHappiness}`, { method: "DELETE" });
    showToast("幸福记录已删除");
    await loadHappiness();
  } catch (error) {
    showToast(error.message || "删除失败");
    button.disabled = false;
  }
}

function renderHappiness(items) {
  const container = $("#happinessList");
  $("#happinessCount").textContent = String(items.length);
  if (!items.length) {
    container.className = "happiness-list empty-state";
    container.textContent = "还没有幸福记录";
    return;
  }
  container.className = "happiness-list";
  container.innerHTML = items.map((item) => `
    <article class="happiness-card">
      <time datetime="${escapeHtml(item.event_date)}">${escapeHtml(formatDate(item.event_date))}</time>
      <p>${escapeHtml(item.content)}</p>
      <button type="button" data-delete-happiness="${item.id}">删除</button>
    </article>`).join("");
}

function formatDate(value) {
  const [year, month, day] = String(value || "").split("-");
  return year && month && day ? `${year} 年 ${Number(month)} 月 ${Number(day)} 日` : value;
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
