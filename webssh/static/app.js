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

if (activeSessionId) {
  sessionInput.value = activeSessionId;
  updateSessionUi(activeSessionId);
}

checkPinGate();
bindControlPanels();

window.addEventListener("resize", () => {
  fitAddon.fit();
  sendResize();
});

term.onData((data) => {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    return;
  }
  ws.send(JSON.stringify({ type: "input", data: stringToBase64(data) }));
});

document.querySelector("#connect-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("创建会话...");
  const privateKey = await readPrivateKey();
  const payload = {
    host: valueOf("#host"),
    port: Number(valueOf("#port") || 22),
    username: valueOf("#username"),
    password: valueOf("#password"),
    private_key: privateKey,
    private_key_passphrase: valueOf("#private-key-passphrase"),
    allow_agent: checked("#allow-agent"),
    look_for_keys: checked("#look-for-keys"),
    legacy_algorithms: checked("#legacy-algorithms"),
    strict_host_key: checked("#strict-host-key"),
    term: "xterm-256color",
    size: { cols: term.cols, rows: term.rows },
  };

  const response = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    appendLogLine(`创建会话失败: ${await response.text()}`);
    setStatus("创建失败");
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
    pinError.textContent = "Invalid PIN.";
    pinInput.select();
    return;
  }
  pinInput.value = "";
  pinGate.classList.add("hidden");
  setStatus("Ready");
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
    appendLogLine("上传需要会话 UUID、远端路径和本地文件。");
    return;
  }
  const form = new FormData();
  form.append("remote_path", remotePath);
  form.append("total_bytes", String(file.size));
  form.append("file", file);
  let xhr = null;
  const uploadState = {
    xhr: null,
    transferId: null,
    pollTimer: null,
    cancelled: false,
    fileSize: file.size,
  };
  activeUpload = uploadState;
  showUploadProgress(0, file.size, "准备上传...");
  setStatus("上传中...");
  try {
    const task = await createUploadTask(activeSessionId, remotePath, file.size);
    uploadState.transferId = task.transfer_id;
    form.append("transfer_id", uploadState.transferId);
    startUploadPolling(uploadState);
    xhr = uploadWithXhr(`/api/sessions/${activeSessionId}/files/upload`, form, uploadState);
    uploadState.xhr = xhr;
    const result = await xhr;
    showUploadProgress(result.bytes_transferred, file.size, "上传完成");
    appendLogLine(`上传完成: ${JSON.stringify(result)}`);
    setStatus("上传完成");
  } catch (error) {
    appendLogLine(uploadState.cancelled ? "上传已取消。" : `上传失败: ${error}`);
    setStatus(uploadState.cancelled ? "上传已取消" : "上传失败");
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
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        showUploadProgress(event.loaded, event.total, "正在发送到服务端...");
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(xhr.responseText || `HTTP ${xhr.status}`));
      }
    });
    xhr.addEventListener("error", () => reject(new Error("Network error during upload.")));
    xhr.addEventListener("abort", () => reject(new Error("Upload request aborted.")));
    xhr.send(form);
  });
}

cancelUploadButton.addEventListener("click", async () => {
  if (!activeUpload) return;
  activeUpload.cancelled = true;
  showUploadProgress(0, activeUpload.fileSize, "正在取消上传...");
  if (activeUpload.transferId) {
    await fetch(`/api/transfers/${activeUpload.transferId}`, { method: "DELETE" });
  }
  if (activeUpload.xhr) activeUpload.xhr.abort();
});

document.querySelector("#download-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const remotePath = valueOf("#download-path");
  if (!activeSessionId || !remotePath) {
    appendLogLine("下载需要会话 UUID 和远端路径。");
    return;
  }
  setStatus("下载中...");
  const response = await fetch(
    `/api/sessions/${activeSessionId}/files/download?remote_path=${encodeURIComponent(remotePath)}`,
  );
  if (!response.ok) {
    appendLogLine(`下载失败: ${await response.text()}`);
    setStatus("下载失败");
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
  setStatus("下载完成");
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
  setStatus("WebSocket 连接中...");
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/sessions/${sessionId}`);
  ws = socket;
  socket.addEventListener("open", () => {
    if (ws !== socket) return;
    setStatus("WebSocket 已连接");
    sendResize();
  });
  socket.addEventListener("message", async (event) => {
    if (ws !== socket) return;
    const message = JSON.parse(event.data);
    await handleMessage(message);
  });
  socket.addEventListener("close", () => {
    if (ws !== socket) return;
    setStatus("WebSocket closed; reconnect is available");
  });
  socket.addEventListener("error", () => {
    if (ws === socket) setStatus("WebSocket 错误");
  });
}

async function checkPinGate() {
  const response = await fetch("/api/auth/status");
  if (!response.ok) {
    pinGate.classList.remove("hidden");
    pinInput.focus();
    return;
  }
  const status = await response.json();
  if (status.enabled) {
    pinGate.classList.remove("hidden");
    pinInput.focus();
  } else {
    pinGate.classList.add("hidden");
  }
}

async function handleMessage(message) {
  if (message.type === "session") {
    appendLogLine(`绑定会话 ${message.session_id}`);
  } else if (message.type === "replay") {
    await replayTerminal(message);
    setStatus(`会话状态: ${message.state}`);
    if (message.warning) appendLogLine(message.warning);
    for (const entry of message.logs || []) appendLogEntry(entry);
  } else if (message.type === "output") {
    await writeChunk(message);
  } else if (message.type === "status") {
    setStatus(`会话状态: ${message.state}`);
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
  const file = document.querySelector("#private-key-file").files[0];
  return file ? await file.text() : "";
}

function updateSessionUi(sessionId) {
  sessionLabel.textContent = sessionId ? `UUID ${sessionId}` : "";
  logsLink.href = sessionId ? `/sessions/${sessionId}/logs` : "#";
}

function setStatus(text) {
  statusElement.textContent = text;
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

function filenameFromResponse(response, fallbackPath) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  if (match) return match[1];
  return fallbackPath.split("/").filter(Boolean).pop() || "download.bin";
}

function showUploadProgress(done, total, message) {
  uploadProgress.classList.remove("hidden");
  const percent = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  uploadProgressBar.value = percent;
  uploadProgressText.textContent = `${message} ${formatBytes(done)}${total ? ` / ${formatBytes(total)}` : ""}`;
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
