# py-web-ssh

Languages: [English](#english) | [中文](#中文)

## English

A Web SSH client built with Python, FastAPI, and Paramiko. The frontend uses xterm.js to render real terminal control sequences, while the backend forwards interactive SSH data over WebSocket. Each web client receives a random UUID and can reconnect to the same UUID, restore terminal snapshots, view logs, and upload or download files.

### Features

- Interactive SSH terminal: Paramiko backend with `invoke_shell`, xterm.js frontend with real-time interaction.
- Login methods: password, browser-uploaded private key, private-key passphrase, server-local default `~/.ssh` keys, and passwordless/none auth.
- Host key confirmation: `known_hosts` verification is not used. Every interactive SSH connection displays the server host key fingerprint in the xterm.js terminal and requires the user to enter `Y` or `N` before authentication continues.
- Algorithm controls: the frontend "Algorithms" panel lists all KEX/Cipher/MAC/HostKey/Pubkey algorithms supported by the current server-side Paramiko runtime. Everything is selected by default; unchecked algorithms are disabled in later SSH connections, and the logs show the algorithms that were enabled or disabled.
- UUID sessions: creating a session returns a UUID. After a WebSocket disconnect, the same UUID can be used to reconnect.
- Session cleanup: if every browser connection for the same UUID disconnects and nobody reconnects within 5 minutes, the server actively disconnects SSH and clears in-memory caches.
- Terminal recovery: the server stores the SSH output stream, and the browser periodically sends back xterm serialize snapshots. On reconnect, the snapshot is restored first, then output after the snapshot is replayed.
- Logs page: `/sessions/{uuid}/logs` shows complete connection, authentication, error, and file-transfer logs.
- File transfer: inspired by `simple-ssh-copy`, without SFTP/SCP. Each transfer creates an independent SSH connection from the same connection configuration, appends base64 chunks through short remote shell commands, decodes them into a temporary data file on the remote side, and then runs `mv` to the final path. Progress, ETA, and cancellation are supported. Before upload, the target path is probed: if the target is a remote directory, the browser-uploaded file's original name is placed inside it; if the target does not exist or is a regular file, the specified path is overwritten. Uploads probe the remote maximum command length starting at 1 MiB per command by default, and the user can change that initial probe size with MB, KB, or B units. The probe binary-searches downward on failures such as argument-too-long or closed connections, stops at a minimum of 64 B, and writes the final command length to the logs. File-transfer connections verify that the server host key exactly matches the host key confirmed by the user in the interactive terminal.
- Optional PIN gate: when the server starts with `--pin`, the web page requires the correct PIN first. After successful verification, the browser stores a salted hash cookie, and the backend protects HTTP APIs, the logs page, file endpoints, and WebSocket.
- Custom branding: the default page title is `py-web-ssh`, and the default subtitle is `Web SSH Client`. They can be configured with `--title` and `--subtitle` at startup. The subtitle always shows the current package version on the right as `(py-web-ssh vx.y.z)`, and the title/subtitle do not change when the UI language changes.
- Startup lock policy: supports `--lock-host`, `--lock-username`, `--lock-pwd`, and `--lock-private-key` to enforce the target host, username, password, and server-side private-key file from the server. The frontend locks or hides the matching controls, while the backend still validates and overrides sensitive fields. If no password, custom private key, or server-local key lookup is used, SSH connections try none authentication first, matching the empty-credential path used by `simple-ssh-copy`.
- English/Chinese UI: English is the default language. The web page and logs page support switching between English and Chinese, and the language choice is persisted in the `py_web_ssh_lang` cookie.
- Browser client session: on first visit, the server assigns an independent browser session UUID and writes it to an HttpOnly cookie. It is separate from the SSH session UUID.
- Left control panel: the Connection, Algorithms, Session, and Files sections are mutually exclusive collapsible panels. At most one section is expanded at a time, and all sections can also be collapsed.

### Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

### Start

```bash
py-web-ssh
```

Or:

```bash
uvicorn webssh.app:app --host 0.0.0.0 --port 8022
```

Open <http://127.0.0.1:8022>.

Enable PIN:

```bash
py-web-ssh --pin 123456
```

Set the page title and subtitle:

```bash
py-web-ssh --title "Ops SSH" --subtitle "Production Access"
```

Lock the connection target or credentials:

```bash
py-web-ssh --lock-host server.example.com --lock-username deploy
py-web-ssh --lock-pwd 'ssh-password'
py-web-ssh --lock-private-key C:\secrets\id_ed25519
```

The values of `--lock-pwd` and `--lock-private-key` are used only on the server and are not sent to the browser through the config API. `--lock-private-key` points to a server-local file path, not a browser-uploaded file.

The frontend loads xterm.js, the fit addon, and the serialize addon from jsDelivr by default. For offline intranet deployment, vendor these static assets into `webssh/static/` and replace the CDN URLs in `index.html`.

### API Overview

- `GET /api/config` returns non-sensitive public server configuration and lock status.
- `GET /api/algorithms` returns the SSH algorithm list supported by the current server-side Paramiko runtime.
- `POST /api/sessions` creates an SSH session.
- `GET /api/sessions/{uuid}` returns session status.
- `GET /api/sessions/{uuid}/logs` returns complete logs as JSON.
- `DELETE /api/sessions/{uuid}` actively disconnects SSH.
- `WS /ws/sessions/{uuid}` handles terminal input, output, resize, snapshots, and disconnect control.
- `POST /api/sessions/{uuid}/files/upload` uploads a file with multipart fields: `remote_path`, `file`.
- `GET /api/sessions/{uuid}/files/download?remote_path=/path/file` downloads a remote file.

### Security Notes

This project is designed by default for trusted intranet or local use. Private keys and passphrases are kept only in process memory and are not written to logs. SSH agent is disabled, `known_hosts` verification has been removed, and users must confirm the server host key fingerprint in the xterm.js terminal before authentication continues. If you expose it to the public internet, add HTTPS, login authentication, CSRF/origin restrictions, auditing, and session cleanup policies.

## 中文

一个基于 Python/FastAPI/Paramiko 的 Web SSH 客户端。前端使用 xterm.js 渲染真实终端控制序列，后端通过 WebSocket 转发 SSH 交互数据，并为每个网页客户端分配随机 UUID，支持同 UUID 断线重连、终端快照恢复、日志查看和文件上传下载。

### 功能

- SSH 交互终端：Paramiko 后端 `invoke_shell`，xterm.js 前端实时交互。
- 登录方式：密码、浏览器上传私钥、私钥口令、服务端本机默认 `~/.ssh` 密钥、免口令/none auth。
- Host key 确认：不使用 `known_hosts` 校验；每次交互 SSH 连接都会在 xterm.js 终端里显示服务器 host key 指纹，并要求用户输入 `Y` 或 `N` 后才继续认证。
- 算法控制：前端“算法”面板会列出当前服务端 Paramiko 运行时支持的全部 KEX/Cipher/MAC/HostKey/Pubkey 算法；默认全选，取消勾选后后端会在后续 SSH 连接中禁用对应算法，并在日志中列出实际启用和禁用的算法。
- UUID 会话：创建会话后返回 UUID，WebSocket 断开后可用同 UUID 重连。
- 会话回收：同一个 UUID 如果所有浏览器连接都断开并且 5 分钟内无人重连，服务端会主动断开 SSH 并清理内存缓存。
- 终端恢复：服务端保存 SSH 输出流，浏览器定期回传 xterm serialize 快照；重连时先恢复快照，再补放快照之后的输出。
- 日志页面：`/sessions/{uuid}/logs` 展示完整连接、认证、错误和文件传输日志。
- 文件传输：参考 `simple-ssh-copy` 思路，不使用 SFTP/SCP；每次传输都按连接配置新建独立 SSH 连接，通过短小的远端 shell 命令分块追加 base64 临时文件，再在远端解码到临时数据文件并 `mv` 到最终路径，支持进度显示、ETA 和取消。上传会先探测目标路径：如果目标是远端目录，则使用浏览器上传文件的原始文件名放入该目录；如果目标不存在或是普通文件，则按指定路径覆盖。上传前默认会从 1 MiB 单次命令开始探测远端可承载的最大命令长度，用户也可以用 MB、KB、B 单位自行调整初始试探大小；遇到参数过长或连接关闭等失败时二分下降，最低探测到 64 B，并把最终命令长度写入日志。文件传输连接会校验服务器 host key 必须等于用户在交互终端里确认过的 host key。
- 可选 PIN 门禁：服务端传入 `--pin` 后，网页启动时必须先输入正确 PIN；验证成功后浏览器会保存加盐哈希 cookie，后端会保护 HTTP API、日志页面、文件接口和 WebSocket。
- 可定制品牌：默认网页标题为 `py-web-ssh`，副标题为 `Web SSH Client`；启动时可用 `--title` 和 `--subtitle` 设置。副标题右侧始终显示当前包版本 `(py-web-ssh vx.y.z)`，且标题和副标题不会跟随语言切换。
- 启动锁定策略：支持 `--lock-host`、`--lock-username`、`--lock-pwd`、`--lock-private-key`，可从服务端强制绑定目标主机、用户名、密码和服务端侧私钥文件。前端会锁定或隐藏对应控件，后端仍会校验并覆盖敏感字段。如果用户没有填写口令、没有上传自定义私钥，也没有启用服务端本机密钥查找，SSH 连接会优先尝试 none authentication，与 `simple-ssh-copy` 的空凭据路径保持一致。
- 中英双语：默认英文，网页和日志页都支持中英切换；语言选择会长期保存到 `py_web_ssh_lang` cookie。
- 浏览器客户端 session：首次访问时服务端会分配独立的浏览器 session UUID，并写入 HttpOnly cookie；它与 SSH 会话 UUID 分离。
- 左侧控制面板：连接、算法、会话、文件四个栏目改为互斥折叠面板，一次最多展开一个，也可以全部折叠。

### 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

### 启动

```bash
py-web-ssh
```

或者：

```bash
uvicorn webssh.app:app --host 0.0.0.0 --port 8022
```

打开 <http://127.0.0.1:8022>。

启用 PIN：

```bash
py-web-ssh --pin 123456
```

设置网页标题和副标题：

```bash
py-web-ssh --title "Ops SSH" --subtitle "Production Access"
```

锁定连接目标或凭据：

```bash
py-web-ssh --lock-host server.example.com --lock-username deploy
py-web-ssh --lock-pwd 'ssh-password'
py-web-ssh --lock-private-key C:\secrets\id_ed25519
```

`--lock-pwd` 和 `--lock-private-key` 的值只在服务端使用，不会通过配置接口发送给浏览器。`--lock-private-key` 指向的是服务端本机文件路径，不是浏览器上传的文件。

前端默认从 jsDelivr 加载 xterm.js、fit addon 和 serialize addon。离线内网部署时，请把这些静态资源 vendoring 到 `webssh/static/` 并替换 `index.html` 里的 CDN 地址。

### API 概览

- `GET /api/config` 查看非敏感的服务端公开配置和锁定状态。
- `GET /api/algorithms` 查看当前服务端 Paramiko 支持的 SSH 算法列表。
- `POST /api/sessions` 创建 SSH 会话。
- `GET /api/sessions/{uuid}` 查看会话状态。
- `GET /api/sessions/{uuid}/logs` 获取完整日志 JSON。
- `DELETE /api/sessions/{uuid}` 主动断开 SSH。
- `WS /ws/sessions/{uuid}` 终端输入、输出、resize、快照和断开控制。
- `POST /api/sessions/{uuid}/files/upload` 上传文件，multipart 字段：`remote_path`、`file`。
- `GET /api/sessions/{uuid}/files/download?remote_path=/path/file` 下载远端文件。

### 安全提示

这个项目默认面向可信内网或本机使用。私钥和口令只保存在进程内存中，不写入日志；SSH agent 已禁用，`known_hosts` 校验已移除，用户必须在 xterm.js 终端里确认服务器 host key 指纹后才会继续认证。如果要暴露到公网，请务必加 HTTPS、登录认证、CSRF/来源限制、审计和会话回收策略。
