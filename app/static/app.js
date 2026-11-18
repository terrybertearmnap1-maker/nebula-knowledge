const els = {
  chat: document.getElementById("chat"),
  inner: document.getElementById("inner"),
  welcome: document.getElementById("welcome"),
  input: document.getElementById("input"),
  send: document.getElementById("send"),
  newChat: document.getElementById("newChat"),
  status: document.getElementById("status"),
  modelName: document.getElementById("modelName"),
  demoBanner: document.getElementById("demoBanner"),
  meta: document.getElementById("meta"),
  toast: document.getElementById("toast"),
  teamName: document.getElementById("teamName"),
  openTeam: document.getElementById("openTeam"),
  openKb: document.getElementById("openKb"),
  welcomeKb: document.getElementById("welcomeKb"),
  kbCount: document.getElementById("kbCount"),
  kbBackdrop: document.getElementById("kbBackdrop"),
  closeKb: document.getElementById("closeKb"),
  teamSelect: document.getElementById("teamSelect"),
  newTeamToggle: document.getElementById("newTeamToggle"),
  newTeamForm: document.getElementById("newTeamForm"),
  newTeamName: document.getElementById("newTeamName"),
  createTeam: document.getElementById("createTeam"),
  dropzone: document.getElementById("dropzone"),
  fileInput: document.getElementById("fileInput"),
  uploadStatus: document.getElementById("uploadStatus"),
  docCount: document.getElementById("docCount"),
  docList: document.getElementById("docList"),
};

const state = {
  teamId: localStorage.getItem("nebula_team") || "default",
  teams: [],
  sessionId: null,
  docs: [],
  busy: false,
  uploadBusy: false,
  demo: false,
  toastTimer: null,
};

function sessionKey(teamId = state.teamId) {
  return `nebula_session:${teamId}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatText(value) {
  return escapeHtml(value)
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replaceAll("\n", "<br>");
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    els.chat.scrollTop = els.chat.scrollHeight;
  });
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("show");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => els.toast.classList.remove("show"), 4200);
}

function setUploadStatus(message, type = "") {
  els.uploadStatus.textContent = message;
  els.uploadStatus.className = `upload-status ${type}`.trim();
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") detail = payload.detail;
      else if (Array.isArray(payload.detail)) {
        detail = payload.detail.map((item) => item.msg || "参数错误").join("；");
      }
    } catch (_) {
      /* keep generic message */
    }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function hideWelcome() {
  if (els.welcome) els.welcome.style.display = "none";
}

function clearChat() {
  els.inner.replaceChildren(els.welcome);
  els.welcome.style.display = "";
}

function setBusy(busy) {
  state.busy = busy;
  els.send.disabled = busy;
  els.input.disabled = busy;
  els.teamSelect.disabled = busy || state.uploadBusy;
  els.newTeamToggle.disabled = busy || state.uploadBusy;
  if (!busy) els.input.focus();
}

function renderCitations(citations) {
  const box = document.createElement("div");
  box.className = "citations";
  const seen = new Set();
  for (const citation of citations) {
    const isWeather = citation.source_type === "weather";
    const isWeb = citation.source_type === "web" || isWeather;
    const key = isWeb
      ? `${citation.source_type}:${citation.url}`
      : `document:${citation.document_id}:${citation.page ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);

    const link = document.createElement("a");
    link.className = `citation${isWeb ? " citation-web" : ""}`;
    if (isWeb && citation.url) {
      link.href = citation.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.title = `${citation.snippet || ""}\n${citation.url}`.trim();
      link.textContent = `${isWeather ? "☀" : "🌐"} ${citation.document || citation.title || "网页"}`;
    } else {
      link.href = `/api/teams/${encodeURIComponent(state.teamId)}/documents/${encodeURIComponent(citation.document_id)}/download`;
      link.target = "_blank";
      link.rel = "noopener";
      link.title = citation.snippet || citation.document;
      link.textContent = `▤ ${citation.document}${citation.page ? ` · 第 ${citation.page} 页` : ""}`;
    }
    box.appendChild(link);
  }
  return box;
}

function buildToolCard(call) {
  const details = document.createElement("details");
  details.className = "tool-card";

  const summary = document.createElement("summary");
  const gear = document.createElement("span");
  gear.className = "gear";
  gear.textContent = "⚙";
  const label = document.createElement("span");
  label.textContent = `调用工具 · ${call.name || "unknown"}`;
  const ok = document.createElement("span");
  ok.className = "ok";
  ok.textContent = "已完成";
  summary.append(gear, label, ok);

  const body = document.createElement("div");
  body.className = "tool-body";

  const argsLabel = document.createElement("label");
  argsLabel.textContent = "arguments";
  const argsPre = document.createElement("pre");
  argsPre.textContent = JSON.stringify(call.args || {}, null, 2);

  const resultLabel = document.createElement("label");
  resultLabel.textContent = "result";
  const resultPre = document.createElement("pre");
  resultPre.textContent = call.result || "(empty)";

  body.append(argsLabel, argsPre, resultLabel, resultPre);
  details.append(summary, body);
  return details;
}

function addMessage(role, text, toolCalls = [], citations = []) {
  hideWelcome();
  const row = document.createElement("div");
  row.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "你" : "N";
  avatar.setAttribute("aria-hidden", "true");

  const wrap = document.createElement("div");
  wrap.className = "bubble-wrap";

  const name = document.createElement("div");
  name.className = "name";
  name.textContent = role === "user" ? "YOU" : "NEBULA";
  wrap.appendChild(name);

  if (toolCalls.length) {
    const tools = document.createElement("div");
    tools.className = "tools";
    for (const call of toolCalls) {
      tools.appendChild(buildToolCard(call));
    }
    wrap.appendChild(tools);
  }

  if (text) {
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = formatText(text);
    wrap.appendChild(bubble);
  }

  if (citations.length) {
    wrap.appendChild(renderCitations(citations));
  }

  row.append(avatar, wrap);
  els.inner.appendChild(row);
  scrollToBottom();
}

function addTyping() {
  hideWelcome();
  const row = document.createElement("div");
  row.className = "message assistant";
  row.id = "typingRow";

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = "N";
  avatar.setAttribute("aria-hidden", "true");

  const bubble = document.createElement("div");
  bubble.className = "bubble typing";
  bubble.setAttribute("aria-label", "Agent 正在检索");
  bubble.innerHTML = "<i></i><i></i><i></i>";

  row.append(avatar, bubble);
  els.inner.appendChild(row);
  scrollToBottom();
}

function removeTyping() {
  document.getElementById("typingRow")?.remove();
}

async function loadHealth() {
  try {
    const health = await api("/healthz");
    state.demo = health.demo_mode;
    els.status.classList.add("online");
    els.modelName.textContent = health.model;
    els.meta.textContent = `LangChain · ${health.model}${health.web_search ? " · 联网" : ""}`;
    els.demoBanner.classList.toggle("show", Boolean(health.demo_mode));
  } catch (_) {
    els.status.classList.add("offline");
    els.modelName.textContent = "后端离线";
    showToast("无法连接后端，请检查服务是否已启动。");
  }
}

function renderTeamOptions() {
  els.teamSelect.replaceChildren();
  for (const team of state.teams) {
    const option = document.createElement("option");
    option.value = team.id;
    option.textContent = team.name;
    els.teamSelect.appendChild(option);
  }
  els.teamSelect.value = state.teamId;
}

function updateTeamLabel() {
  const team = state.teams.find((item) => item.id === state.teamId);
  els.teamName.textContent = team ? team.name : "默认团队";
}

async function loadTeams() {
  state.teams = await api("/api/teams");
  if (!Array.isArray(state.teams) || state.teams.length === 0) {
    state.teams = [{ id: "default", name: "默认团队", document_count: 0 }];
  }
  if (!state.teams.some((team) => team.id === state.teamId)) {
    state.teamId = state.teams[0].id;
  }
  localStorage.setItem("nebula_team", state.teamId);
  state.sessionId = localStorage.getItem(sessionKey());
  renderTeamOptions();
  updateTeamLabel();
}

function renderDocuments() {
  els.docList.replaceChildren();
  els.docCount.textContent = `${state.docs.length} 份`;
  els.kbCount.textContent = String(state.docs.length);

  if (state.docs.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-docs";
    empty.textContent = "还没有文档。上传一份制度、手册或会议纪要，然后开始提问。";
    els.docList.appendChild(empty);
    return;
  }

  for (const doc of state.docs) {
    const item = document.createElement("div");
    item.className = "doc-item";

    const icon = document.createElement("div");
    icon.className = "doc-icon";
    icon.textContent = (doc.filename.split(".").pop() || "DOC").slice(0, 4).toUpperCase();

    const meta = document.createElement("div");
    meta.className = "doc-meta";
    const title = document.createElement("strong");
    title.textContent = doc.filename;
    title.title = doc.filename;
    const details = document.createElement("span");
    const pages = doc.page_count ? `${doc.page_count} 页 · ` : "";
    details.textContent = `${pages}${doc.chunk_count} 个片段 · ${formatBytes(doc.size_bytes)}`;
    meta.append(title, details);

    const actions = document.createElement("div");
    actions.className = "doc-actions";
    const download = document.createElement("a");
    download.href = doc.download_url;
    download.download = doc.filename;
    download.title = "下载原文件";
    download.textContent = "↓";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.title = "删除文档";
    remove.textContent = "×";
    remove.addEventListener("click", () => deleteDocument(doc.id, doc.filename));
    actions.append(download, remove);

    item.append(icon, meta, actions);
    els.docList.appendChild(item);
  }
}

async function loadDocuments() {
  const requestedTeam = state.teamId;
  try {
    const payload = await api(`/api/teams/${encodeURIComponent(requestedTeam)}/documents`);
    if (requestedTeam !== state.teamId) return;
    state.docs = payload.documents || [];
    renderDocuments();
    const team = state.teams.find((item) => item.id === requestedTeam);
    if (team) team.document_count = state.docs.length;
  } catch (error) {
    if (requestedTeam !== state.teamId) return;
    state.docs = [];
    renderDocuments();
    setUploadStatus(error.message, "error");
  }
}

async function loadHistory() {
  if (!state.sessionId) {
    clearChat();
    return;
  }
  const requestedTeam = state.teamId;
  const requestedSession = state.sessionId;
  try {
    const params = new URLSearchParams({ team_id: requestedTeam });
    const payload = await api(`/api/sessions/${encodeURIComponent(requestedSession)}/history?${params}`);
    if (requestedTeam !== state.teamId || requestedSession !== state.sessionId) return;
    clearChat();
    let rendered = 0;
    for (const message of payload.messages) {
      if (message.role === "user") {
        addMessage("user", message.content);
        rendered += 1;
      } else if (message.role === "assistant" && message.content.trim()) {
        addMessage("assistant", message.content, [], message.citations || []);
        rendered += 1;
      }
    }
    if (rendered === 0) clearChat();
  } catch (_) {
    state.sessionId = null;
    localStorage.removeItem(sessionKey(requestedTeam));
    clearChat();
  }
}

async function switchTeam(teamId) {
  if (teamId === state.teamId) return;
  if (state.busy || state.uploadBusy) {
    showToast("请等待当前操作完成后再切换团队。");
    els.teamSelect.value = state.teamId;
    return;
  }
  state.teamId = teamId;
  localStorage.setItem("nebula_team", teamId);
  state.sessionId = localStorage.getItem(sessionKey(teamId));
  updateTeamLabel();
  els.teamSelect.value = teamId;
  clearChat();
  await Promise.all([loadDocuments(), loadHistory()]);
}

async function deleteDocument(documentId, filename) {
  if (!window.confirm(`确定删除「${filename}」？删除后它的检索结果也会消失。`)) return;
  const teamId = state.teamId;
  try {
    await api(`/api/teams/${encodeURIComponent(teamId)}/documents/${encodeURIComponent(documentId)}`, {
      method: "DELETE",
    });
    showToast(`已删除 ${filename}`);
    if (teamId === state.teamId) await loadDocuments();
  } catch (error) {
    showToast(error.message);
  }
}

async function uploadFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length || state.uploadBusy) return;
  state.uploadBusy = true;
  els.teamSelect.disabled = true;
  els.newTeamToggle.disabled = true;
  setUploadStatus("正在上传并解析文档…");

  const teamId = state.teamId;
  let uploaded = 0;
  const errors = [];
  for (const file of files) {
    if (file.size > 10 * 1024 * 1024) {
      errors.push(`${file.name} 超过 10MB`);
      continue;
    }
    setUploadStatus(`正在解析 ${file.name}…`);
    const form = new FormData();
    form.append("file", file, file.name);
    try {
      await api(`/api/teams/${encodeURIComponent(teamId)}/documents`, {
        method: "POST",
        body: form,
      });
      uploaded += 1;
    } catch (error) {
      errors.push(`${file.name}：${error.message}`);
    }
  }

  state.uploadBusy = false;
  els.teamSelect.disabled = false;
  els.newTeamToggle.disabled = false;
  els.fileInput.value = "";
  if (teamId === state.teamId) await loadDocuments();

  if (errors.length) {
    setUploadStatus(`${uploaded} 个成功；${errors.join("；")}`, "error");
  } else {
    setUploadStatus(`${uploaded} 个文件已加入知识库`, "success");
  }
}

async function sendMessage(text) {
  const message = text.trim();
  if (!message || state.busy) return;

  const teamId = state.teamId;
  setBusy(true);
  els.input.value = "";
  resizeInput();
  addMessage("user", message);
  addTyping();

  try {
    const payload = {
      message,
      team_id: teamId,
      ...(state.sessionId ? { session_id: state.sessionId } : {}),
    };
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    removeTyping();
    if (teamId !== state.teamId) return;
    state.sessionId = result.session_id;
    localStorage.setItem(sessionKey(teamId), state.sessionId);
    addMessage("assistant", result.answer, result.tool_calls || [], result.citations || []);
    if (result.demo_mode) els.demoBanner.classList.add("show");
  } catch (error) {
    removeTyping();
    if (teamId === state.teamId) {
      addMessage("assistant", `请求失败：${error.message}`);
      showToast("Agent 请求失败，请查看后端日志。");
    }
  } finally {
    setBusy(false);
  }
}

function resizeInput() {
  els.input.style.height = "auto";
  els.input.style.height = `${Math.min(els.input.scrollHeight, 150)}px`;
}

async function newChat() {
  if (state.busy) return;
  const oldTeam = state.teamId;
  const oldSession = state.sessionId;
  state.sessionId = null;
  localStorage.removeItem(sessionKey(oldTeam));
  clearChat();
  els.input.value = "";
  resizeInput();
  els.input.focus();
  if (oldSession) {
    const params = new URLSearchParams({ team_id: oldTeam });
    api(`/api/sessions/${encodeURIComponent(oldSession)}?${params}`, { method: "DELETE" }).catch(() => {});
  }
}

function openKnowledgeBase() {
  els.kbBackdrop.hidden = false;
  loadDocuments();
  requestAnimationFrame(() => els.closeKb.focus());
}

function closeKnowledgeBase() {
  els.kbBackdrop.hidden = true;
  els.openKb.focus();
}

async function createTeam() {
  const name = els.newTeamName.value.trim();
  if (!name) {
    showToast("请输入团队名称。");
    return;
  }
  els.createTeam.disabled = true;
  try {
    const team = await api("/api/teams", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    state.teams.push({ ...team, document_count: 0 });
    els.newTeamName.value = "";
    els.newTeamForm.hidden = true;
    renderTeamOptions();
    await switchTeam(team.id);
    showToast(`已创建团队「${team.name}」`);
  } catch (error) {
    showToast(error.message);
  } finally {
    els.createTeam.disabled = false;
  }
}

els.send.addEventListener("click", () => sendMessage(els.input.value));

els.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendMessage(els.input.value);
  }
});

els.input.addEventListener("input", resizeInput);
els.newChat.addEventListener("click", newChat);
els.openKb.addEventListener("click", openKnowledgeBase);
els.openTeam.addEventListener("click", openKnowledgeBase);
els.welcomeKb.addEventListener("click", openKnowledgeBase);
els.closeKb.addEventListener("click", closeKnowledgeBase);
els.kbBackdrop.addEventListener("click", (event) => {
  if (event.target === els.kbBackdrop) closeKnowledgeBase();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !els.kbBackdrop.hidden) closeKnowledgeBase();
});

els.teamSelect.addEventListener("change", () => switchTeam(els.teamSelect.value));
els.newTeamToggle.addEventListener("click", () => {
  els.newTeamForm.hidden = !els.newTeamForm.hidden;
  if (!els.newTeamForm.hidden) els.newTeamName.focus();
});
els.createTeam.addEventListener("click", createTeam);
els.newTeamName.addEventListener("keydown", (event) => {
  if (event.key === "Enter") createTeam();
});

els.fileInput.addEventListener("change", () => uploadFiles(els.fileInput.files));
["dragenter", "dragover"].forEach((type) => {
  els.dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    els.dropzone.classList.add("dragover");
  });
});
["dragleave", "drop"].forEach((type) => {
  els.dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    els.dropzone.classList.remove("dragover");
  });
});
els.dropzone.addEventListener("drop", (event) => uploadFiles(event.dataTransfer.files));

document.querySelectorAll(".suggestion[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    els.input.value = button.dataset.prompt || "";
    resizeInput();
    sendMessage(els.input.value);
  });
});

(async function init() {
  await loadHealth();
  try {
    await loadTeams();
  } catch (error) {
    showToast(error.message);
  }
  await Promise.all([loadDocuments(), loadHistory()]);
  els.input.focus();
  scrollToBottom();
})();
