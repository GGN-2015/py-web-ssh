# API 参考

[English](api.md)

Web UI 使用的就是这里描述的 HTTP 与 WebSocket API。除非另有说明，响应都是 JSON。

服务端使用 `--pin` 启动时，除 `/`、`/static/*`、`/favicon.ico`、`GET /api/auth/status`、`POST /api/auth/login` 外，所有路径都需要 PIN auth cookie。未授权 HTTP 请求返回 `401`；未授权 WebSocket 会以 `4401` 关闭。

## 数据结构

`ConnectRequest`：

```json
{
  "host": "server.example.com",
  "port": 22,
  "username": "deploy",
  "password": "optional password",
  "private_key": "optional PEM private key text",
  "private_key_passphrase": "optional passphrase",
  "look_for_keys": false,
  "disabled_algorithms": {},
  "cwd_sync": true,
  "term": "xterm-256color",
  "size": {"cols": 100, "rows": 30},
  "timeout_seconds": 20.0,
  "keepalive_seconds": 30,
  "scrollback_bytes": 10000000
}
```

会话摘要会脱敏敏感字段：`password`、`private_key`、`private_key_passphrase` 会以布尔值返回。

会话状态包括 `connecting`、`waiting_host_key`、`connected`、`closing`、`closed` 和 `error`。

## Auth

### `GET /api/auth/status`

返回 PIN auth 是否启用，以及当前请求是否已经授权。

```json
{"enabled": true, "authorized": false}
```

### `POST /api/auth/login`

请求：

```json
{"pin": "123456"}
```

成功时返回 `{"ok": true, "enabled": true}`，并设置 PIN auth cookie。PIN 错误返回 `401`。

## 公开配置

### `GET /api/config`

返回非敏感的运行时公开配置：

```json
{
  "branding": {
    "title": "py-web-ssh",
    "subtitle": "Web SSH Client",
    "version": "0.1.30"
  },
  "locks": {
    "host": {"enabled": false, "value": null},
    "username": {"enabled": false, "value": null},
    "password": {"enabled": false},
    "private_key": {"enabled": false}
  },
  "security": {
    "ban_lan": false,
    "ban_dns": false,
    "ban_ipv6": false
  }
}
```

密码和私钥锁定值永远不会返回。

### `GET /api/algorithms`

返回当前 Paramiko 运行时支持的 SSH 算法分组。参见 [SSH 算法控制](algorithms.zh-CN.md)。

## Sessions

### `POST /api/sessions`

使用 `ConnectRequest` 创建 SSH 会话。

服务端锁定规则和目标 host 限制会在会话启动前应用。非法算法选择返回 `422`。Host 限制失败通常返回 `403`，但命中 `--ban-host` 的目标会故意返回 `502` 和 `DNS resolution failed.`。

响应：

```json
{
  "session_id": "uuid",
  "logs_url": "/sessions/uuid/logs",
  "websocket_url": "/ws/sessions/uuid"
}
```

### `GET /api/sessions`

返回会话摘要列表。

### `GET /api/sessions/{uuid}`

返回单个会话摘要：

```json
{
  "session_id": "uuid",
  "state": "connected",
  "created_at": "2026-06-24T00:00:00Z",
  "updated_at": "2026-06-24T00:00:01Z",
  "config": {},
  "output_next_seq": 1234,
  "output_earliest_seq": 0,
  "has_snapshot": true,
  "connected_clients": 1
}
```

### `GET /api/sessions/{uuid}/logs`

返回会话摘要和完整日志：

```json
{
  "session": {},
  "logs": [
    {
      "timestamp": "2026-06-24T00:00:00Z",
      "level": "info",
      "message": "SSH authentication succeeded.",
      "details": null
    }
  ]
}
```

### `GET /sessions/{uuid}/logs`

返回供浏览器查看的 HTML 日志页面。

### `DELETE /api/sessions/{uuid}`

主动断开 SSH，并返回：

```json
{"ok": true}
```

## 文件传输

文件传输要求用户已经在交互终端确认过 SSH 服务器 host key，否则 API 返回 `409`。

### `POST /api/sessions/{uuid}/files/uploads`

在发送文件字节前创建上传 tracker。

请求：

```json
{
  "remote_path": "/tmp/file.bin",
  "total_bytes": 1048576
}
```

响应：

```json
{
  "transfer_id": "uuid",
  "state": "running",
  "remote_path": "/tmp/file.bin",
  "total_bytes": 1048576
}
```

### `POST /api/sessions/{uuid}/files/upload`

使用 `multipart/form-data` 上传文件。

字段：

- `remote_path`：必填，远端路径。
- `file`：必填，上传文件。
- `transfer_id`：可选，来自 `POST /api/sessions/{uuid}/files/uploads` 的 tracker id。
- `total_bytes`：可选，总字节数。
- `upload_command_size_bytes`：可选，正整数初始探测大小。小于 `64` 的值会被收敛到 `64`。

响应：

```json
{
  "ok": true,
  "method": "shell",
  "bytes_transferred": 1048576,
  "remote_path": "/tmp/file.bin",
  "message": "Uploaded 1048576 bytes to /tmp/file.bin using shell.",
  "transfer_id": "uuid"
}
```

取消上传返回 HTTP `499`。上传失败返回 `500`。

### `GET /api/sessions/{uuid}/files/download?remote_path=/path/file`

以 `application/octet-stream` 下载远端文件。响应包含：

- `Content-Disposition`：附件文件名。
- `X-Transfer-Method`：目前为 `shell`。

### `GET /api/transfers/{transfer_id}`

返回当前上传状态：

```json
{
  "transfer_id": "uuid",
  "state": "running",
  "bytes_transferred": 524288,
  "total_bytes": 1048576,
  "remote_path": "/tmp/file.bin",
  "message": "Uploading.",
  "created_at": "2026-06-24T00:00:00Z",
  "updated_at": "2026-06-24T00:00:01Z"
}
```

`state` 可以是 `running`、`completed`、`cancelled` 或 `failed`。

### `DELETE /api/transfers/{transfer_id}`

请求取消上传，并返回：

```json
{"ok": true}
```

## WebSocket

### `WS /ws/sessions/{uuid}`

连接接受后，服务端先发送：

```json
{"type": "session", "session_id": "uuid"}
```

随后发送 `replay` payload：

```json
{
  "type": "replay",
  "state": "connected",
  "snapshot_seq": 100,
  "snapshot": "base64 xterm serialize snapshot or null",
  "history_earliest_seq": 0,
  "history_next_seq": 120,
  "chunks": [{"seq": 100, "data": "base64 terminal bytes"}],
  "logs": [],
  "warning": null,
  "cwd": "/home/deploy",
  "cwd_sync": true
}
```

服务端发给浏览器的消息：

- `output`: `{ "type": "output", "seq": number, "data": "base64 terminal bytes" }`
- `status`: `{ "type": "status", "state": "connected" }`
- `log`: `{ "type": "log", "entry": LogEntry }`
- `cwd`: `{ "type": "cwd", "cwd": "/path" }`
- `cwd_sync`: `{ "type": "cwd_sync", "enabled": true }`

浏览器发给服务端的消息：

- `input`: `{ "type": "input", "data": "base64 terminal input bytes" }`
- `resize`: `{ "type": "resize", "cols": 120, "rows": 40 }`
- `snapshot`: `{ "type": "snapshot", "seq": 1234, "data": "base64 xterm serialize snapshot" }`
- `cwd_sync`: `{ "type": "cwd_sync", "enabled": true }`
- `disconnect`: `{ "type": "disconnect" }`
- `ping`: `{ "type": "ping" }`

隐藏 CWD Sync OSC 汇报会由后端过滤，不会作为终端字节发送给浏览器。

