const assistantWindow = document.querySelector("#assistantWindow");
const dragbar = document.querySelector("#dragbar");
const inputText = document.querySelector("#inputText");
const hintStream = document.querySelector("#hintStream");
const statusText = document.querySelector("#statusText");

const escapeHtml = (value) => value.replace(/[&<>"']/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#039;"
})[char]);

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `请求失败：${response.status}`);
  }
  return payload;
}

function renderHints(hints) {
  if (!hints.length) {
    hintStream.innerHTML = '<div class="empty">没有生成客户侧提示。请确认文本里包含客户消息。</div>';
    return;
  }

  hintStream.innerHTML = hints.map((hint) => {
    const matches = (hint.matched_entries || []).slice(0, 3);
    const chips = matches.map((match) => `<span class="chip">${escapeHtml(match.entry.title)}</span>`).join("");
    const warning = hint.warnings?.length ? `<div class="warning">${escapeHtml(hint.warnings.join("；"))}</div>` : "";
    return `
      <article class="hint-card">
        <div class="hint-head">
          <span class="intent">${escapeHtml(hint.intent)}</span>
          <span class="confidence">${Math.round(hint.confidence * 100)}%</span>
        </div>
        <p class="message"><strong>互动分析：</strong>${escapeHtml(hint.interaction_analysis || hint.summary)}</p>
        ${warning}
        <div class="reply"><strong>可复制回复：</strong>${escapeHtml(hint.suggested_reply)}</div>
        <div class="chips">${chips}</div>
      </article>
    `;
  }).join("");
}

async function analyzeText() {
  statusText.textContent = "识别中";
  const recognized = await requestJson("/api/recognize-text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: inputText.value })
  });
  const analyzed = await requestJson("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: recognized.messages, include_safety: true })
  });
  renderHints(analyzed.hints);
  statusText.textContent = `已生成 ${analyzed.hints.length} 条提示`;
}

async function analyzeImage(file) {
  statusText.textContent = "OCR 中";
  const form = new FormData();
  form.append("file", file);
  const recognized = await requestJson("/api/recognize-image", { method: "POST", body: form });
  if (recognized.text) {
    inputText.value = recognized.text;
  }
  const analyzed = recognized.messages.length ? await requestJson("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: recognized.messages, include_safety: true })
  }) : { hints: [] };
  renderHints(analyzed.hints);
  statusText.textContent = recognized.warnings?.length ? recognized.warnings[0] : `已生成 ${analyzed.hints.length} 条提示`;
}

document.querySelector("#analyzeBtn").addEventListener("click", () => {
  analyzeText().catch((error) => {
    statusText.textContent = error.message;
  });
});

document.querySelector("#pasteBtn").addEventListener("click", async () => {
  try {
    inputText.value = await navigator.clipboard.readText();
    await analyzeText();
  } catch (error) {
    statusText.textContent = "浏览器未授权剪贴板，手动粘贴后再生成。";
  }
});

document.querySelector("#screenshotInput").addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (file) {
    analyzeImage(file).catch((error) => {
      statusText.textContent = error.message;
    });
  }
});

document.querySelector("#compactBtn").addEventListener("click", () => {
  assistantWindow.classList.toggle("compact");
});

let startX = 0;
let startY = 0;
let startRight = 0;
let startTop = 0;
let dragging = false;

dragbar.addEventListener("pointerdown", (event) => {
  if (event.target.closest("button, a")) return;
  dragging = true;
  startX = event.clientX;
  startY = event.clientY;
  const rect = assistantWindow.getBoundingClientRect();
  startRight = window.innerWidth - rect.right;
  startTop = rect.top;
  dragbar.setPointerCapture(event.pointerId);
});

dragbar.addEventListener("pointermove", (event) => {
  if (!dragging) return;
  const nextRight = Math.max(0, Math.min(window.innerWidth - 80, startRight - (event.clientX - startX)));
  const nextTop = Math.max(0, Math.min(window.innerHeight - 48, startTop + (event.clientY - startY)));
  assistantWindow.style.right = `${nextRight}px`;
  assistantWindow.style.top = `${nextTop}px`;
});

dragbar.addEventListener("pointerup", () => {
  dragging = false;
});

analyzeText().catch((error) => {
  statusText.textContent = error.message;
});
