const state = {
  imageFile: null,
  lastReply: ""
};

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
  if (!response.ok) {
    throw new Error(payload.detail || `请求失败：${response.status}`);
  }
  return payload;
}

function setStatus(text) {
  $("#statusLine").textContent = text;
}

async function loadStatus() {
  const status = await requestJson("/api/kb/status");
  $("#kbCount").textContent = `${status.entries} 条`;
  $("#kbSource").textContent = `知识文件：${status.source_file}`;
}

function setImage(file) {
  state.imageFile = file;
  const preview = $("#preview");
  preview.src = URL.createObjectURL(file);
  preview.hidden = false;
  setStatus(`已选择：${file.name}`);
}

function renderAnalysis(payload) {
  const hint = payload.analysis?.hints?.[0];
  if (!hint) {
    $("#analysisText").innerHTML = "没有生成分析。";
    $("#replyText").value = "";
    $("#matchList").innerHTML = "";
    return;
  }
  state.lastReply = hint.suggested_reply || "";
  $("#analysisText").innerHTML = `
    <p><strong>${escapeHtml(hint.intent)}</strong> · 置信度 ${Math.round((hint.confidence || 0) * 100)}%</p>
    <p>${escapeHtml(hint.interaction_analysis || hint.summary)}</p>
    ${payload.llm_enabled ? "" : "<p class='warning'>未配置 Vision API Key，当前为本地知识库匹配与规则分析。</p>"}
  `;
  $("#replyText").value = state.lastReply;
  $("#matchList").innerHTML = (hint.matched_entries || []).map((match) => `
    <article class="match-item">
      <strong>${escapeHtml(match.entry.title)}</strong>
      <span>得分 ${match.score}</span>
      <p>${escapeHtml((match.entry.content || "").slice(0, 130))}...</p>
    </article>
  `).join("") || "<div class='empty-state'>暂无知识命中。</div>";
}

async function analyzeImage() {
  if (!state.imageFile) {
    throw new Error("请先上传图片。");
  }
  const form = new FormData();
  form.append("file", state.imageFile);
  form.append("question", $("#question").value);
  form.append("session_id", "web-tool");
  setStatus("正在识图分析...");
  const payload = await requestJson("/api/vision/analyze", { method: "POST", body: form });
  renderAnalysis(payload);
  setStatus(`分析完成，图片已安全保存：${payload.upload_path}`);
}

async function feedKnowledge(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  $("#feedStatus").textContent = "入库中";
  const payload = await requestJson("/api/kb/feed", { method: "POST", body: form });
  $("#feedStatus").textContent = `已入库：${payload.entry.title}`;
  event.currentTarget.reset();
  await loadStatus();
}

async function copyReply() {
  const text = $("#replyText").value || state.lastReply;
  if (!text.trim()) {
    setStatus("没有可复制回复。");
    return;
  }
  await navigator.clipboard.writeText(text);
  setStatus("回复已复制。");
}

function initUpload() {
  const input = $("#imageInput");
  const dropZone = $("#dropZone");
  input.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) setImage(file);
  });
  dropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
    const file = event.dataTransfer.files?.[0];
    if (file) setImage(file);
  });
}

function init() {
  initUpload();
  $("#analyzeBtn").addEventListener("click", () => analyzeImage().catch((error) => setStatus(error.message)));
  $("#copyReplyBtn").addEventListener("click", () => copyReply().catch((error) => setStatus(error.message)));
  $("#feedForm").addEventListener("submit", (event) => feedKnowledge(event).catch((error) => {
    $("#feedStatus").textContent = error.message;
  }));
  $("#backupBtn").addEventListener("click", () => requestJson("/api/kb/backup", { method: "POST" }).then(loadStatus).catch((error) => setStatus(error.message)));
  loadStatus().catch((error) => setStatus(error.message));
}

window.addEventListener("DOMContentLoaded", init);
