from __future__ import annotations

import asyncio
import base64
import binascii
import posixpath
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any, Literal

import paramiko
from starlette.websockets import WebSocket

from .history import OutputChunk, OutputHistory
from .models import ConnectRequest, LogEntry, SessionSummary
from .ssh_client import ConnectedClient, HostKeyInfo, connect_ssh


SessionState = Literal["connecting", "waiting_host_key", "connected", "closing", "closed", "error"]
CWD_OSC_PREFIX = b"\x1b]6970;cwd;"
CWD_LISTING_OSC_PREFIX = b"\x1b]6970;ls;"
CWD_READY_OSC_PREFIX = b"\x1b]6970;ready;"
CWD_OSC_SUFFIX = b"\x07"
CWD_TOKEN_PLACEHOLDER = "__PY_WEB_SSH_CWD_TOKEN__"
MAX_HIDDEN_COMMAND_LENGTH = 1024
CWD_REPORT_FUNCTION = "__py_web_ssh_cwd_report"
CWD_LIST_FUNCTION = "__py_web_ssh_cwd_list"
CWD_READY_FUNCTION = "__py_web_ssh_cwd_ready"
CWD_INSTALL_COMMAND_TEMPLATES = (
    "__py_web_ssh_cwd_armed=; "
    "__py_web_ssh_cwd_ready(){ "
    "[ -n \"${__py_web_ssh_cwd_armed-}\" ] || return; "
    "printf '\\033]6970;ready;" + CWD_TOKEN_PLACEHOLDER + "=1\\007' >&2; "
    "}",
    "__py_web_ssh_cwd_list(){ "
    "[ -n \"${__py_web_ssh_cwd_armed-}\" ] || return; "
    "__py_web_ssh_cwd_ls=$(LC_ALL=C command ls -al 2>&1 | command base64 | command tr -d '\\r\\n') || __py_web_ssh_cwd_ls=; "
    "printf '\\033]6970;ls;" + CWD_TOKEN_PLACEHOLDER + "=%s\\007' \"$__py_web_ssh_cwd_ls\" >&2; "
    "}",
    "__py_web_ssh_cwd_report(){ "
    "[ -n \"${__py_web_ssh_cwd_armed-}\" ] || return; "
    "__py_web_ssh_cwd_now=$(command pwd 2>/dev/null || printf '%s' \"$PWD\") || return; "
    "if [ \"${__py_web_ssh_cwd_now}\" != \"${__py_web_ssh_cwd_last-}\" ]; then "
    "__py_web_ssh_cwd_last=$__py_web_ssh_cwd_now; "
    "printf '\\033]6970;cwd;" + CWD_TOKEN_PLACEHOLDER + "=%s\\007' \"$__py_web_ssh_cwd_now\" >&2; "
    "__py_web_ssh_cwd_list; "
    "fi; "
    "__py_web_ssh_cwd_ready; "
    "}",
    "if [ -n \"${BASH_VERSION:-}\" ]; then "
    "PROMPT_COMMAND=\"__py_web_ssh_cwd_report${PROMPT_COMMAND:+;$PROMPT_COMMAND}\"; "
    "elif [ -n \"${ZSH_VERSION:-}\" ]; then "
    "autoload -Uz add-zsh-hook 2>/dev/null && add-zsh-hook precmd __py_web_ssh_cwd_report || "
    "precmd_functions+=(__py_web_ssh_cwd_report); "
    "else "
    "__py_web_ssh_cwd_prompt=; "
    "PS1='${__py_web_ssh_cwd_prompt:-$(__py_web_ssh_cwd_report)}'\"${PS1-}\"; "
    "PS2='${__py_web_ssh_cwd_prompt:-$(__py_web_ssh_cwd_report)}'\"${PS2-}\"; "
    "fi"
)
CWD_INITIAL_REPORT_COMMAND_TEMPLATE = "__py_web_ssh_cwd_armed=1; " + CWD_REPORT_FUNCTION
CWD_INITIAL_READY_COMMAND_TEMPLATE = "__py_web_ssh_cwd_armed=1; " + CWD_READY_FUNCTION
CWD_INSTALL_COMMAND_TEMPLATE = "; ".join(CWD_INSTALL_COMMAND_TEMPLATES)


def cwd_install_commands(token: str, cwd_sync_enabled: bool) -> list[str]:
    commands = [
        command.replace(CWD_TOKEN_PLACEHOLDER, token)
        for command in CWD_INSTALL_COMMAND_TEMPLATES
    ]
    final_command = (
        CWD_INITIAL_REPORT_COMMAND_TEMPLATE
        if cwd_sync_enabled
        else CWD_INITIAL_READY_COMMAND_TEMPLATE
    )
    commands.append(final_command.replace(CWD_TOKEN_PLACEHOLDER, token))
    too_long = [command for command in commands if len(command.encode("utf-8")) > MAX_HIDDEN_COMMAND_LENGTH]
    if too_long:
        raise ValueError("A hidden SSH command exceeds the 1024 byte limit.")
    return commands


@dataclass(eq=False)
class BrowserConnection:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]


class TerminalSession:
    def __init__(self, config: ConnectRequest, clock: Callable[[], float] = time.monotonic) -> None:
        self.id = str(uuid.uuid4())
        self.config = config
        self._clock = clock
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = self.created_at
        self.state: SessionState = "connecting"
        self.history = OutputHistory(config.scrollback_bytes)
        self._logs: list[LogEntry] = []
        self._clients: set[BrowserConnection] = set()
        self._lock = threading.RLock()
        self._channel_lock = threading.RLock()
        self._host_key_lock = threading.Condition(threading.RLock())
        self._awaiting_host_key_confirmation = False
        self._host_key_decision: bool | None = None
        self._confirmed_host_key: HostKeyInfo | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"ssh-session-{self.id}", daemon=True)
        self._connected: ConnectedClient | None = None
        self._channel: paramiko.Channel | None = None
        self._snapshot: tuple[int, bytes, datetime] | None = None
        self._cwd_token = uuid.uuid4().hex
        self._cwd_osc_prefix = CWD_OSC_PREFIX + self._cwd_token.encode("ascii") + b"="
        self._cwd_listing_osc_prefix = CWD_LISTING_OSC_PREFIX + self._cwd_token.encode("ascii") + b"="
        self._cwd_ready_osc_prefix = CWD_READY_OSC_PREFIX + self._cwd_token.encode("ascii") + b"="
        self._current_working_directory = ""
        self._current_directory_listing: list[dict[str, object]] = []
        self._directory_listing_error = ""
        self._cwd_sync_enabled = config.cwd_sync
        self._cwd_sync_waiting_for_change = False
        self._last_observed_working_directory = ""
        self._shell_prompt_ready = False
        self._terminal_filter_buffer = b""
        self._hidden_echo_filter_buffer = b""
        self._hidden_command_echoes: list[bytes] = []
        self._hidden_terminal_transaction_active = False
        self._hidden_terminal_transaction_closing = False
        self._last_client_detached_at: float | None = self._clock()
        self._reaped = False

    def start(self) -> None:
        self._thread.start()

    def attach(self, websocket: WebSocket) -> BrowserConnection:
        connection = BrowserConnection(loop=asyncio.get_running_loop(), queue=asyncio.Queue(maxsize=512))
        with self._lock:
            if self._reaped:
                raise RuntimeError("Session was cleaned up after being idle.")
            self._clients.add(connection)
            self._last_client_detached_at = None
        return connection

    def detach(self, connection: BrowserConnection) -> None:
        with self._lock:
            self._clients.discard(connection)
            if not self._clients:
                self._last_client_detached_at = self._clock()

    def summary(self) -> SessionSummary:
        with self._lock:
            return SessionSummary(
                session_id=self.id,
                state=self.state,
                created_at=self.created_at,
                updated_at=self.updated_at,
                config=self.config.sanitized(),
                output_next_seq=self.history.next_seq,
                output_earliest_seq=self.history.earliest_seq,
                has_snapshot=self._snapshot is not None,
                connected_clients=len(self._clients),
            )

    def logs(self) -> list[LogEntry]:
        with self._lock:
            return list(self._logs)

    def log(self, level: str, message: str, details: str | None = None) -> None:
        entry = LogEntry(level=level, message=message, details=details)
        with self._lock:
            self._logs.append(entry)
            self.updated_at = entry.timestamp
        self._broadcast(
            {
                "type": "log",
                "entry": entry.model_dump(mode="json"),
            }
        )

    def replay_payload(self) -> dict[str, Any]:
        with self._lock:
            snapshot_seq: int | None = None
            snapshot_b64: str | None = None
            warning: str | None = None
            if self._snapshot is not None:
                snapshot_seq, snapshot, _created_at = self._snapshot
                snapshot_b64 = base64.b64encode(snapshot).decode("ascii")
            elif self.history.earliest_seq > 0:
                warning = (
                    "The server trimmed early terminal bytes before any browser snapshot was saved. "
                    "Replay may be incomplete; reconnect sooner or increase scrollback_bytes."
                )

            since_seq = snapshot_seq
            if since_seq is not None and since_seq < self.history.earliest_seq:
                warning = (
                    "The server trimmed terminal bytes older than the latest browser snapshot. "
                    "Replay may be incomplete; increase scrollback_bytes for longer disconnected runs."
                )
                chunks = self.history.since()
            else:
                chunks = self.history.since(since_seq)

            return {
                "type": "replay",
                "state": self.state,
                "snapshot_seq": snapshot_seq,
                "snapshot": snapshot_b64,
                "history_earliest_seq": self.history.earliest_seq,
                "history_next_seq": self.history.next_seq,
                "chunks": [self._chunk_payload(chunk) for chunk in chunks],
                "logs": [entry.model_dump(mode="json") for entry in self._logs[-200:]],
                "warning": warning,
                "cwd": self._current_working_directory if self._cwd_sync_enabled else "",
                "directory_listing": self._current_directory_listing if self._cwd_sync_enabled else [],
                "directory_listing_error": self._directory_listing_error if self._cwd_sync_enabled else "",
                "cwd_sync": self._cwd_sync_enabled,
                "shell_ready": self._shell_prompt_ready if self._cwd_sync_enabled else False,
            }

    def send_input(self, data: bytes) -> None:
        if self._handle_host_key_confirmation_input(data):
            return
        self._send_visible_terminal_input(data)

    def enter_directory(self, directory_name: str) -> None:
        name = _valid_directory_entry_name(directory_name)
        with self._lock:
            shell_ready = self._cwd_sync_enabled and self._shell_prompt_ready
            directory_names = {
                str(entry.get("name", ""))
                for entry in self._current_directory_listing
                if entry.get("type") == "directory"
            }
        if not shell_ready:
            raise RuntimeError("The remote shell prompt is not ready.")
        if name not in directory_names:
            raise ValueError("Directory entry is not available.")
        self._send_visible_terminal_input(f"cd {_posix_shell_quote(name)}\r".encode("utf-8"))

    def enter_parent_directory(self) -> None:
        with self._lock:
            shell_ready = self._cwd_sync_enabled and self._shell_prompt_ready
            cwd = self._current_working_directory
        if not shell_ready:
            raise RuntimeError("The remote shell prompt is not ready.")
        if not cwd or cwd == "/":
            raise ValueError("Current directory has no parent directory.")
        self._send_visible_terminal_input(b"cd ..\r")

    def _send_visible_terminal_input(self, data: bytes) -> None:
        with self._channel_lock:
            if self._channel is None or self.state != "connected":
                raise RuntimeError("SSH channel is not connected.")
            if self._hidden_terminal_transaction_active:
                raise RuntimeError("SSH channel is preparing the hidden shell monitor.")
            self._clear_hidden_terminal_transaction()
            self._set_shell_prompt_ready(False)
            self._channel.sendall(data)

    def resize(self, cols: int, rows: int) -> None:
        with self._channel_lock:
            if self._channel is not None and self.state == "connected":
                self._channel.resize_pty(width=cols, height=rows)

    def save_snapshot(self, seq: int, snapshot: bytes) -> None:
        with self._lock:
            if seq <= self.history.next_seq:
                self._snapshot = (seq, snapshot, datetime.now(timezone.utc))

    def set_cwd_sync_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._cwd_sync_enabled = enabled
            self._current_working_directory = ""
            self._current_directory_listing = []
            self._directory_listing_error = ""
            self._cwd_sync_waiting_for_change = enabled
            self.updated_at = datetime.now(timezone.utc)
        self._set_shell_prompt_ready(False)
        self._broadcast({"type": "cwd_sync", "enabled": enabled})
        self._broadcast({"type": "cwd", "cwd": ""})
        self._broadcast({"type": "directory_listing", "cwd": "", "entries": [], "error": "", "loading": False})

    def close(self, reason: str = "Client requested disconnect.") -> None:
        self.log("info", reason, None)
        self._set_state("closing")
        self._stop.set()
        with self._channel_lock:
            if self._channel is not None:
                self._channel.close()
            if self._connected is not None:
                self._connected.client.close()

    def mark_reaped_if_idle(self, now: float, idle_timeout_seconds: float) -> bool:
        with self._lock:
            if self._clients or self._last_client_detached_at is None or self._reaped:
                return False
            if now - self._last_client_detached_at < idle_timeout_seconds:
                return False
            self._reaped = True
            return True

    @property
    def ssh_client(self) -> paramiko.SSHClient:
        if self._connected is None or self.state not in ("connected", "closing", "closed"):
            raise RuntimeError("SSH connection is not ready.")
        return self._connected.client

    @property
    def confirmed_host_key(self) -> HostKeyInfo | None:
        with self._host_key_lock:
            return self._confirmed_host_key

    def _run(self) -> None:
        try:
            self.log("info", "Creating SSH connection.", None)
            self._connected = connect_ssh(
                self.config,
                self.log,
                confirm_host_key=self._confirm_host_key,
            )
            channel = self._connected.transport.open_session()
            channel.get_pty(
                term=self.config.term,
                width=self.config.size.cols,
                height=self.config.size.rows,
            )
            channel.invoke_shell()
            channel.settimeout(0.0)
            with self._channel_lock:
                self._channel = channel
            self._set_state("connected")
            self._drain_ready_terminal_output(channel)
            self._install_cwd_monitor()
            self.log("info", "Interactive SSH terminal is ready.", None)

            while not self._stop.is_set():
                try:
                    if channel.recv_ready():
                        data = channel.recv(64 * 1024)
                        if not data:
                            break
                        self._append_output(data)
                    elif channel.exit_status_ready():
                        break
                    else:
                        time.sleep(0.01)
                except paramiko.ssh_exception.SSHException:
                    raise
                except Exception as exc:
                    if self._stop.is_set():
                        break
                    if "timed out" not in str(exc).lower():
                        raise

            if self._stop.is_set():
                self._set_state("closed")
                self.log("info", "SSH terminal closed by request.", None)
            else:
                self._set_state("closed")
                self.log("warning", "SSH terminal channel closed by the remote server.", None)
        except Exception as exc:
            self._set_state("error")
            self.log("error", f"SSH session failed: {exc}", traceback.format_exc())
            self._append_output(f"\r\n[py-web-ssh] SSH session failed: {exc}\r\n".encode("utf-8"))
        finally:
            with self._channel_lock:
                try:
                    if self._channel is not None:
                        self._channel.close()
                finally:
                    self._channel = None
                if self._connected is not None:
                    self._connected.client.close()
            if self.state not in ("error", "closed"):
                self._set_state("closed")

    def _append_output(self, data: bytes) -> None:
        data = self._filter_hidden_terminal_output(data)
        if not data:
            return
        with self._lock:
            chunk = self.history.append(data)
            self.updated_at = datetime.now(timezone.utc)
        self._broadcast(self._chunk_payload(chunk) | {"type": "output"})

    def _install_cwd_monitor(self) -> None:
        try:
            self._send_hidden_terminal_commands(
                cwd_install_commands(self._cwd_token, self._cwd_sync_enabled)
            )
        except Exception as exc:
            self.log("warning", f"Could not start remote working-directory monitor: {exc}", None)

    def _send_hidden_terminal_command(self, command: str) -> None:
        self._send_hidden_terminal_commands([command])

    def _send_hidden_terminal_commands(self, commands: list[str]) -> None:
        if not commands:
            return
        payload = "".join(f"{command}\n" for command in commands).encode("utf-8")
        with self._channel_lock:
            if self._channel is None or self.state != "connected":
                return
            with self._lock:
                self._hidden_terminal_transaction_active = True
                self._hidden_terminal_transaction_closing = False
                self._hidden_command_echoes.clear()
                self._hidden_echo_filter_buffer = b""
            self._channel.sendall(payload)

    def _drain_ready_terminal_output(
        self,
        channel: paramiko.Channel,
        quiet_seconds: float = 0.08,
        max_seconds: float = 1.5,
    ) -> None:
        deadline = self._clock() + max_seconds
        quiet_deadline = self._clock() + quiet_seconds
        while not self._stop.is_set() and self._clock() < deadline:
            try:
                if channel.recv_ready():
                    data = channel.recv(64 * 1024)
                    if not data:
                        return
                    self._append_output(data)
                    quiet_deadline = self._clock() + quiet_seconds
                elif self._clock() >= quiet_deadline:
                    return
                else:
                    time.sleep(0.01)
            except Exception as exc:
                if "timed out" not in str(exc).lower():
                    raise

    def _filter_hidden_terminal_output(self, data: bytes) -> bytes:
        pending = self._terminal_filter_buffer + data
        self._terminal_filter_buffer = b""
        visible = bytearray()

        while pending:
            marker = self._next_hidden_osc_marker(pending)
            if marker is None:
                tail_length = self._hidden_osc_prefix_tail_length(pending)
                if tail_length:
                    if not self._hidden_terminal_output_suppressed():
                        visible.extend(pending[:-tail_length])
                    self._terminal_filter_buffer = pending[-tail_length:]
                else:
                    if not self._hidden_terminal_output_suppressed():
                        visible.extend(pending)
                break

            kind, prefix, start = marker
            if not self._hidden_terminal_output_suppressed():
                visible.extend(pending[:start])
            payload_start = start + len(prefix)
            end = pending.find(CWD_OSC_SUFFIX, payload_start)
            if end < 0:
                self._terminal_filter_buffer = pending[start:]
                break

            payload = pending[payload_start:end]
            if kind == "cwd":
                cwd = payload.decode("utf-8", errors="replace").replace("\x00", "")
                self._set_current_working_directory(cwd.strip("\r\n"))
            elif kind == "listing":
                self._set_current_directory_listing_from_base64(payload)
            else:
                self._set_shell_prompt_ready(True)
                self._finish_hidden_terminal_transaction()
            pending = pending[end + len(CWD_OSC_SUFFIX) :]

        return self._remove_hidden_command_echoes(bytes(visible))

    def _hidden_terminal_output_suppressed(self) -> bool:
        return self._hidden_terminal_transaction_active or self._hidden_terminal_transaction_closing

    def _finish_hidden_terminal_transaction(self) -> None:
        with self._lock:
            if not self._hidden_terminal_transaction_active:
                return
            self._hidden_terminal_transaction_active = False
            self._hidden_terminal_transaction_closing = True
            self._hidden_command_echoes.clear()
            self._hidden_echo_filter_buffer = b""

    def _clear_hidden_terminal_transaction(self) -> None:
        with self._lock:
            self._hidden_terminal_transaction_active = False
            self._hidden_terminal_transaction_closing = False
            self._terminal_filter_buffer = b""
            self._hidden_echo_filter_buffer = b""
            self._hidden_command_echoes.clear()

    def _next_hidden_osc_marker(self, data: bytes) -> tuple[str, bytes, int] | None:
        markers = [
            ("cwd", self._cwd_osc_prefix, data.find(self._cwd_osc_prefix)),
            ("listing", self._cwd_listing_osc_prefix, data.find(self._cwd_listing_osc_prefix)),
            ("ready", self._cwd_ready_osc_prefix, data.find(self._cwd_ready_osc_prefix)),
        ]
        found = [marker for marker in markers if marker[2] >= 0]
        if not found:
            return None
        return min(found, key=lambda marker: marker[2])

    def _hidden_osc_prefix_tail_length(self, data: bytes) -> int:
        prefixes = (self._cwd_osc_prefix, self._cwd_listing_osc_prefix, self._cwd_ready_osc_prefix)
        max_length = max(len(prefix) for prefix in prefixes) - 1
        for length in range(min(len(data), max_length), 0, -1):
            if any(prefix.startswith(data[-length:]) for prefix in prefixes):
                return length
        return 0

    def _remove_hidden_command_echoes(self, data: bytes) -> bytes:
        with self._lock:
            echoes = list(self._hidden_command_echoes)
        data = self._hidden_echo_filter_buffer + data
        self._hidden_echo_filter_buffer = b""
        if not echoes:
            return data

        if not data:
            return data

        visible = data
        remaining: list[bytes] = []
        buffered_tail = b""
        for echo in echoes:
            visible, echo_tail, removed = self._remove_hidden_command_echo(visible, echo)
            if echo_tail:
                buffered_tail = echo_tail + buffered_tail
            if echo_tail or not removed:
                remaining.append(echo)

        if not buffered_tail:
            tail_length = self._hidden_echo_tail_length(visible, remaining)
            if tail_length:
                buffered_tail = visible[-tail_length:]
                visible = visible[:-tail_length]
        self._hidden_echo_filter_buffer = buffered_tail

        with self._lock:
            self._hidden_command_echoes = remaining[-8:]
        return visible

    def _remove_hidden_command_echo(self, data: bytes, echo: bytes) -> tuple[bytes, bytes, bool]:
        if not echo:
            return data, b"", True

        visible = bytearray()
        index = 0
        removed = False
        first = echo[:1]
        while index < len(data):
            start = data.find(first, index)
            if start < 0:
                visible.extend(data[index:])
                break
            visible.extend(data[index:start])
            status, end = self._match_hidden_command_echo(data, start, echo)
            if status == "complete":
                if end == len(data):
                    return bytes(visible), data[start:], removed
                index = self._consume_hidden_command_echo_suffix(data, end)
                removed = True
                continue
            if status == "incomplete":
                return bytes(visible), data[start:], removed
            visible.append(data[start])
            index = start + 1

        return bytes(visible), b"", removed

    def _match_hidden_command_echo(self, data: bytes, start: int, echo: bytes) -> tuple[str, int]:
        data_index = start
        echo_index = 0
        while echo_index < len(echo):
            if data_index >= len(data):
                return "incomplete", data_index
            ignored_length = self._hidden_echo_ignored_sequence_length(data, data_index)
            if ignored_length is None:
                return "incomplete", data_index
            if ignored_length:
                data_index += ignored_length
                continue
            if data[data_index] != echo[echo_index]:
                return "mismatch", data_index
            data_index += 1
            echo_index += 1
        return "complete", data_index

    def _hidden_echo_ignored_sequence_length(self, data: bytes, index: int) -> int | None:
        byte = data[index]
        if byte in (0x08, 0x0A, 0x0D):
            return 1
        if data.startswith(b"\x1b[", index):
            for cursor in range(index + 2, len(data)):
                if 0x40 <= data[cursor] <= 0x7E:
                    return cursor - index + 1
            return None
        return 0

    def _consume_hidden_command_echo_suffix(self, data: bytes, index: int) -> int:
        while index < len(data):
            ignored_length = self._hidden_echo_ignored_sequence_length(data, index)
            if ignored_length is None:
                return index
            if not ignored_length:
                break
            index += ignored_length
        return index

    def _hidden_echo_tail_length(self, data: bytes, echoes: list[bytes]) -> int:
        tail_length = 0
        for echo in echoes:
            for pattern in (echo + b"\r\n", echo + b"\n", echo + b"\r", echo):
                for length in range(min(len(data), len(pattern) - 1), tail_length, -1):
                    if pattern.startswith(data[-length:]):
                        tail_length = length
                        break
        return tail_length

    def _set_current_working_directory(self, cwd: str) -> None:
        if not cwd:
            return
        listing_payload: dict[str, object] | None = None
        with self._lock:
            changed = cwd != self._last_observed_working_directory
            self._last_observed_working_directory = cwd
            if not self._cwd_sync_enabled:
                return
            if self._cwd_sync_waiting_for_change and not changed:
                return
            self._cwd_sync_waiting_for_change = False
            if cwd == self._current_working_directory:
                return
            self._current_working_directory = cwd
            self._current_directory_listing = []
            self._directory_listing_error = ""
            self.updated_at = datetime.now(timezone.utc)
            listing_payload = self._directory_listing_payload(loading=True)
        self._broadcast({"type": "cwd", "cwd": cwd})
        if listing_payload is not None:
            self._broadcast(listing_payload)

    def _set_current_directory_listing_from_base64(self, payload: bytes) -> None:
        try:
            decoded = base64.b64decode(b"".join(payload.split()), validate=True)
            listing_text = decoded.decode("utf-8", errors="replace")
            entries, error = parse_ls_al_listing(listing_text, self._current_working_directory)
        except (binascii.Error, ValueError):
            entries = []
            error = "directoryUnreadable"

        with self._lock:
            if not self._cwd_sync_enabled:
                return
            self._current_directory_listing = entries
            self._directory_listing_error = error
            self.updated_at = datetime.now(timezone.utc)
            payload_message = self._directory_listing_payload()
        self._broadcast(payload_message)

    def _directory_listing_payload(self, loading: bool = False) -> dict[str, object]:
        return {
            "type": "directory_listing",
            "cwd": self._current_working_directory,
            "entries": self._current_directory_listing,
            "error": self._directory_listing_error,
            "loading": loading,
        }

    def _set_shell_prompt_ready(self, ready: bool) -> None:
        ready = bool(ready and self._cwd_sync_enabled and self.state == "connected")
        with self._lock:
            if self._shell_prompt_ready == ready:
                return
            self._shell_prompt_ready = ready
            self.updated_at = datetime.now(timezone.utc)
        self._broadcast({"type": "shell_ready", "ready": ready})

    def _confirm_host_key(self, host_key: HostKeyInfo) -> bool:
        with self._host_key_lock:
            self._awaiting_host_key_confirmation = True
            self._host_key_decision = None
        self._set_state("waiting_host_key")
        self.log("warning", "Waiting for browser user to confirm SSH server host key.", host_key.details())
        self._append_output(self._host_key_prompt(host_key).encode("utf-8"))

        while not self._stop.is_set():
            with self._host_key_lock:
                if self._host_key_decision is not None:
                    accepted = self._host_key_decision
                    self._awaiting_host_key_confirmation = False
                    if accepted:
                        self._confirmed_host_key = host_key
                    break
                self._host_key_lock.wait(timeout=0.2)
        else:
            accepted = False
            with self._host_key_lock:
                self._awaiting_host_key_confirmation = False

        if accepted:
            self._append_output(b"Y\r\nContinuing SSH authentication...\r\n")
            self._set_state("connecting")
            return True

        self._append_output(b"N\r\nSSH connection cancelled before authentication.\r\n")
        return False

    def _handle_host_key_confirmation_input(self, data: bytes) -> bool:
        with self._host_key_lock:
            if not self._awaiting_host_key_confirmation:
                return False

        text = data.decode("utf-8", errors="ignore")
        decision: bool | None = None
        invalid = False
        for char in text:
            if char in "\r\n\t ":
                continue
            if char in ("y", "Y"):
                decision = True
                break
            if char in ("n", "N"):
                decision = False
                break
            invalid = True
            break

        if decision is None:
            if invalid:
                self._append_output(b"\r\nPlease type Y or N: ")
            return True

        with self._host_key_lock:
            self._host_key_decision = decision
            self._host_key_lock.notify_all()
        return True

    def _host_key_prompt(self, host_key: HostKeyInfo) -> str:
        return (
            "\r\n[py-web-ssh] SSH server host key fingerprint\r\n"
            f"Host: {self.config.host}:{self.config.port}\r\n"
            f"Key type: {host_key.key_type}\r\n"
            f"SHA256 fingerprint: {host_key.sha256_fingerprint}\r\n"
            f"MD5 fingerprint: {host_key.md5_fingerprint}\r\n"
            "Continue connecting? Type Y or N: "
        )

    def _chunk_payload(self, chunk: OutputChunk) -> dict[str, Any]:
        return {
            "seq": chunk.seq,
            "data": base64.b64encode(chunk.data).decode("ascii"),
        }

    def _set_state(self, state: SessionState) -> None:
        with self._lock:
            self.state = state
            self.updated_at = datetime.now(timezone.utc)
        if state != "connected":
            self._set_shell_prompt_ready(False)
        self._broadcast({"type": "status", "state": state})

    def _broadcast(self, message: dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.loop.call_soon_threadsafe(self._queue_message, client, message)
            except RuntimeError:
                self.detach(client)

    def _queue_message(self, client: BrowserConnection, message: dict[str, Any]) -> None:
        try:
            client.queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                client.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            client.queue.put_nowait(
                {
                    "type": "warning",
                    "message": "Browser message queue overflowed; an output frame was dropped.",
                }
            )


def parse_ls_al_listing(listing_text: str, cwd: str) -> tuple[list[dict[str, object]], str]:
    entries: list[dict[str, object]] = []
    errors: list[str] = []
    for raw_line in listing_text.splitlines():
        line = raw_line.strip("\r\n")
        if not line or line.startswith("total "):
            continue
        parts = line.split(maxsplit=8)
        if len(parts) >= 9 and parts[8] in {".", ".."}:
            continue
        entry = _parse_ls_al_line(line, cwd)
        if entry is None:
            errors.append(line)
        else:
            entries.append(entry)
    error = ""
    if errors:
        error = "directoryUnreadable"
    return entries, error


def _valid_directory_entry_name(name: str) -> str:
    name = str(name)
    if not name or "/" in name or "\x00" in name or name in {".", ".."}:
        raise ValueError("Invalid directory entry name.")
    return name


def _posix_shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _parse_ls_al_line(line: str, cwd: str) -> dict[str, object] | None:
    parts = line.split(maxsplit=8)
    if len(parts) < 9:
        return None
    mode, links, owner, group, size, month, day, time_or_year, name_text = parts
    if name_text in {".", ".."}:
        return None
    name = name_text
    link_target = ""
    if mode.startswith("l") and " -> " in name_text:
        name, link_target = name_text.split(" -> ", 1)
    try:
        link_count = int(links)
    except ValueError:
        link_count = 0
    try:
        byte_size = int(size)
    except ValueError:
        byte_size = 0
    return {
        "name": name,
        "path": posixpath.join(cwd or ".", name),
        "mode": mode,
        "type": _file_type_from_mode(mode),
        "links": link_count,
        "owner": owner,
        "group": group,
        "size": byte_size,
        "modified": " ".join([month, day, time_or_year]),
        "link_target": link_target,
        "downloadable": not mode.startswith("d"),
    }


def _file_type_from_mode(mode: str) -> str:
    if mode.startswith("d"):
        return "directory"
    if mode.startswith("l"):
        return "symlink"
    if mode.startswith("-"):
        return "file"
    return "other"


class SessionManager:
    def __init__(
        self,
        idle_timeout_seconds: float = 300.0,
        cleanup_interval_seconds: float = 30.0,
        autostart_reaper: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.RLock()
        self._idle_timeout_seconds = idle_timeout_seconds
        self._cleanup_interval_seconds = cleanup_interval_seconds
        self._clock = clock
        self._stop_reaper = threading.Event()
        self._reaper_thread: threading.Thread | None = None
        if autostart_reaper and idle_timeout_seconds > 0:
            self._reaper_thread = threading.Thread(
                target=self._run_reaper,
                name="ssh-session-reaper",
                daemon=True,
            )
            self._reaper_thread.start()

    def create(self, config: ConnectRequest) -> TerminalSession:
        session = TerminalSession(config, clock=self._clock)
        with self._lock:
            self._sessions[session.id] = session
        session.start()
        return session

    def get(self, session_id: str) -> TerminalSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list(self) -> list[TerminalSession]:
        with self._lock:
            return list(self._sessions.values())

    def close(self, session_id: str, reason: str = "Client requested disconnect.") -> bool:
        session = self.get(session_id)
        if session is None:
            return False
        session.close(reason)
        return True

    def cleanup_expired(self) -> list[str]:
        now = self._clock()
        expired: list[tuple[str, TerminalSession]] = []
        with self._lock:
            for session_id, session in list(self._sessions.items()):
                if session.mark_reaped_if_idle(now, self._idle_timeout_seconds):
                    expired.append((session_id, session))
                    self._sessions.pop(session_id, None)

        for session_id, session in expired:
            session.close(
                "No browser reconnected for 300 seconds; SSH session is being cleaned up."
            )
        return [session_id for session_id, _session in expired]

    def stop_reaper(self) -> None:
        self._stop_reaper.set()
        if self._reaper_thread is not None:
            self._reaper_thread.join(timeout=2.0)

    def _run_reaper(self) -> None:
        while not self._stop_reaper.wait(self._cleanup_interval_seconds):
            self.cleanup_expired()
