const state = { entries: [], selectedId: null };
const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  })[char]);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `请求失败：${response.status}`);
  return payload;
}

function entryFromForm() {
  return {
    id: $("#entryId").value.trim(),
    title: $("#entryTitle").value.trim(),
    content: $("#entryContent").value.trim(),
    tags: $("#entryTags").value.split(",").map((item) => item.trim()).filter(Boolean),
    image_path: $("#entryImage").value.trim() || null,
    reply_templates: $("#entryReply").value.split("\n").map((item) => item.trim()).filter(Boolean)
  };
}

function fillForm(entry) {
  $("#entryId").value = entry?.id || "";
  $("#entryTitle").value = entry?.title || "";
  $("#entryTags").value = (entry?.tags || []).join(", ");
  $("#entryImage").value = entry?.image_path || "";
  $("#entryContent").value = entry?.content || "";
  $("#entryReply").value = (entry?.reply_templates || []).join("\n");
  state.selectedId = entry?.id || null;
  renderEntries();
}

function renderEntries() {
  $("#entryCount").textContent = `${state.entries.length} 条`;
  $("#entryList").innerHTML = state.entries.map((entry) => `
    <button class="entry-button ${entry.id === state.selectedId ? "active" : ""}" data-id="${escapeHtml(entry.id)}">
      <strong>${escapeHtml(entry.title)}</strong>
      <small>${escapeHtml(entry.tags.join(" / "))}</small>
    </button>
  `).join("");
  document.querySelectorAll(".entry-button").forEach((button) => {
    button.addEventListener("click", () => {
      fillForm(state.entries.find((item) => item.id === button.dataset.id));
    });
  });
}

async function loadEntries() {
  const data = await requestJson("/api/kb");
  state.entries = data.entries;
  renderEntries();
  if (!state.selectedId && state.entries.length) fillForm(state.entries[0]);
  await loadStatus();
}

async function loadStatus() {
  const status = await requestJson("/api/kb/status");
  $("#kbStatus").textContent = `${status.entries} 条知识，${status.backups} 个备份。最近备份：${status.latest_backup ? status.latest_backup.split("/").pop() : "无"}`;
  const github = await requestJson("/api/kb/github/status");
  $("#githubStatus").textContent = `Git 仓库：${github.entries} 条，提交：${github.commit || "无"}，远程：${github.remote || "未配置"}`;
}

async function loadLearningQueue() {
  const data = await requestJson("/api/learning/candidates?status=pending");
  $("#learningStatus").textContent = `${data.candidates.length} 条待审核`;
  $("#learningList").innerHTML = data.candidates.map((item) => `
    <article class="result-card">
      <strong>${escapeHtml(item.suggested_entry.title)}</strong>
      <p>${escapeHtml(item.reason)}</p>
      <p>${escapeHtml(item.source_text)}</p>
      <div class="chips">${item.suggested_entry.tags.map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("")}</div>
      <div class="learning-actions">
        <button data-approve="${escapeHtml(item.id)}">采纳进知识库</button>
        <button data-reject="${escapeHtml(item.id)}">拒绝</button>
      </div>
    </article>
  `).join("") || '<div class="result-card"><p>暂无待审核学习候选。客服互动越多，这里会出现未命中或冲突问题。</p></div>';
  document.querySelectorAll("[data-approve]").forEach((button) => {
    button.addEventListener("click", () => approveCandidate(button.dataset.approve));
  });
  document.querySelectorAll("[data-reject]").forEach((button) => {
    button.addEventListener("click", () => rejectCandidate(button.dataset.reject));
  });
}

async function loadInteractions() {
  const data = await requestJson("/api/interactions?limit=5");
  $("#interactionStatus").textContent = `${data.total} 条采集记录`;
  $("#interactionList").innerHTML = data.records.map((record) => {
    const firstHint = record.output.hints[0];
    const input = record.ocr_text || record.raw_text || "无文本";
    return `
      <article class="result-card">
        <strong>${escapeHtml(record.source)} · ${escapeHtml(record.input_type)}</strong>
        <p>${escapeHtml(input.slice(0, 90))}</p>
        <p>${escapeHtml(firstHint ? firstHint.suggested_reply : "无输出建议")}</p>
      </article>
    `;
  }).join("") || '<div class="result-card"><p>暂无采集记录。使用原生悬浮助手框选或粘贴分析后会自动记录。</p></div>';
}

async function saveEntry() {
  const entry = entryFromForm();
  if (!entry.id || !entry.title || !entry.content) {
    throw new Error("条目 ID、标题、知识内容不能为空");
  }
  const saved = await requestJson(`/api/kb/entry/${encodeURIComponent(entry.id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry)
  });
  $("#saveStatus").textContent = "已保存并同步";
  state.selectedId = saved.id;
  await loadEntries();
}

async function importEntries() {
  const raw = $("#importJson").value.trim();
  if (!raw) throw new Error("请粘贴 JSON 数据");
  const payload = JSON.parse(raw);
  const entries = Array.isArray(payload) ? payload : payload.entries;
  const result = await requestJson("/api/kb/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entries, mode: "upsert" })
  });
  $("#saveStatus").textContent = `已导入 ${result.created} 条，更新 ${result.updated} 条`;
  await loadEntries();
}

async function testSearch() {
  $("#testStatus").textContent = "测试中";
  const data = await requestJson("/api/kb/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: $("#testQuery").value, limit: 6 })
  });
  $("#testStatus").textContent = `命中 ${data.matches.length} 条`;
  $("#testResults").innerHTML = data.matches.map((match) => `
    <article class="result-card">
      <strong>${escapeHtml(match.entry.title)} · 分数 ${match.score}</strong>
      <p>${escapeHtml(match.entry.content)}</p>
      <div class="chips">${match.reasons.map((reason) => `<span class="chip">${escapeHtml(reason)}</span>`).join("")}</div>
    </article>
  `).join("") || '<div class="result-card"><p>没有命中，建议补充标签、标题关键词或正文说法。</p></div>';
}

async function ingestTestQuery() {
  const text = $("#testQuery").value.trim();
  if (!text) return;
  await requestJson("/api/learning/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: "trainer_test", messages: [{ id: "trainer-test", sender: "customer", text }] })
  });
  await loadLearningQueue();
}

async function approveCandidate(id) {
  await requestJson(`/api/learning/candidates/${encodeURIComponent(id)}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "approved", review_note: "trainer approved" })
  });
  $("#saveStatus").textContent = "已采纳学习候选，并写入正式知识库";
  await loadEntries();
  await loadLearningQueue();
}

async function rejectCandidate(id) {
  await requestJson(`/api/learning/candidates/${encodeURIComponent(id)}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "rejected", review_note: "trainer rejected" })
  });
  $("#saveStatus").textContent = "已拒绝学习候选";
  await loadLearningQueue();
}

$("#newBtn").addEventListener("click", () => {
  fillForm({ id: "", title: "", content: "", tags: [], image_path: "/static/assets/window-system.svg", reply_templates: [] });
  $("#saveStatus").textContent = "新建中";
});
$("#saveBtn").addEventListener("click", () => saveEntry().catch((error) => { $("#saveStatus").textContent = error.message; }));
$("#importBtn").addEventListener("click", () => importEntries().catch((error) => { $("#saveStatus").textContent = error.message; }));
$("#exportBtn").addEventListener("click", () => {
  $("#importJson").value = JSON.stringify({ entries: state.entries }, null, 2);
  $("#saveStatus").textContent = "已生成导出 JSON";
});
$("#testBtn").addEventListener("click", () => testSearch().then(ingestTestQuery).catch((error) => { $("#testStatus").textContent = error.message; }));
$("#backupBtn").addEventListener("click", async () => {
  try {
    await requestJson("/api/kb/backup", { method: "POST" });
    await loadStatus();
    $("#saveStatus").textContent = "已手动备份";
  } catch (error) {
    $("#saveStatus").textContent = error.message;
  }
});
$("#githubBackupBtn").addEventListener("click", async () => {
  try {
    const github = await requestJson("/api/kb/github/export", { method: "POST" });
    $("#githubStatus").textContent = `已生成：${github.entries} 条，素材 ${github.assets} 个，提交 ${github.commit || "无"}`;
  } catch (error) {
    $("#githubStatus").textContent = error.message;
  }
});
$("#exportDistillBtn").addEventListener("click", async () => {
  try {
    const result = await requestJson("/api/interactions/export", { method: "POST" });
    $("#interactionStatus").textContent = `已导出：${result.output_path.split("/").pop()}`;
    await loadInteractions();
  } catch (error) {
    $("#interactionStatus").textContent = error.message;
  }
});

loadEntries().then(testSearch).then(loadLearningQueue).then(loadInteractions).catch((error) => { $("#saveStatus").textContent = error.message; });
