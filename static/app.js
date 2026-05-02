const state = {
  messages: [],
  hints: []
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => ({
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

function renderMessages() {
  const list = $("#messageList");
  if (!state.messages.length) {
    list.innerHTML = '<div class="empty-state">还没有识别到消息。</div>';
    return;
  }
  list.innerHTML = state.messages.map((message) => `
    <article class="message ${message.sender === "agent" ? "agent" : "customer"}" id="${escapeHtml(message.id)}">
      <div class="avatar">${message.sender === "agent" ? "客" : "用"}</div>
      <div class="bubble">${escapeHtml(message.text)}</div>
    </article>
  `).join("");
}

function renderHints() {
  const rail = $("#hintRail");
  if (!state.hints.length) {
    rail.innerHTML = '<div class="empty-state">识别窗口内容后，提示会贴在对应消息旁边。</div>';
    return;
  }
  rail.innerHTML = state.hints.map((hint) => {
    const matches = hint.matched_entries || [];
    const tags = matches.slice(0, 2).map((match) => `<span class="tag">${escapeHtml(match.entry.title)}</span>`).join("");
    const warnings = hint.warnings?.length ? `<p class="warning">${escapeHtml(hint.warnings.join("；"))}</p>` : "";
    return `
      <article class="hint-card" data-message="${escapeHtml(hint.message_id)}">
        <strong>${escapeHtml(hint.intent)} · 置信度 ${Math.round(hint.confidence * 100)}%</strong>
        <p><strong>互动分析：</strong>${escapeHtml(hint.interaction_analysis || hint.summary)}</p>
        ${warnings}
        <div class="reply"><strong>可复制回复：</strong>${escapeHtml(hint.suggested_reply)}</div>
        <div class="tag-row">${tags}</div>
      </article>
    `;
  }).join("");
}

function renderKnowledge(entries) {
  $("#kbCount").textContent = `${entries.length} 条`;
  $("#kbList").innerHTML = entries.map((entry) => `
    <article class="kb-item">
      <img src="${escapeHtml(entry.image_path || "/static/assets/refund.svg")}" alt="${escapeHtml(entry.title)}" />
      <div>
        <strong>${escapeHtml(entry.title)}</strong>
        <p>${escapeHtml(entry.tags.join(" / "))}</p>
      </div>
    </article>
  `).join("");
}

async function loadKnowledge() {
  const data = await requestJson("/api/kb");
  renderKnowledge(data.entries);
}

async function recognizeText() {
  $("#recognitionStatus").textContent = "识别中";
  $("#recognitionWarnings").textContent = "";
  const data = await requestJson("/api/recognize-text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: $("#windowText").value })
  });
  state.messages = data.messages;
  renderMessages();
  $("#recognitionStatus").textContent = `识别到 ${data.messages.length} 条`;
}

async function recognizeImage(file) {
  $("#recognitionStatus").textContent = "OCR 中";
  const form = new FormData();
  form.append("file", file);
  const data = await requestJson("/api/recognize-image", { method: "POST", body: form });
  $("#windowText").value = data.text || $("#windowText").value;
  state.messages = data.messages;
  renderMessages();
  $("#recognitionWarnings").textContent = (data.warnings || []).join("；");
  $("#recognitionStatus").textContent = `识别到 ${data.messages.length} 条`;
}

async function analyze() {
  if (!state.messages.length) {
    await recognizeText();
  }
  const data = await requestJson("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: state.messages, include_safety: true })
  });
  state.hints = data.hints;
  renderHints();
}

$("#recognizeTextBtn").addEventListener("click", () => recognizeText().catch((error) => {
  $("#recognitionWarnings").textContent = error.message;
}));

$("#analyzeBtn").addEventListener("click", () => analyze().catch((error) => {
  $("#recognitionWarnings").textContent = error.message;
}));

$("#imageInput").addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (file) {
    recognizeImage(file).catch((error) => {
      $("#recognitionWarnings").textContent = error.message;
    });
  }
});

loadKnowledge().then(recognizeText).then(analyze).catch((error) => {
  $("#recognitionWarnings").textContent = error.message;
});
