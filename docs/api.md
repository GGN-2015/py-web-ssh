# API Reference

[中文](api.zh-CN.md)

The web UI uses the same HTTP and WebSocket API described here. Unless noted otherwise, responses are JSON.

When the server is started with `--pin`, all paths except `/`, `/static/*`, `/favicon.ico`, `GET /api/auth/status`, and `POST /api/auth/login` require the PIN auth cookie. Unauthorized HTTP requests return `401`; unauthorized WebSockets close with code `4401`.

## Data Shapes

`ConnectRequest`:

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

Sensitive fields are sanitized in session summaries: `password`, `private_key`, and `private_key_passphrase` are returned as booleans.

Session states are `connecting`, `waiting_host_key`, `connected`, `closing`, `closed`, or `error`.

## Auth

### `GET /api/auth/status`

Returns whether PIN auth is enabled and whether the current request is already authorized.

```json
{"enabled": true, "authorized": false}
```

### `POST /api/auth/login`

Request:

```json
{"pin": "123456"}
```

On success, returns `{"ok": true, "enabled": true}` and sets the PIN auth cookie. Invalid PIN returns `401`.

## Public Config

### `GET /api/config`

Returns public, non-sensitive runtime configuration:

```json
{
  "branding": {
    "title": "py-web-ssh",
    "subtitle": "Web SSH Client",
    "version": "0.1.33"
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
  },
  "upload": {
    "block_size_bytes": 1048576
  }
}
```

Password and private-key lock values are never returned.

`upload.block_size_bytes` is the server default initial upload probe size after applying the `64 B` minimum.

### `GET /api/algorithms`

Returns SSH algorithm groups supported by the current Paramiko runtime. See [SSH Algorithm Controls](algorithms.md).

## Sessions

### `POST /api/sessions`

Creates an SSH session from `ConnectRequest`.

Server-side locks and target-host guards are applied before the session starts. Invalid algorithm selections return `422`. Host guard failures return `403`, except banned `--ban-host` matches intentionally report `502` with `DNS resolution failed.`

Response:

```json
{
  "session_id": "uuid",
  "logs_url": "/sessions/uuid/logs",
  "websocket_url": "/ws/sessions/uuid"
}
```

### `GET /api/sessions`

Returns a list of session summaries.

### `GET /api/sessions/{uuid}`

Returns one session summary:

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

Returns session summary plus complete logs:

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

Returns the HTML logs page for a browser.

### `DELETE /api/sessions/{uuid}`

Actively disconnects SSH and returns:

```json
{"ok": true}
```

## File Transfers

File transfers require that the user has already confirmed the SSH server host key in the interactive terminal. Otherwise, the API returns `409`.

### `POST /api/sessions/{uuid}/files/uploads`

Creates an upload tracker before sending file bytes.

Request:

```json
{
  "remote_path": "/tmp/file.bin",
  "total_bytes": 1048576
}
```

Response:

```json
{
  "transfer_id": "uuid",
  "state": "running",
  "remote_path": "/tmp/file.bin",
  "total_bytes": 1048576
}
```

### `POST /api/sessions/{uuid}/files/upload`

Uploads a file with `multipart/form-data`.

Fields:

- `remote_path`: required remote path.
- `file`: required uploaded file.
- `transfer_id`: optional tracker id from `POST /api/sessions/{uuid}/files/uploads`.
- `total_bytes`: optional total byte count.
- `upload_command_size_bytes`: optional positive integer initial probe size. Values below `64` are clamped to `64`.

Response:

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

Cancelled uploads return HTTP `499`. Failed uploads return `500`.

### `GET /api/sessions/{uuid}/files/download?remote_path=/path/file`

Downloads a remote file as `application/octet-stream`. The response includes:

- `Content-Disposition`: attachment filename.
- `X-Transfer-Method`: currently `shell`.

### `GET /api/transfers/{transfer_id}`

Returns current upload status:

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

`state` is `running`, `completed`, `cancelled`, or `failed`.

### `DELETE /api/transfers/{transfer_id}`

Requests upload cancellation and returns:

```json
{"ok": true}
```

## WebSocket

### `WS /ws/sessions/{uuid}`

After accepting, the server sends:

```json
{"type": "session", "session_id": "uuid"}
```

Then it sends a `replay` payload:

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

Server-to-browser messages:

- `output`: `{ "type": "output", "seq": number, "data": "base64 terminal bytes" }`
- `status`: `{ "type": "status", "state": "connected" }`
- `log`: `{ "type": "log", "entry": LogEntry }`
- `cwd`: `{ "type": "cwd", "cwd": "/path" }`
- `cwd_sync`: `{ "type": "cwd_sync", "enabled": true }`

Browser-to-server messages:

- `input`: `{ "type": "input", "data": "base64 terminal input bytes" }`
- `resize`: `{ "type": "resize", "cols": 120, "rows": 40 }`
- `snapshot`: `{ "type": "snapshot", "seq": 1234, "data": "base64 xterm serialize snapshot" }`
- `cwd_sync`: `{ "type": "cwd_sync", "enabled": true }`
- `disconnect`: `{ "type": "disconnect" }`
- `ping`: `{ "type": "ping" }`

The hidden CWD sync OSC reports are filtered by the backend before terminal bytes are sent to the browser.
