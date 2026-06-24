const terminalElement = document.querySelector("#terminal");
const logsElement = document.querySelector("#logs");
const statusElement = document.querySelector("#status");
const sessionInput = document.querySelector("#session-id");
const sessionLabel = document.querySelector("#session-label");
const logsLink = document.querySelector("#logs-link");
const pinGate = document.querySelector("#pin-gate");
const pinForm = document.querySelector("#pin-form");
const pinInput = document.querySelector("#pin-input");
const pinError = document.querySelector("#pin-error");
const panelToggles = document.querySelectorAll(".panel-toggle");
const uploadProgress = document.querySelector("#upload-progress");
const uploadProgressText = document.querySelector("#upload-progress-text");
const uploadProgressBar = document.querySelector("#upload-progress-bar");
const cancelUploadButton = document.querySelector("#cancel-upload");
const languageToggle = document.querySelector("#language-toggle");
const algorithmGroupsElement = document.querySelector("#algorithm-groups");
const appTitleElement = document.querySelector("#app-title");
const appSubtitleElement = document.querySelector("#app-subtitle");
const appVersionElement = document.querySelector("#app-version");
const uploadProbeSizeInput = document.querySelector("#upload-probe-size");
const uploadProbeUnitSelect = document.querySelector("#upload-probe-unit");

const LANGUAGE_COOKIE = "py_web_ssh_lang";
const MIN_UPLOAD_PROBE_BYTES = 64;
const UPLOAD_PROBE_UNIT_BYTES = {
  mb: 1024 * 1024,
  kb: 1024,
  b: 1,
};
const translations = {
  en: {
    pinRequired: "PIN required",
    pin: "PIN",
    unlock: "Unlock",
    connect: "Connect",
    algorithms: "Algorithms",
    session: "Session",
    files: "Files",
    host: "Target host",
    port: "Port",
    username: "Username",
    password: "Password",
    passwordLocked: "Password is forced by the server.",
    privateKeyFile: "Private key file",
    privateKeyLocked: "Private key file is forced by the server.",
    privateKeyPassphrase: "Private key passphrase",
    algorithmHelp:
      "All Paramiko-supported algorithms are allowed by default. Uncheck algorithms to disable them for new SSH connections.",
    algorithmLoadFailed: "Could not load SSH algorithms.",
    algorithmGroup_kex: "Key exchange",
    algorithmGroup_ciphers: "Ciphers",
    algorithmGroup_digests: "MACs / digests",
    algorithmGroup_key_types: "Server host keys",
    algorithmGroup_pubkeys: "Public key signatures",
    serverKeys: "Server local keys",
    reconnect: "Reconnect",
    disconnect: "Disconnect SSH",
    openLogs: "Open full logs",
    uploadRemotePath: "Upload remote path",
    localFile: "Local file",
    uploadProbeSize: "Initial probe size",
    upload: "Upload",
    waitingUpload: "Waiting for upload",
    cancelUpload: "Cancel upload",
    downloadRemotePath: "Download remote path",
    download: "Download",
    terminal: "Terminal",
    logs: "Logs",
    notConnected: "Not connected",
    creatingSession: "Creating session...",
    createFailed: "Create failed",
    createSessionFailed: "Create session failed",
    ready: "Ready",
    invalidPin: "Invalid PIN.",
    uploadNeedsInputs: "Upload requires a session UUID, remote path, and local file.",
    preparingUpload: "Preparing upload...",
    uploading: "Uploading...",
    uploadComplete: "Upload complete",
    uploadFailed: "Upload failed",
    uploadCancelled: "Upload cancelled.",
    eta: "ETA",
    cancellingUpload: "Cancelling upload...",
    sendingToServer: "Sending to server...",
    networkUploadError: "Network error during upload.",
    uploadRequestAborted: "Upload request aborted.",
    downloadNeedsInputs: "Download requires a session UUID and remote path.",
    downloading: "Downloading...",
    downloadFailed: "Download failed",
    downloadComplete: "Download complete",
    connectingWebSocket: "WebSocket connecting...",
    webSocketConnected: "WebSocket connected",
    webSocketClosed: "WebSocket closed; reconnect is available",
    webSocketError: "WebSocket error",
    boundSession: "Bound session",
    sessionState: "Session state",
    lockedConfigFailed: "Could not load server configuration.",
    languageButton: "中文",
  },
  zh: {
    pinRequired: "需要 PIN",
    pin: "PIN",
    unlock: "解锁",
    connect: "连接",
    algorithms: "算法",
    session: "会话",
    files: "文件",
    host: "目标服务器",
    port: "端口",
    username: "用户名",
    password: "口令",
    passwordLocked: "口令已强制绑定",
    privateKeyFile: "私钥文件",
    privateKeyLocked: "私钥文件已强制绑定",
    privateKeyPassphrase: "私钥口令",
    algorithmHelp: "默认允许当前 Paramiko 支持的全部算法。取消勾选后，新 SSH 连接会禁用对应算法。",
    algorithmLoadFailed: "无法加载 SSH 算法列表。",
    algorithmGroup_kex: "密钥交换",
    algorithmGroup_ciphers: "加密算法",
    algorithmGroup_digests: "MAC / 摘要",
    algorithmGroup_key_types: "服务器主机密钥",
    algorithmGroup_pubkeys: "公钥签名",
    serverKeys: "服务端本机密钥",
    reconnect: "重连",
    disconnect: "断开 SSH",
    openLogs: "打开完整日志",
    uploadRemotePath: "上传到远端路径",
    localFile: "本地文件",
    uploadProbeSize: "初始试探大小",
    upload: "上传",
    waitingUpload: "等待上传",
    cancelUpload: "取消上传",
    downloadRemotePath: "下载远端路径",
    download: "下载",
    terminal: "终端",
    logs: "日志",
    notConnected: "未连接",
    creatingSession: "创建会话...",
    createFailed: "创建失败",
    createSessionFailed: "创建会话失败",
    ready: "就绪",
    invalidPin: "PIN 不正确。",
    uploadNeedsInputs: "上传需要会话 UUID、远端路径和本地文件。",
    preparingUpload: "准备上传...",
    uploading: "上传中...",
    uploadComplete: "上传完成",
    uploadFailed: "上传失败",
    uploadCancelled: "上传已取消。",
    eta: "预计",
    cancellingUpload: "正在取消上传...",
    sendingToServer: "正在发送到服务端...",
    networkUploadError: "上传过程发生网络错误。",
    uploadRequestAborted: "上传请求已中止。",
    downloadNeedsInputs: "下载需要会话 UUID 和远端路径。",
    downloading: "下载中...",
    downloadFailed: "下载失败",
    downloadComplete: "下载完成",
    connectingWebSocket: "WebSocket 连接中...",
    webSocketConnected: "WebSocket 已连接",
    webSocketClosed: "WebSocket 已关闭；可以重连",
    webSocketError: "WebSocket 错误",
    boundSession: "绑定会话",
    sessionState: "会话状态",
    lockedConfigFailed: "无法加载服务端配置。",
    languageButton: "English",
  },
};

let currentLanguage = readLanguageCookie();
let runtimeConfig = { locks: {} };
let algorithmCatalog = [];

const term = new Terminal({
  cursorBlink: true,
  convertEol: false,
  fontFamily: "Cascadia Mono, Consolas, Menlo, monospace",
  fontSize: 14,
  scrollback: 5000,
  theme: {
    background: "#0b0f14",
    foreground: "#dbe7f3",
    cursor: "#f8d66d",
    selectionBackground: "#315f8c",
    black: "#0b0f14",
    red: "#f26d6d",
    green: "#8fd694",
    yellow: "#f8d66d",
    blue: "#7db7ff",
    magenta: "#c792ea",
    cyan: "#82d7d1",
    white: "#dbe7f3",
    brightBlack: "#61707f",
    brightRed: "#ff8a8a",
    brightGreen: "#a6e3a1",
    brightYellow: "#ffe08a",
    brightBlue: "#9cc9ff",
    brightMagenta: "#d9a8ff",
    brightCyan: "#a5f3ed",
    brightWhite: "#ffffff",
  },
});
const fitAddon = new FitAddon.FitAddon();
const serializeAddon = new SerializeAddon.SerializeAddon();
term.loadAddon(fitAddon);
term.loadAddon(serializeAddon);
term.open(terminalElement);
fitAddon.fit();

let ws = null;
let activeSessionId = localStorage.getItem("py-web-ssh-session") || "";
let lastAppliedSeq = 0;
let snapshotTimer = null;
let activeUpload = null;

applyLanguage(currentLanguage);
initialize();
bindControlPanels();

if (activeSessionId) {
  sessionInput.value = activeSessionId;
  updateSessionUi(activeSessionId);
}

window.addEventListener("resize", () => {
  fitAddon.fit();
  sendResize();
});

languageToggle.addEventListener("click", () => {
  applyLanguage(currentLanguage === "en" ? "zh" : "en");
});
uploadProbeSizeInput.addEventListener("blur", normalizeUploadProbeSize);
uploadProbeUnitSelect.addEventListener("change", normalizeUploadProbeSize);

term.onData((data) => {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    return;
  }
  ws.send(JSON.stringify({ type: "input", data: stringToBase64(data) }));
});

document.querySelector("#connect-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus(t("creatingSession"));
  const privateKey = await readPrivateKey();
  const payload = {
    host: valueOf("#host"),
    port: Number(valueOf("#port") || 22),
    username: valueOf("#username"),
    password: valueOf("#password"),
    private_key: privateKey,
    private_key_passphrase: valueOf("#private-key-passphrase"),
    look_for_keys: checked("#look-for-keys"),
    disabled_algorithms: collectDisabledAlgorithms(),
    term: "xterm-256color",
    size: { cols: term.cols, rows: term.rows },
  };

  const response = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    appendLogLine(`${t("createSessionFailed")}: ${await response.text()}`);
    setStatus(t("createFailed"));
    return;
  }
  const result = await response.json();
  activeSessionId = result.session_id;
  localStorage.setItem("py-web-ssh-session", activeSessionId);
  sessionInput.value = activeSessionId;
  updateSessionUi(activeSessionId);
  connectWebSocket(activeSessionId);
});

pinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  pinError.textContent = "";
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin: pinInput.value }),
  });
  if (!response.ok) {
    pinError.textContent = t("invalidPin");
    pinInput.select();
    return;
  }
  pinInput.value = "";
  pinGate.classList.add("hidden");
  setStatus(t("ready"));
  await loadRuntimeConfig();
  await loadAlgorithms();
});

document.querySelector("#reconnect").addEventListener("click", () => {
  const id = sessionInput.value.trim();
  if (id) {
    activeSessionId = id;
    localStorage.setItem("py-web-ssh-session", id);
    updateSessionUi(id);
    connectWebSocket(id);
  }
});

document.querySelector("#disconnect").addEventListener("click", () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    sendSnapshot();
    ws.send(JSON.stringify({ type: "disconnect" }));
  }
});

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.querySelector("#upload-file").files[0];
  const remotePath = valueOf("#upload-path");
  if (!activeSessionId || !file || !remotePath) {
    appendLogLine(t("uploadNeedsInputs"));
    return;
  }
  const form = new FormData();
  form.append("remote_path", remotePath);
  form.append("total_bytes", String(file.size));
  form.append("upload_command_size_bytes", String(uploadProbeSizeBytes()));
  form.append("file", file);
  const uploadState = {
    xhr: null,
    transferId: null,
    pollTimer: null,
    cancelled: false,
    fileSize: file.size,
    startedAt: Date.now(),
  };
  activeUpload = uploadState;
  setUploadActionState("cancel");
  showUploadProgress(0, file.size, t("preparingUpload"), uploadState);
  setStatus(t("uploading"));
  try {
    const task = await createUploadTask(activeSessionId, remotePath, file.size);
    uploadState.transferId = task.transfer_id;
    form.append("transfer_id", uploadState.transferId);
    startUploadPolling(uploadState);
    const xhrUpload = uploadWithXhr(`/api/sessions/${activeSessionId}/files/upload`, form, uploadState);
    uploadState.xhr = xhrUpload.xhr;
    const result = await xhrUpload.promise;
    showUploadProgress(result.bytes_transferred, file.size, t("uploadComplete"), uploadState);
    setUploadActionState("complete");
    appendLogLine(`${t("uploadComplete")}: ${JSON.stringify(result)}`);
    setStatus(t("uploadComplete"));
  } catch (error) {
    appendLogLine(uploadState.cancelled ? t("uploadCancelled") : `${t("uploadFailed")}: ${error}`);
    setStatus(uploadState.cancelled ? t("uploadCancelled") : t("uploadFailed"));
  } finally {
    stopUploadPolling(uploadState);
    if (activeUpload === uploadState) activeUpload = null;
  }
});

async function createUploadTask(sessionId, remotePath, totalBytes) {
  const response = await fetch(`/api/sessions/${sessionId}/files/uploads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ remote_path: remotePath, total_bytes: totalBytes }),
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return await response.json();
}

function uploadWithXhr(url, form, uploadState) {
  const xhr = new XMLHttpRequest();
  const promise = new Promise((resolve, reject) => {
    xhr.open("POST", url);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        showUploadProgress(event.loaded, event.total, t("sendingToServer"), uploadState);
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(xhr.responseText || `HTTP ${xhr.status}`));
      }
    });
    xhr.addEventListener("error", () => reject(new Error(t("networkUploadError"))));
    xhr.addEventListener("abort", () => reject(new Error(t("uploadRequestAborted"))));
    xhr.send(form);
  });
  uploadState.xhr = xhr;
  return { xhr, promise };
}

cancelUploadButton.addEventListener("click", async () => {
  if (!activeUpload) return;
  activeUpload.cancelled = true;
  showUploadProgress(0, activeUpload.fileSize, t("cancellingUpload"), activeUpload);
  if (activeUpload.transferId) {
    await fetch(`/api/transfers/${activeUpload.transferId}`, { method: "DELETE" });
  }
  if (activeUpload.xhr) activeUpload.xhr.abort();
});

function setUploadActionState(state) {
  cancelUploadButton.dataset.uploadActionState = state;
  const completed = state === "complete";
  cancelUploadButton.disabled = completed;
  cancelUploadButton.textContent = completed ? t("uploadComplete") : t("cancelUpload");
}

document.querySelector("#download-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const remotePath = valueOf("#download-path");
  if (!activeSessionId || !remotePath) {
    appendLogLine(t("downloadNeedsInputs"));
    return;
  }
  setStatus(t("downloading"));
  const response = await fetch(
    `/api/sessions/${activeSessionId}/files/download?remote_path=${encodeURIComponent(remotePath)}`,
  );
  if (!response.ok) {
    appendLogLine(`${t("downloadFailed")}: ${await response.text()}`);
    setStatus(t("downloadFailed"));
    return;
  }
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filenameFromResponse(response, remotePath);
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
  setStatus(t("downloadComplete"));
});

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
    document.querySelectorAll(".pane").forEach((pane) => pane.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`#${button.dataset.tab}-pane`).classList.add("active");
    if (button.dataset.tab === "terminal") {
      fitAddon.fit();
    }
  });
});

function bindControlPanels() {
  panelToggles.forEach((button) => {
    button.addEventListener("click", () => {
      const panelId = button.getAttribute("aria-controls");
      const isOpen = button.getAttribute("aria-expanded") === "true";
      closeControlPanels();
      if (!isOpen) {
        openControlPanel(panelId);
      }
    });
  });

  document.querySelectorAll("[data-open-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      openControlPanel(button.dataset.openPanel);
    });
  });
}

function openControlPanel(panelId) {
  closeControlPanels();
  const panel = document.querySelector(`#${panelId}`);
  const toggle = document.querySelector(`[aria-controls="${panelId}"]`);
  if (!panel || !toggle) return;
  panel.hidden = false;
  toggle.setAttribute("aria-expanded", "true");
}

function closeControlPanels() {
  panelToggles.forEach((button) => {
    button.setAttribute("aria-expanded", "false");
    const panel = document.querySelector(`#${button.getAttribute("aria-controls")}`);
    if (panel) panel.hidden = true;
  });
}

function connectWebSocket(sessionId) {
  if (ws) {
    sendSnapshot();
    ws.close();
  }
  term.focus();
  setStatus(t("connectingWebSocket"));
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/sessions/${sessionId}`);
  ws = socket;
  socket.addEventListener("open", () => {
    if (ws !== socket) return;
    setStatus(t("webSocketConnected"));
    sendResize();
  });
  socket.addEventListener("message", async (event) => {
    if (ws !== socket) return;
    const message = JSON.parse(event.data);
    await handleMessage(message);
  });
  socket.addEventListener("close", () => {
    if (ws !== socket) return;
    setStatus(t("webSocketClosed"));
  });
  socket.addEventListener("error", () => {
    if (ws === socket) setStatus(t("webSocketError"));
  });
}

async function checkPinGate() {
  const response = await fetch("/api/auth/status");
  if (!response.ok) {
    pinGate.classList.remove("hidden");
    pinInput.focus();
    return false;
  }
  const status = await response.json();
  if (status.enabled && !status.authorized) {
    pinGate.classList.remove("hidden");
    pinInput.focus();
    return false;
  } else {
    pinGate.classList.add("hidden");
    return true;
  }
}

async function initialize() {
  if (await checkPinGate()) {
    await loadRuntimeConfig();
    await loadAlgorithms();
  }
}

async function loadRuntimeConfig() {
  const response = await fetch("/api/config");
  if (!response.ok) {
    appendLogLine(t("lockedConfigFailed"));
    return;
  }
  runtimeConfig = await response.json();
  applyBranding(runtimeConfig);
  applyRuntimeLocks(runtimeConfig);
}

function applyBranding(config) {
  const branding = config.branding || {};
  const title = branding.title || "py-web-ssh";
  const subtitle = branding.subtitle || "Web SSH Client";
  const version = branding.version || "0.0.0";
  document.title = title;
  appTitleElement.textContent = title;
  appSubtitleElement.textContent = subtitle;
  appVersionElement.textContent = `(py-web-ssh v${version})`;
}

function applyRuntimeLocks(config) {
  const locks = config.locks || {};
  lockTextInput("#host", locks.host);
  lockTextInput("#username", locks.username);

  const passwordLocked = Boolean(locks.password && locks.password.enabled);
  document.querySelector("#password-field").hidden = passwordLocked;
  document.querySelector("#password").disabled = passwordLocked;
  document.querySelector("#password").value = "";
  document.querySelector("#password-lock-note").hidden = !passwordLocked;

  const privateKeyLocked = Boolean(locks.private_key && locks.private_key.enabled);
  document.querySelector("#private-key-field").hidden = privateKeyLocked;
  document.querySelector("#private-key-file").disabled = privateKeyLocked;
  document.querySelector("#private-key-file").value = "";
  document.querySelector("#private-key-lock-note").hidden = !privateKeyLocked;
}

async function loadAlgorithms() {
  const response = await fetch("/api/algorithms");
  if (!response.ok) {
    appendLogLine(t("algorithmLoadFailed"));
    return;
  }
  const payload = await response.json();
  algorithmCatalog = Array.isArray(payload.groups) ? payload.groups : [];
  renderAlgorithmGroups();
}

function renderAlgorithmGroups() {
  const previous = collectAlgorithmChecks();
  algorithmGroupsElement.textContent = "";
  for (const group of algorithmCatalog) {
    const groupElement = document.createElement("section");
    groupElement.className = "algorithm-group";

    const heading = document.createElement("h3");
    heading.textContent = algorithmGroupLabel(group);
    groupElement.appendChild(heading);

    const options = document.createElement("div");
    options.className = "algorithm-options";
    for (const algorithm of group.algorithms || []) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = previous[group.id]?.[algorithm] ?? true;
      input.dataset.algorithmGroup = group.id;
      input.value = algorithm;

      const name = document.createElement("span");
      name.textContent = algorithm;
      label.append(input, name);
      options.appendChild(label);
    }
    groupElement.appendChild(options);
    algorithmGroupsElement.appendChild(groupElement);
  }
}

function algorithmGroupLabel(group) {
  const key = `algorithmGroup_${group.id}`;
  const translated = t(key);
  return translated === key ? group.label || group.id : translated;
}

function collectAlgorithmChecks() {
  const checks = {};
  algorithmGroupsElement.querySelectorAll("input[data-algorithm-group]").forEach((input) => {
    const group = input.dataset.algorithmGroup;
    if (!checks[group]) checks[group] = {};
    checks[group][input.value] = input.checked;
  });
  return checks;
}

function collectDisabledAlgorithms() {
  const disabled = {};
  algorithmGroupsElement.querySelectorAll("input[data-algorithm-group]").forEach((input) => {
    if (input.checked) return;
    const group = input.dataset.algorithmGroup;
    if (!disabled[group]) disabled[group] = [];
    disabled[group].push(input.value);
  });
  return disabled;
}

function lockTextInput(selector, lock) {
  const input = document.querySelector(selector);
  const locked = Boolean(lock && lock.enabled);
  input.readOnly = locked;
  input.classList.toggle("locked", locked);
  if (locked) {
    input.value = lock.value || "";
  }
}

async function handleMessage(message) {
  if (message.type === "session") {
    appendLogLine(`${t("boundSession")} ${message.session_id}`);
  } else if (message.type === "replay") {
    await replayTerminal(message);
    setStatus(`${t("sessionState")}: ${message.state}`);
    if (message.warning) appendLogLine(message.warning);
    for (const entry of message.logs || []) appendLogEntry(entry);
  } else if (message.type === "output") {
    await writeChunk(message);
  } else if (message.type === "status") {
    setStatus(`${t("sessionState")}: ${message.state}`);
  } else if (message.type === "log") {
    appendLogEntry(message.entry);
  } else if (message.type === "warning") {
    appendLogLine(message.message);
  }
}

async function replayTerminal(message) {
  term.reset();
  lastAppliedSeq = 0;
  if (message.snapshot) {
    await writeTerminal(base64ToString(message.snapshot));
    lastAppliedSeq = message.snapshot_seq || 0;
  }
  for (const chunk of message.chunks || []) {
    await writeChunk(chunk);
  }
  scheduleSnapshot();
}

async function writeChunk(chunk) {
  const bytes = base64ToBytes(chunk.data);
  await writeTerminal(bytes);
  lastAppliedSeq = chunk.seq + bytes.byteLength;
  scheduleSnapshot();
}

function writeTerminal(data) {
  return new Promise((resolve) => term.write(data, resolve));
}

function sendResize() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
  }
}

function scheduleSnapshot() {
  if (snapshotTimer) return;
  snapshotTimer = window.setTimeout(() => {
    snapshotTimer = null;
    sendSnapshot();
  }, 1500);
}

function sendSnapshot() {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    return;
  }
  const snapshot = serializeAddon.serialize();
  ws.send(JSON.stringify({ type: "snapshot", seq: lastAppliedSeq, data: stringToBase64(snapshot) }));
}

window.addEventListener("beforeunload", sendSnapshot);

async function readPrivateKey() {
  const lock = runtimeConfig.locks ? runtimeConfig.locks.private_key : null;
  if (lock && lock.enabled) {
    return "";
  }
  const file = document.querySelector("#private-key-file").files[0];
  return file ? await file.text() : "";
}

function updateSessionUi(sessionId) {
  sessionLabel.textContent = sessionId ? `UUID ${sessionId}` : "";
  logsLink.href = sessionId ? `/sessions/${sessionId}/logs` : "#";
}

function setStatus(text) {
  statusElement.textContent = text;
  statusElement.removeAttribute("data-i18n");
}

function appendLogEntry(entry) {
  const detail = entry.details ? `\n${entry.details}` : "";
  appendLogLine(`[${entry.timestamp}] ${entry.level.toUpperCase()} ${entry.message}${detail}`);
}

function appendLogLine(line) {
  logsElement.textContent += `${line}\n`;
  logsElement.scrollTop = logsElement.scrollHeight;
}

function valueOf(selector) {
  return document.querySelector(selector).value.trim();
}

function checked(selector) {
  return document.querySelector(selector).checked;
}

function uploadProbeSizeBytes() {
  normalizeUploadProbeSize();
  const value = Number.parseInt(valueOf("#upload-probe-size"), 10);
  const unit = document.querySelector("#upload-probe-unit").value;
  return value * (UPLOAD_PROBE_UNIT_BYTES[unit] || UPLOAD_PROBE_UNIT_BYTES.mb);
}

function normalizeUploadProbeSize() {
  const value = Number.parseInt(valueOf("#upload-probe-size"), 10);
  const unit = document.querySelector("#upload-probe-unit").value;
  const multiplier = UPLOAD_PROBE_UNIT_BYTES[unit] || UPLOAD_PROBE_UNIT_BYTES.mb;
  const bytes = Math.max(1, Number.isFinite(value) ? value : 1) * multiplier;
  if (bytes >= MIN_UPLOAD_PROBE_BYTES) {
    return;
  }
  uploadProbeSizeInput.value = String(MIN_UPLOAD_PROBE_BYTES);
  uploadProbeUnitSelect.value = "b";
}

function filenameFromResponse(response, fallbackPath) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  if (match) return match[1];
  return fallbackPath.split("/").filter(Boolean).pop() || "download.bin";
}

function showUploadProgress(done, total, message, uploadState = activeUpload) {
  uploadProgress.classList.remove("hidden");
  const percent = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  uploadProgressBar.value = percent;
  const eta = formatUploadEta(done, total, uploadState);
  uploadProgressText.textContent =
    `${message} ${formatBytes(done)}${total ? ` / ${formatBytes(total)}` : ""}${eta ? ` · ${t("eta")} ${eta}` : ""}`;
}

function startUploadPolling(uploadState) {
  stopUploadPolling(uploadState);
  uploadState.pollTimer = window.setInterval(async () => {
    if (!uploadState.transferId) return;
    try {
      const response = await fetch(`/api/transfers/${uploadState.transferId}`);
      if (!response.ok) return;
      const status = await response.json();
      showUploadProgress(
        status.bytes_transferred || 0,
        status.total_bytes || uploadState.fileSize,
        status.message || status.state,
        uploadState,
      );
      if (["completed", "cancelled", "failed"].includes(status.state)) {
        stopUploadPolling(uploadState);
      }
    } catch (_error) {
      return;
    }
  }, 500);
}

function stopUploadPolling(uploadState) {
  if (uploadState.pollTimer) {
    window.clearInterval(uploadState.pollTimer);
    uploadState.pollTimer = null;
  }
}

function formatBytes(value) {
  if (!Number.isFinite(value)) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 / 1024).toFixed(1)} MiB`;
}

function formatUploadEta(done, total, uploadState) {
  if (!uploadState || !uploadState.startedAt || !total || done <= 0 || done >= total) return "";
  const elapsedMs = Date.now() - uploadState.startedAt;
  if (elapsedMs <= 0) return "";
  const bytesPerSecond = done / (elapsedMs / 1000);
  if (!Number.isFinite(bytesPerSecond) || bytesPerSecond <= 0) return "";
  return formatDuration(Math.floor((total - done) / bytesPerSecond));
}

function formatDuration(seconds) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const secs = safeSeconds % 60;
  const parts = [];
  if (hours) parts.push(`${hours}h`);
  if (minutes) parts.push(`${minutes}m`);
  parts.push(`${secs}s`);
  return parts.join(" ");
}

function t(key) {
  return translations[currentLanguage][key] || translations.en[key] || key;
}

function applyLanguage(language) {
  currentLanguage = translations[language] ? language : "en";
  document.documentElement.lang = currentLanguage === "zh" ? "zh-CN" : "en";
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    const key = element.getAttribute("data-i18n");
    element.textContent = t(key);
  });
  languageToggle.textContent = t("languageButton");
  setLanguageCookie(currentLanguage);
  setUploadActionState(cancelUploadButton.dataset.uploadActionState || "cancel");
  if (statusElement.getAttribute("data-i18n") === "notConnected") {
    statusElement.textContent = t("notConnected");
  }
  if (algorithmCatalog.length) {
    renderAlgorithmGroups();
  }
}

function readLanguageCookie() {
  const match = document.cookie.match(new RegExp(`(?:^|; )${LANGUAGE_COOKIE}=([^;]+)`));
  const value = match ? decodeURIComponent(match[1]) : "en";
  return translations[value] ? value : "en";
}

function setLanguageCookie(language) {
  document.cookie = `${LANGUAGE_COOKIE}=${encodeURIComponent(language)}; Max-Age=31536000; Path=/; SameSite=Lax`;
}

function bytesToBase64(bytes) {
  let binary = "";
  const size = 0x8000;
  for (let i = 0; i < bytes.length; i += size) {
    binary += String.fromCharCode(...bytes.subarray(i, i + size));
  }
  return btoa(binary);
}

function base64ToBytes(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function stringToBase64(text) {
  return bytesToBase64(new TextEncoder().encode(text));
}

function base64ToString(text) {
  return new TextDecoder().decode(base64ToBytes(text));
}
