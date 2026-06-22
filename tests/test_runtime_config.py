from pathlib import Path

from fastapi.testclient import TestClient

import webssh.app as app_module
from webssh.app import app, build_arg_parser
from webssh.runtime_config import configure_runtime_locks
from webssh.session import SessionManager


class NoStartSessionManager(SessionManager):
    def create(self, config):
        from webssh.session import TerminalSession

        session = TerminalSession(config)
        with self._lock:
            self._sessions[session.id] = session
        return session


def teardown_function() -> None:
    configure_runtime_locks()


def test_cli_accepts_lock_arguments() -> None:
    args = build_arg_parser().parse_args(
        [
            "--lock-host",
            "server.example.com",
            "--lock-username",
            "root",
            "--lock-pwd",
            "secret",
            "--lock-private-key",
            "id_rsa",
        ]
    )

    assert args.lock_host == "server.example.com"
    assert args.lock_username == "root"
    assert args.lock_pwd == "secret"
    assert args.lock_private_key == "id_rsa"


def test_public_config_never_exposes_locked_password_or_private_key_path(tmp_path: Path) -> None:
    key_path = tmp_path / "id_test"
    key_path.write_text("PRIVATE KEY TEXT", encoding="utf-8")
    configure_runtime_locks(
        lock_host="server.example.com",
        lock_username="deploy",
        lock_password="secret",
        lock_private_key=str(key_path),
    )
    client = TestClient(app)

    payload = client.get("/api/config").json()

    assert payload["locks"]["host"] == {"enabled": True, "value": "server.example.com"}
    assert payload["locks"]["username"] == {"enabled": True, "value": "deploy"}
    assert payload["locks"]["password"] == {"enabled": True}
    assert payload["locks"]["private_key"] == {"enabled": True}
    assert "secret" not in str(payload)
    assert str(key_path) not in str(payload)
    assert "PRIVATE KEY TEXT" not in str(payload)


def test_locked_host_and_username_reject_tampered_request(monkeypatch) -> None:
    configure_runtime_locks(lock_host="allowed.example.com", lock_username="deploy")
    monkeypatch.setattr(app_module, "sessions", NoStartSessionManager(autostart_reaper=False))
    client = TestClient(app)

    bad_host = client.post(
        "/api/sessions",
        json={"host": "evil.example.com", "username": "deploy"},
    )
    bad_username = client.post(
        "/api/sessions",
        json={"host": "allowed.example.com", "username": "root"},
    )

    assert bad_host.status_code == 403
    assert bad_username.status_code == 403


def test_locked_secrets_are_applied_server_side(tmp_path: Path, monkeypatch) -> None:
    key_path = tmp_path / "id_test"
    key_path.write_text("PRIVATE KEY TEXT", encoding="utf-8")
    configure_runtime_locks(
        lock_host="allowed.example.com",
        lock_username="deploy",
        lock_password="server-password",
        lock_private_key=str(key_path),
    )
    manager = NoStartSessionManager(autostart_reaper=False)
    monkeypatch.setattr(app_module, "sessions", manager)
    client = TestClient(app)

    response = client.post(
        "/api/sessions",
        json={
            "host": "allowed.example.com",
            "username": "deploy",
            "password": "browser-password",
            "private_key": "BROWSER KEY",
        },
    )

    assert response.status_code == 200
    session = manager.get(response.json()["session_id"])
    assert session is not None
    assert session.config.password == "server-password"
    assert session.config.private_key == "PRIVATE KEY TEXT"
