# Usage Guide

[中文](usage.zh-CN.md)

py-web-ssh starts a FastAPI server and serves an xterm.js based SSH terminal. The default UI language is English, and the web page can switch between English and Chinese.

## Installation

Install the published package:

```bash
pip install py-web-ssh
```

For editable development from the repository root:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

## Start The Server

```bash
py-web-ssh
```

The default bind address is `0.0.0.0:8022`. Open <http://127.0.0.1:8022> from the same machine.

You can also run the ASGI app directly:

```bash
uvicorn webssh.app:app --host 0.0.0.0 --port 8022
```

Use `--launch-browser` to open the web UI in the system default browser after the server has successfully started. The browser is opened once, and when multiple listening addresses are available py-web-ssh prefers `127.0.0.1` for the URL.

```bash
py-web-ssh --launch-browser
```

Use `--auto-port` to try the configured `--port` first, then keep trying higher ports until one can be bound.

```bash
py-web-ssh --host 127.0.0.1 --port 8022 --auto-port --launch-browser
```

Use `--block-size` to set the initial upload command-size probe. Values accept bytes by default, or `B`, `KB`, `MB`, `GB`, and `TB` suffixes.

```bash
py-web-ssh --block-size 12KB
py-web-ssh --block-size 2048
```

On Windows, a frozen one-file exe started without arguments behaves as if these options were supplied:

```bash
py-web-ssh.exe --host 127.0.0.1 --auto-port --launch-browser
```

If any argument is passed to the exe, it follows the same CLI behavior as the Python package.

## Login Methods

The connection form supports password authentication, browser-uploaded private keys, private-key passphrases, and server-local key lookup from the process user's default `~/.ssh` keys.

Browser-uploaded private keys are parsed with the private-key loaders available in the installed Paramiko runtime, including Ed25519, ECDSA, RSA, and legacy DSA when supported.

If no password, no custom private key, and no server-local key lookup are used, py-web-ssh tries SSH none authentication first. This supports servers that allow login without a password or public key.

Every interactive SSH connection shows the server host key fingerprint in the terminal and waits for the browser user to type `Y` or `N` before authentication continues. `known_hosts` verification is not used.

## PIN Gate

Start with `--pin` to require a PIN before the browser can access the UI APIs, logs, file endpoints, and WebSocket.

```bash
py-web-ssh --pin 123456
```

After successful verification, the browser stores a signed, salted hash cookie.

## Branding

```bash
py-web-ssh --title "Ops SSH" --subtitle "Production Access"
```

The subtitle area always includes the package version as `(py-web-ssh vx.y.z)`. The title and subtitle do not change when the UI language changes.

## Server-Side Locks

Use locks to enforce connection values from the server:

```bash
py-web-ssh --lock-host server.example.com --lock-username deploy
py-web-ssh --lock-pwd "ssh-password"
py-web-ssh --lock-private-key C:\secrets\id_ed25519
```

`--lock-pwd` and `--lock-private-key` are used only on the server. Their values are not returned by `GET /api/config`. `--lock-private-key` points to a server-local file path, not a browser-uploaded file.

## Target Host Guards

```bash
py-web-ssh --ban-lan
py-web-ssh --ban-dns
py-web-ssh --ban-ipv6
py-web-ssh --ban-host secret.internal --ban-host "*.corp.local"
```

`--ban-lan` blocks private or local IP literals such as `192.168.1.10`, `127.0.0.1`, `::1`, `fc00::1`, and `fe80::1`. It does not resolve hostnames, so a hostname that resolves to a LAN IP is still allowed by this specific guard.

`--ban-dns` allows only IP address literals. Hostnames are rejected.

`--ban-ipv6` rejects IPv6 address literals. IPv4 literals and hostnames remain allowed unless another guard blocks them.

`--ban-host` can be repeated. Matching is enforced only on the backend, is case-insensitive, and supports `*` as a wildcard that matches any hostname characters, including dots and zero characters. When a target matches a banned pattern, the API reports a DNS resolution failure rather than exposing the ban rule.

## Sessions And Reconnect

Creating a session returns a random SSH session UUID. If the WebSocket disconnects, the browser can reconnect to the same UUID. The server stores the SSH output stream, and the browser periodically sends xterm serialize snapshots. On WebSocket reconnect, the browser restores the latest snapshot first, then replays server-side output after that snapshot.

The `Reconnect` button has two modes. When the WebSocket is disconnected, it reconnects the browser to the same server-side session UUID. When the WebSocket is open and the SSH session is connected, it creates a fresh SSH session from the last connection form payload. That payload is encrypted with Web Crypto and stored only in `sessionStorage`; the encryption key is kept in memory for the current browser tab.

If all browser connections for the same UUID disconnect and no one reconnects within 5 minutes, the server actively disconnects SSH and clears in-memory caches.

The logs page at `/sessions/{uuid}/logs` shows connection, authentication, error, and file-transfer logs.

## Files Panel

File transfer does not use SFTP or SCP. Each transfer creates a separate SSH connection from the same connection configuration, verifies that the server host key still matches the key confirmed in the interactive terminal, then uses bounded remote shell commands to move data.

Uploads append base64 chunks to a temporary remote file, decode it into a temporary data file, and move it to the final path. Downloads stream file content back through a separate SSH command.

Before upload, the target path is probed. If the target is a remote directory, the browser-uploaded file's original name is placed inside it. If the target does not exist or is a regular file, the specified path is overwritten.

The upload command-size probe starts at 1 MiB by default, or the value configured with `--block-size`. The Files panel lets the user choose a positive integer value with `TB`, `GB`, `MB`, `KB`, or `B` units. The frontend clamps values below `64 B` to `64 B`; the backend also enforces a minimum of `64 B`. If the initial probe fails because the command is too large or the connection closes, py-web-ssh binary-searches downward and writes the selected size to the logs.

## CWD Sync

The Files panel includes a read-only current working directory field and a checked-by-default `CWD Sync` checkbox. When enabled, py-web-ssh installs a hidden shell-side monitor after login and filters its private OSC reports before terminal output reaches the browser. The field updates when the remote shell prompt is reached after directory changes such as `cd`, `pushd`, or `popd`.

When `CWD Sync` is unchecked, the backend stops reporting CWD updates and the read-only field is cleared. When it is checked again, the field stays empty until the next observed directory change.

The upload path defaults follow the synced current working directory when CWD Sync is active.

The terminal-side Directory panel uses the same CWD Sync listing. Regular files show `Download` and `Delete`; directories show `Enter Dir` and `Delete`. File deletion opens an in-app confirmation dialog and, after confirmation, sends a visible `rm -- 'file-name'` command to the shell. Directory deletion asks for confirmation and then sends a visible `rm -rf -- 'directory-name'` command. Directory entry uses `Enter Dir` to send a visible `cd 'directory-name'` command. `UP`, `Enter Dir`, and `Delete` are enabled only when the backend has confirmed that the remote session is back at a shell prompt, so they are disabled while another terminal program is active or while the user is typing a command.

The Directory panel splits entries into two equal-height stacked tables: visible files and hidden files. Any entry whose name starts with `.` is treated as hidden. After a successful upload, and after a file delete command returns to a ready shell prompt, py-web-ssh silently refreshes the current directory listing with the hidden CWD Sync channel.

When the SSH session state becomes `closed`, the Directory panel clears its current directory, listing, loading state, and errors back to the initial empty state.

## Static Assets

The frontend loads xterm.js, the fit addon, and the serialize addon from jsDelivr by default. For offline intranet deployment, vendor those assets into `webssh/static/` and update the CDN URLs in `webssh/static/index.html`.

## Security Notes

py-web-ssh is designed by default for trusted intranet or local use. Private keys and passphrases are kept only in process memory and are not written to logs. SSH agent authentication is disabled. If you expose the server to the public internet, add HTTPS, stronger login authentication, CSRF/origin restrictions, auditing, and session cleanup policies.
