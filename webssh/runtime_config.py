from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from .models import ConnectRequest


@dataclass(frozen=True)
class RuntimeConfig:
    lock_host: str | None = None
    lock_username: str | None = None
    lock_password: str | None = None
    lock_private_key_path: Path | None = None

    @property
    def lock_password_enabled(self) -> bool:
        return self.lock_password is not None

    @property
    def lock_private_key_enabled(self) -> bool:
        return self.lock_private_key_path is not None

    def public_payload(self) -> dict[str, object]:
        return {
            "locks": {
                "host": {"enabled": self.lock_host is not None, "value": self.lock_host},
                "username": {"enabled": self.lock_username is not None, "value": self.lock_username},
                "password": {"enabled": self.lock_password_enabled},
                "private_key": {"enabled": self.lock_private_key_enabled},
            }
        }

    def apply_to_connect_request(self, incoming: ConnectRequest) -> ConnectRequest:
        data = incoming.model_dump()

        if self.lock_host is not None:
            requested = str(data.get("host") or "").strip()
            if requested and requested != self.lock_host:
                raise HTTPException(status_code=403, detail="Host is locked by the server.")
            data["host"] = self.lock_host

        if self.lock_username is not None:
            requested = str(data.get("username") or "").strip()
            if requested and requested != self.lock_username:
                raise HTTPException(status_code=403, detail="Username is locked by the server.")
            data["username"] = self.lock_username

        if self.lock_password is not None:
            data["password"] = self.lock_password

        if self.lock_private_key_path is not None:
            data["private_key"] = _read_locked_private_key(self.lock_private_key_path)

        return ConnectRequest.model_validate(data)


runtime_config = RuntimeConfig()


def configure_runtime_locks(
    *,
    lock_host: str | None = None,
    lock_username: str | None = None,
    lock_password: str | None = None,
    lock_private_key: str | None = None,
) -> None:
    global runtime_config
    key_path = Path(lock_private_key).expanduser().resolve() if lock_private_key else None
    if key_path is not None:
        _read_locked_private_key(key_path)
    runtime_config = RuntimeConfig(
        lock_host=_blank_to_none(lock_host),
        lock_username=_blank_to_none(lock_username),
        lock_password=lock_password if lock_password is not None else None,
        lock_private_key_path=key_path,
    )


def add_runtime_lock_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--lock-host",
        default=None,
        metavar="HOST",
        help="Only allow SSH connections to this host or domain.",
    )
    parser.add_argument(
        "--lock-username",
        default=None,
        metavar="USERNAME",
        help="Only allow SSH connections with this username.",
    )
    parser.add_argument(
        "--lock-pwd",
        default=None,
        metavar="PASSWORD",
        help="Bind this SSH password server-side. It is never sent to the browser.",
    )
    parser.add_argument(
        "--lock-private-key",
        default=None,
        metavar="KEY_FILE",
        help="Bind this server-side SSH private key file. It is never sent to the browser.",
    )


def _read_locked_private_key(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read locked private key file {path}: {exc}") from exc


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
