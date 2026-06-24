from io import BytesIO

from fastapi.testclient import TestClient

import webssh.app as app_module
from webssh.app import app
from webssh.models import ConnectRequest
from webssh.session import SessionManager, TerminalSession
from webssh.ssh_client import HostKeyInfo


def fake_host_key() -> HostKeyInfo:
    return HostKeyInfo(
        key_type="ssh-ed25519",
        sha256_fingerprint="SHA256:test",
        md5_fingerprint="MD5:00",
        key_base64="key",
    )


def test_upload_uses_session_config_not_interactive_ssh_client(monkeypatch) -> None:
    client = TestClient(app)
    manager = SessionManager(autostart_reaper=False)
    session = TerminalSession(ConnectRequest(host="example.com", username="root"))
    manager._sessions[session.id] = session
    monkeypatch.setattr(app_module, "sessions", manager)
    captured: dict[str, object] = {}

    host_key = fake_host_key()
    session._confirmed_host_key = host_key

    def fake_upload(
        config,
        source,
        remote_path,
        size,
        expected_host_key,
        requested_command_size,
        original_filename=None,
        cancel_event=None,
        progress=None,
        log=None,
    ):
        captured["config"] = config
        captured["source"] = source.read()
        captured["remote_path"] = remote_path
        captured["size"] = size
        captured["expected_host_key"] = expected_host_key
        captured["requested_command_size"] = requested_command_size
        captured["original_filename"] = original_filename
        if progress:
            progress(len(captured["source"]))
        if log:
            log("info", "fake upload log", None)
        return "shell", len(captured["source"]), "/tmp/example.txt"

    monkeypatch.setattr(app_module, "upload_file_via_ssh", fake_upload)

    task = client.post(
        f"/api/sessions/{session.id}/files/uploads",
        json={"remote_path": "/tmp/example.txt", "total_bytes": 5},
    )
    transfer_id = task.json()["transfer_id"]
    response = client.post(
        f"/api/sessions/{session.id}/files/upload",
        data={
            "remote_path": "/tmp/example.txt",
            "transfer_id": transfer_id,
            "total_bytes": "5",
            "upload_command_size_bytes": "2048",
        },
        files={"file": ("example.txt", BytesIO(b"hello"), "text/plain")},
    )

    assert response.status_code == 200
    assert captured["config"] is session.config
    assert captured["expected_host_key"] is host_key
    assert captured["requested_command_size"] == 2048
    assert captured["original_filename"] == "example.txt"
    assert captured["source"] == b"hello"
    assert response.json()["method"] == "shell"
    assert response.json()["remote_path"] == "/tmp/example.txt"


def test_upload_requires_confirmed_host_key(monkeypatch) -> None:
    client = TestClient(app)
    manager = SessionManager(autostart_reaper=False)
    session = TerminalSession(ConnectRequest(host="example.com", username="root"))
    manager._sessions[session.id] = session
    monkeypatch.setattr(app_module, "sessions", manager)

    response = client.post(
        f"/api/sessions/{session.id}/files/upload",
        data={"remote_path": "/tmp/example.txt", "total_bytes": "5"},
        files={"file": ("example.txt", BytesIO(b"hello"), "text/plain")},
    )

    assert response.status_code == 409
    assert "host key has not been confirmed" in response.json()["detail"]


def test_upload_accepts_positive_probe_size_and_applies_minimum(monkeypatch) -> None:
    client = TestClient(app)
    manager = SessionManager(autostart_reaper=False)
    session = TerminalSession(ConnectRequest(host="example.com", username="root"))
    manager._sessions[session.id] = session
    session._confirmed_host_key = fake_host_key()
    monkeypatch.setattr(app_module, "sessions", manager)
    captured: dict[str, object] = {}

    def fake_upload(
        config,
        source,
        remote_path,
        size,
        expected_host_key,
        requested_command_size,
        original_filename=None,
        cancel_event=None,
        progress=None,
        log=None,
    ):
        captured["requested_command_size"] = requested_command_size
        payload = source.read()
        return "shell", len(payload), remote_path

    monkeypatch.setattr(app_module, "upload_file_via_ssh", fake_upload)

    response = client.post(
        f"/api/sessions/{session.id}/files/upload",
        data={
            "remote_path": "/tmp/example.txt",
            "total_bytes": "5",
            "upload_command_size_bytes": "1",
        },
        files={"file": ("example.txt", BytesIO(b"hello"), "text/plain")},
    )

    assert response.status_code == 200
    assert captured["requested_command_size"] == 64


def test_upload_rejects_non_positive_probe_size(monkeypatch) -> None:
    client = TestClient(app)
    manager = SessionManager(autostart_reaper=False)
    session = TerminalSession(ConnectRequest(host="example.com", username="root"))
    manager._sessions[session.id] = session
    session._confirmed_host_key = fake_host_key()
    monkeypatch.setattr(app_module, "sessions", manager)

    response = client.post(
        f"/api/sessions/{session.id}/files/upload",
        data={
            "remote_path": "/tmp/example.txt",
            "total_bytes": "5",
            "upload_command_size_bytes": "0",
        },
        files={"file": ("example.txt", BytesIO(b"hello"), "text/plain")},
    )

    assert response.status_code == 422
    assert "positive integer" in response.json()["detail"]


def test_create_upload_task_requires_confirmed_host_key(monkeypatch) -> None:
    client = TestClient(app)
    manager = SessionManager(autostart_reaper=False)
    session = TerminalSession(ConnectRequest(host="example.com", username="root"))
    manager._sessions[session.id] = session
    monkeypatch.setattr(app_module, "sessions", manager)

    response = client.post(
        f"/api/sessions/{session.id}/files/uploads",
        json={"remote_path": "/tmp/example.txt", "total_bytes": 5},
    )

    assert response.status_code == 409
    assert "host key has not been confirmed" in response.json()["detail"]


def test_cancel_transfer_endpoint_marks_transfer_cancelled() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/sessions/not-used/files/uploads",
        json={"remote_path": "/tmp/example.txt", "total_bytes": 5},
    )

    assert response.status_code == 404

    tracker = app_module.transfers.create_upload(5, "/tmp/example.txt")
    cancel = client.delete(f"/api/transfers/{tracker.id}")
    status = client.get(f"/api/transfers/{tracker.id}")

    assert cancel.status_code == 200
    assert status.json()["state"] == "cancelled"
