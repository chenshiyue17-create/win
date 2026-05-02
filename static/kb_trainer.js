const state = { entries: [], learningQueue: [], selectedId: null, selectedCandidateId: null };
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

// --- Tabs Logic ---
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            $(`#tab-${btn.dataset.tab}`).classList.add('active');
            if (btn.dataset.tab === 'kb') loadEntries();
            if (btn.dataset.tab === 'learning') loadLearningQueue();
            if (btn.dataset.tab === 'tools') { loadStatus(); loadInteractions(); }
        });
    });
}

// --- Learning Queue Logic ---
async function loadLearningQueue() {
  const data = await requestJson("/api/learning/candidates?status=pending");
  state.learningQueue = data.candidates;
  $("#learningStatus").textContent = `${data.candidates.length} 条待审核`;
  $("#learningList").innerHTML = data.candidates.map((item) => `
    <article class="result-card ${item.id === state.selectedCandidateId ? 'active' : ''}" data-cand-id="${escapeHtml(item.id)}">
      <strong>${escapeHtml(item.suggested_entry.title)}</strong>
      <div class="chips">${item.suggested_entry.tags.map(t => `<span class="chip">${escapeHtml(t)}</span>`).join('')}</div>
      <p style="font-size: 11px; color: #64748b; margin-top: 8px;">原因: ${escapeHtml(item.reason)}</p>
    </article>
  `).join("") || '<div style="padding: 20px; text-align: center; color: #64748b;">暂无新知识点，请通过悬浮窗采集评论区或对话。</div>';

  document.querySelectorAll("[data-cand-id]").forEach(card => {
    card.addEventListener('click', () => selectCandidate(card.dataset.candId));
  });
}

function selectCandidate(id) {
    state.selectedCandidateId = id;
    const item = state.learningQueue.find(i => i.id === id);
    if (!item) return;

    $("#reviewPlaceholder").classList.add('hidden');
    $("#reviewEditor").classList.remove('hidden');
    document.querySelectorAll("[data-cand-id]").forEach(c => c.classList.remove('active'));
    $(`[data-cand-id="${id}"]`).classList.add('active');

    $("#sourceText").textContent = item.source_text;
    $("#learningReason").textContent = `学习原因: ${item.reason}`;
    $("#revTitle").value = item.suggested_entry.title;
    $("#revTags").value = item.suggested_entry.tags.join(", ");
    $("#revContent").value = item.suggested_entry.content;
    $("#revReply").value = item.suggested_entry.reply_templates.join("\n");
}

async function handleApprove() {
    if (!state.selectedCandidateId) return;
    const item = state.learningQueue.find(i => i.id === state.selectedCandidateId);
    const updatedEntry = {
        ...item.suggested_entry,
        title: $("#revTitle").value,
        tags: $("#revTags").value.split(",").map(t => t.trim()).filter(Boolean),
        content: $("#revContent").value,
        reply_templates: $("#revReply").value.split("\n").map(t => t.trim()).filter(Boolean)
    };

    try {
        await requestJson(`/api/learning/candidates/${encodeURIComponent(state.selectedCandidateId)}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: "approved", review_note: "Approved via re-structured trainer" })
        });
        // 更新知识库条目（如果后端 approve 没包含内容更新逻辑，我们单独更新它，
        // 但根据模型，suggested_entry 已经包含在 approve 里了。
        // 为保险，我们直接调用一次更新接口确保修改的内容也存入）
        await requestJson(`/api/kb/entry/${encodeURIComponent(updatedEntry.id)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(updatedEntry)
        });
        
        state.selectedCandidateId = null;
        $("#reviewEditor").classList.add('hidden');
        $("#reviewPlaceholder").classList.remove('hidden');
        await loadLearningQueue();
    } catch (e) { alert(e.message); }
}

async function handleReject() {
    if (!state.selectedCandidateId) return;
    try {
        await requestJson(`/api/learning/candidates/${encodeURIComponent(state.selectedCandidateId)}/reject`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: "rejected" })
        });
        state.selectedCandidateId = null;
        $("#reviewEditor").classList.add('hidden');
        $("#reviewPlaceholder").classList.remove('hidden');
        await loadLearningQueue();
    } catch (e) { alert(e.message); }
}

// --- Knowledge Base Logic ---
async function loadEntries() {
  const data = await requestJson("/api/kb");
  state.entries = data.entries;
  renderEntries();
  if (!state.selectedId && state.entries.length) fillKBForm(state.entries[0]);
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
      fillKBForm(state.entries.find((item) => item.id === button.dataset.id));
    });
  });
}

function fillKBForm(entry) {
  $("#entryId").value = entry?.id || "";
  $("#entryTitle").value = entry?.title || "";
  $("#entryTags").value = (entry?.tags || []).join(", ");
  $("#entryContent").value = entry?.content || "";
  $("#entryReply").value = (entry?.reply_templates || []).join("\n");
  state.selectedId = entry?.id || null;
  renderEntries();
}

async function saveKBEntry() {
  const entry = {
    id: $("#entryId").value.trim(),
    title: $("#entryTitle").value.trim(),
    content: $("#entryContent").value.trim(),
    tags: $("#entryTags").value.split(",").map((item) => item.trim()).filter(Boolean),
    reply_templates: $("#entryReply").value.split("\n").map((item) => item.trim()).filter(Boolean)
  };
  if (!entry.id || !entry.title) return;
  await requestJson(`/api/kb/entry/${encodeURIComponent(entry.id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry)
  });
  $("#saveStatus").textContent = "保存成功";
  setTimeout(() => $("#saveStatus").textContent = "就绪", 2000);
  await loadEntries();
}

// --- Search Test ---
async function testSearch() {
  const query = $("#testQuery").value.trim();
  if (!query) return;
  const data = await requestJson("/api/kb/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, limit: 4 })
  });
  $("#testResults").innerHTML = data.matches.map((match) => `
    <article class="result-card" style="border-left: 3px solid #10b981; cursor: default;">
      <strong style="font-size: 13px;">${escapeHtml(match.entry.title)} (得分: ${match.score})</strong>
      <p style="font-size: 12px; margin: 4px 0;">${escapeHtml(match.entry.content.slice(0, 80))}...</p>
    </article>
  `).join("") || '<div class="result-card"><p>未匹配到知识点</p></div>';
}

// --- Tools Logic ---
async function loadStatus() {
  const status = await requestJson("/api/kb/status");
  $("#kbStatus").textContent = `${status.entries} 条知识，${status.backups} 个备份。`;
  const github = await requestJson("/api/kb/github/status");
  $("#githubStatus").textContent = github.commit ? `GitHub 已同步: ${github.commit.slice(0,7)}` : "尚未同步到 GitHub";
}

async function loadInteractions() {
  const data = await requestJson("/api/interactions?limit=10");
  $("#interactionStatus").textContent = `共 ${data.total} 条采集记录`;
  $("#interactionList").innerHTML = data.records.map((r) => `
    <article>
        <strong>${escapeHtml(r.input_type)} @ ${new Date(r.created_at).toLocaleString()}</strong>
        <p>${escapeHtml((r.ocr_text || r.raw_text || "").slice(0, 50))}...</p>
    </article>
  `).join("");
}

// --- Initialization ---
function init() {
    initTabs();
    loadLearningQueue();

    $("#approveBtn").addEventListener('click', handleApprove);
    $("#rejectBtn").addEventListener('click', handleReject);
    $("#saveBtn").addEventListener('click', saveKBEntry);
    $("#newBtn").addEventListener('click', () => fillKBForm({id: `new-${Date.now()}`, title: "新知识点", tags: [], content: "", reply_templates: []}));
    $("#testBtn").addEventListener('click', testSearch);
    
    $("#backupBtn").addEventListener('click', () => requestJson("/api/kb/backup", {method: "POST"}).then(loadStatus));
    $("#githubBackupBtn").addEventListener('click', () => requestJson("/api/kb/github/export", {method: "POST"}).then(loadStatus));
    $("#importBtn").addEventListener('click', async () => {
        const raw = $("#importJson").value.trim();
        if (!raw) return;
        const entries = JSON.parse(raw).entries || JSON.parse(raw);
        await requestJson("/api/kb/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ entries }) });
        alert("导入成功");
    });
    $("#exportBtn").addEventListener('click', async () => {
        $("#importJson").value = JSON.stringify({ entries: state.entries }, null, 2);
    });
    $("#exportDistillBtn").addEventListener('click', () => requestJson("/api/interactions/export", {method: "POST"}).then(r => alert(`已导出到: ${r.output_path}`)));

    $("#harvestBtn").addEventListener('click', async () => {
        const url = $("#harvestUrl").value.trim();
        if (!url) return;
        const btn = $("#harvestBtn");
        const originalText = btn.innerText;
        btn.innerText = "正在自动化采集 (约30秒)...";
        btn.disabled = true;
        try {
            const result = await requestJson("/api/harvest-url", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url })
            });
            if (result.warnings && result.warnings.length) {
                alert(result.warnings[0]);
            } else {
                alert(`采集成功！已识别 ${result.messages.length} 条评论，已加入审核队列。`);
                $("#harvestUrl").value = "";
                // 切换到学习标签页查看结果
                document.querySelector('[data-tab="learning"]').click();
            }
        } catch (e) {
            alert("采集失败：" + e.message);
        } finally {
            btn.innerText = originalText;
            btn.disabled = false;
        }
    });
}

window.onload = init;
