const assistantWindow = document.querySelector("#assistantWindow");
const dragbar = document.querySelector("#dragbar");
const inputText = document.querySelector("#inputText");
const hintStream = document.querySelector("#hintStream");
const statusText = document.querySelector("#statusText");

const escapeHtml = (value) => String(value || "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#039;"
})[char]);

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `请求失败：${response.status}`);
  return payload;
}

function renderHints(hints) {
  if (!hints || !hints.length) {
    hintStream.innerHTML = '<div class="empty">没有生成针对性的回复建议。请尝试捕捉一段具体的客户咨询内容。</div>';
    return;
  }

  hintStream.innerHTML = hints.map((hint) => {
    const matches = (hint.matched_entries || []).slice(0, 3);
    const chips = matches.map((m) => `<span class="chip">${escapeHtml(m.entry.title)}</span>`).join("");
    
    // 安全警告模块
    const warningHtml = hint.warnings?.length 
        ? `<div class="card-section warning-box">
             <span class="section-label">风险拦截</span>
             <div class="warning-item">${escapeHtml(hint.warnings.join("；"))}</div>
           </div>` 
        : "";

    // 匹配来源模块
    const sourceHtml = chips 
        ? `<div class="card-section source-box">
             <span class="section-label">知识来源</span>
             <div class="chips">${chips}</div>
           </div>` 
        : "";

    return `
      <article class="hint-card">
        <div class="hint-head">
          <span class="intent-tag">${escapeHtml(hint.intent)}</span>
          <span class="confidence-meter">匹配度 ${Math.round(hint.confidence * 100)}%</span>
        </div>
        
        <div class="card-section analysis-box">
          <span class="section-label">本地分析</span>
          <div class="analysis-text">${escapeHtml(hint.interaction_analysis || hint.summary)}</div>
        </div>

        ${warningHtml}

        <div class="card-section reply-box" onclick="copyReply(this)">
          <span class="section-label">建议回复</span>
          <div class="reply-text">${escapeHtml(hint.suggested_reply)}</div>
          <span class="copy-hint">点击文字即可一键复制</span>
        </div>

        ${sourceHtml}
      </article>
    `;
  }).join("");
}

window.copyReply = (el) => {
    const text = el.querySelector('.reply-text').innerText;
    navigator.clipboard.writeText(text).then(() => {
        const originalLabel = el.querySelector('.section-label').innerText;
        el.querySelector('.section-label').innerText = "✅ 已复制到剪贴板";
        el.style.background = "#dcfce7";
        setTimeout(() => {
            el.querySelector('.section-label').innerText = originalLabel;
            el.style.background = "";
        }, 2000);
    });
};

async function analyzeText() {
  if (!inputText.value.trim()) return;
  statusText.textContent = "正在本地分析...";
  try {
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
      statusText.textContent = `就绪 (生成了 ${analyzed.hints.length} 条建议)`;
  } catch (e) {
      statusText.textContent = "分析出错，请检查 API 配置";
  }
}

const fileToBase64 = (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = error => reject(error);
});

async function analyzeImage(file) {
  statusText.textContent = "视觉分析中...";
  const form = new FormData();
  form.append("file", file);
  try {
      const recognized = await requestJson("/api/recognize-image", { method: "POST", body: form });
      if (recognized.text) inputText.value = recognized.text;
      
      if (recognized.messages.length) {
          const b64Data = await fileToBase64(file);
          const analyzed = await requestJson("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
                messages: recognized.messages, 
                include_safety: true,
                image_bytes: b64Data
            })
          });
          renderHints(analyzed.hints);
      }
      statusText.textContent = "分析完成";
  } catch (e) {
      statusText.textContent = "OCR/AI 分析失败";
  }
}

// 绑定事件
document.querySelector("#analyzeBtn").addEventListener("click", analyzeText);
document.querySelector("#pasteBtn").addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    inputText.value = text;
    await analyzeText();
  } catch (e) { statusText.textContent = "请手动粘贴文本"; }
});

document.querySelector("#screenshotInput").addEventListener("change", (e) => {
  if (e.target.files?.[0]) analyzeImage(e.target.files[0]);
});

document.querySelector("#compactBtn").addEventListener("click", () => assistantWindow.classList.toggle("compact"));

// 拖拽逻辑保持现状...
let startX = 0, startY = 0, startRight = 0, startTop = 0, dragging = false;
dragbar.addEventListener("pointerdown", (e) => {
  if (e.target.closest("button, a")) return;
  dragging = true;
  startX = e.clientX; startY = e.clientY;
  const rect = assistantWindow.getBoundingClientRect();
  startRight = window.innerWidth - rect.right;
  startTop = rect.top;
  dragbar.setPointerCapture(e.pointerId);
});
dragbar.addEventListener("pointermove", (e) => {
  if (!dragging) return;
  assistantWindow.style.right = `${Math.max(0, startRight - (e.clientX - startX))}px`;
  assistantWindow.style.top = `${Math.max(0, startTop + (e.clientY - startY))}px`;
});
dragbar.addEventListener("pointerup", () => dragging = false);

// 初始化加载
if (inputText.value.trim()) analyzeText();
