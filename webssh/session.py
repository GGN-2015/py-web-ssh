from __future__ import annotations

import asyncio
import base64
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
from .ssh_client import ConnectedClient, connect_ssh


SessionState = Literal["connecting", "connected", "closing", "closed", "error"]


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
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"ssh-session-{self.id}", daemon=True)
        self._connected: ConnectedClient | None = None
        self._channel: paramiko.Channel | None = None
        self._snapshot: tuple[int, bytes, datetime] | None = None
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
            }

    def send_input(self, data: bytes) -> None:
        with self._channel_lock:
            if self._channel is None or self.state != "connected":
                raise RuntimeError("SSH channel is not connected.")
            self._channel.sendall(data)

    def resize(self, cols: int, rows: int) -> None:
        with self._channel_lock:
            if self._channel is not None and self.state == "connected":
                self._channel.resize_pty(width=cols, height=rows)

    def save_snapshot(self, seq: int, snapshot: bytes) -> None:
        with self._lock:
            if seq <= self.history.next_seq:
                self._snapshot = (seq, snapshot, datetime.now(timezone.utc))

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

    def _run(self) -> None:
        try:
            self.log("info", "Creating SSH connection.", None)
            self._connected = connect_ssh(self.config, self.log)
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
        with self._lock:
            chunk = self.history.append(data)
            self.updated_at = datetime.now(timezone.utc)
        self._broadcast(self._chunk_payload(chunk) | {"type": "output"})

    def _chunk_payload(self, chunk: OutputChunk) -> dict[str, Any]:
        return {
            "seq": chunk.seq,
            "data": base64.b64encode(chunk.data).decode("ascii"),
        }

    def _set_state(self, state: SessionState) -> None:
        with self._lock:
            self.state = state
            self.updated_at = datetime.now(timezone.utc)
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
