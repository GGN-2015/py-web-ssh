from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TerminalSize(BaseModel):
    cols: int = Field(default=100, ge=20, le=500)
    rows: int = Field(default=30, ge=5, le=200)


class ConnectRequest(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: str | None = None
    private_key: str | None = None
    private_key_passphrase: str | None = None
    look_for_keys: bool = False
    disabled_algorithms: dict[str, list[str]] = Field(default_factory=dict)
    cwd_sync: bool = True
    term: str = Field(default="xterm-256color", min_length=1, max_length=64)
    size: TerminalSize = Field(default_factory=TerminalSize)
    timeout_seconds: float = Field(default=20.0, ge=3.0, le=120.0)
    keepalive_seconds: int = Field(default=30, ge=0, le=300)
    scrollback_bytes: int = Field(default=10_000_000, ge=100_000, le=100_000_000)

    @field_validator("password", "private_key", "private_key_passphrase", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value == "":
            return None
        return value

    def sanitized(self) -> dict[str, object]:
        data = self.model_dump()
        data["password"] = bool(self.password)
        data["private_key"] = bool(self.private_key)
        data["private_key_passphrase"] = bool(self.private_key_passphrase)
        return data


class CreateSessionResponse(BaseModel):
    session_id: str
    logs_url: str
    websocket_url: str


class LogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: Literal["debug", "info", "warning", "error"]
    message: str
    details: str | None = None


class SessionSummary(BaseModel):
    session_id: str
    state: str
    created_at: datetime
    updated_at: datetime
    config: dict[str, object]
    output_next_seq: int
    output_earliest_seq: int
    has_snapshot: bool
    connected_clients: int


class FileTransferResponse(BaseModel):
    ok: bool
    method: Literal["shell"]
    bytes_transferred: int
    remote_path: str
    message: str
    transfer_id: str | None = None
    upload_block_size_bytes: int | None = None
