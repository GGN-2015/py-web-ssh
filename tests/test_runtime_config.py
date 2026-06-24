from pathlib import Path

from fastapi.testclient import TestClient

import webssh.app as app_module
from webssh.app import app, build_arg_parser
from webssh import __version__
from webssh.files import REQUESTED_UPLOAD_COMMAND_BYTES
from webssh.runtime_config import BLOCK_SIZE_MIN_WARNING, configure_runtime_locks
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

    assert payload["branding"] == {
        "title": "py-web-ssh",
        "subtitle": "Web SSH Client",
        "version": __version__,
    }
    assert payload["locks"]["host"] == {"enabled": True, "value": "server.example.com"}
    assert payload["locks"]["username"] == {"enabled": True, "value": "deploy"}
    assert payload["locks"]["password"] == {"enabled": True}
    assert payload["locks"]["private_key"] == {"enabled": True}
    assert payload["upload"] == {"block_size_bytes": REQUESTED_UPLOAD_COMMAND_BYTES}
    assert "secret" not in str(payload)
    assert str(key_path) not in str(payload)
    assert "PRIVATE KEY TEXT" not in str(payload)


def test_public_config_exposes_custom_branding() -> None:
    configure_runtime_locks(title="Ops SSH", subtitle="Production Access")
    client = TestClient(app)

    payload = client.get("/api/config").json()

    assert payload["branding"] == {
        "title": "Ops SSH",
        "subtitle": "Production Access",
        "version": __version__,
    }


def test_public_config_exposes_upload_block_size_default() -> None:
    configure_runtime_locks(upload_block_size_bytes=12 * 1024)
    client = TestClient(app)

    payload = client.get("/api/config").json()

    assert payload["upload"] == {"block_size_bytes": 12 * 1024}


def test_runtime_upload_block_size_is_clamped_to_minimum() -> None:
    configure_runtime_locks(upload_block_size_bytes=12)
    client = TestClient(app)

    payload = client.get("/api/config").json()

    assert payload["upload"] == {"block_size_bytes": 64}


def test_main_warns_and_clamps_tiny_block_size(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        app_module,
        "run_server",
        lambda host, port, launch_browser=False, auto_port=False: captured.update(
            {
                "host": host,
                "port": port,
                "launch_browser": launch_browser,
                "auto_port": auto_port,
            }
        ),
    )

    app_module.main(["--block-size", "12B"])

    assert captured["port"] == 8022
    assert BLOCK_SIZE_MIN_WARNING in capsys.readouterr().err
    assert app_module.runtime_config_module.runtime_config.upload_block_size_bytes == 64


def test_index_renders_custom_branding_and_package_version() -> None:
    configure_runtime_locks(title="Ops SSH", subtitle="Production Access")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "<title>Ops SSH</title>" in response.text
    assert '<h1 id="app-title">Ops SSH</h1>' in response.text
    assert '<span id="app-subtitle">Production Access</span>' in response.text
    assert f'<small id="app-version">(py-web-ssh v{__version__})</small>' in response.text


def test_websocket_can_toggle_cwd_sync(monkeypatch) -> None:
    manager = NoStartSessionManager(autostart_reaper=False)
    monkeypatch.setattr(app_module, "sessions", manager)
    client = TestClient(app)

    response = client.post("/api/sessions", json={"host": "example.com", "username": "root"})
    session_id = response.json()["session_id"]
    session = manager.get(session_id)
    assert session is not None

    with client.websocket_connect(f"/ws/sessions/{session_id}") as websocket:
        websocket.receive_json()
        websocket.receive_json()
        websocket.send_json({"type": "cwd_sync", "enabled": False})
        assert websocket.receive_json() == {"type": "cwd_sync", "enabled": False}
        assert websocket.receive_json() == {"type": "cwd", "cwd": ""}

    assert session.replay_payload()["cwd_sync"] is False


def test_websocket_can_request_enter_directory(monkeypatch) -> None:
    manager = NoStartSessionManager(autostart_reaper=False)
    monkeypatch.setattr(app_module, "sessions", manager)
    client = TestClient(app)

    response = client.post("/api/sessions", json={"host": "example.com", "username": "root"})
    session_id = response.json()["session_id"]
    session = manager.get(session_id)
    assert session is not None
    entered: list[str] = []
    monkeypatch.setattr(session, "enter_directory", lambda name: entered.append(name))

    with client.websocket_connect(f"/ws/sessions/{session_id}") as websocket:
        websocket.receive_json()
        websocket.receive_json()
        websocket.send_json({"type": "enter_directory", "name": "src"})

    assert entered == ["src"]


def test_websocket_can_request_enter_parent_directory(monkeypatch) -> None:
    manager = NoStartSessionManager(autostart_reaper=False)
    monkeypatch.setattr(app_module, "sessions", manager)
    client = TestClient(app)

    response = client.post("/api/sessions", json={"host": "example.com", "username": "root"})
    session_id = response.json()["session_id"]
    session = manager.get(session_id)
    assert session is not None
    called: list[bool] = []
    monkeypatch.setattr(session, "enter_parent_directory", lambda: called.append(True))

    with client.websocket_connect(f"/ws/sessions/{session_id}") as websocket:
        websocket.receive_json()
        websocket.receive_json()
        websocket.send_json({"type": "enter_parent_directory"})

    assert called == [True]


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


def test_ban_lan_rejects_direct_lan_ip_targets(monkeypatch) -> None:
    configure_runtime_locks(ban_lan=True)
    monkeypatch.setattr(app_module, "sessions", NoStartSessionManager(autostart_reaper=False))
    client = TestClient(app)

    for host in [
        "10.0.0.5",
        "127.0.0.1",
        "169.254.1.10",
        "172.16.0.1",
        "192.168.1.10",
        "::1",
        "[::1]",
        "fc00::1",
        "fe80::1",
    ]:
        response = client.post(
            "/api/sessions",
            json={"host": host, "username": "root"},
        )

        assert response.status_code == 403
        assert "LAN IP targets" in response.json()["detail"]


def test_ban_lan_allows_domains_without_resolving_them(monkeypatch) -> None:
    configure_runtime_locks(ban_lan=True)
    manager = NoStartSessionManager(autostart_reaper=False)
    monkeypatch.setattr(app_module, "sessions", manager)
    client = TestClient(app)

    response = client.post(
        "/api/sessions",
        json={"host": "router.local", "username": "root"},
    )

    assert response.status_code == 200
    session = manager.get(response.json()["session_id"])
    assert session is not None
    assert session.config.host == "router.local"


def test_ban_lan_allows_public_ip_targets(monkeypatch) -> None:
    configure_runtime_locks(ban_lan=True)
    manager = NoStartSessionManager(autostart_reaper=False)
    monkeypatch.setattr(app_module, "sessions", manager)
    client = TestClient(app)

    response = client.post(
        "/api/sessions",
        json={"host": "8.8.8.8", "username": "root"},
    )

    assert response.status_code == 200


def test_ban_dns_rejects_domain_targets(monkeypatch) -> None:
    configure_runtime_locks(ban_dns=True)
    monkeypatch.setattr(app_module, "sessions", NoStartSessionManager(autostart_reaper=False))
    client = TestClient(app)

    response = client.post(
        "/api/sessions",
        json={"host": "server.example.com", "username": "root"},
    )

    assert response.status_code == 403
    assert "DNS hostnames" in response.json()["detail"]


def test_ban_dns_allows_ip_address_targets(monkeypatch) -> None:
    configure_runtime_locks(ban_dns=True)
    manager = NoStartSessionManager(autostart_reaper=False)
    monkeypatch.setattr(app_module, "sessions", manager)
    client = TestClient(app)

    for host in ["203.0.113.10", "2001:db8::1", "[2001:db8::1]"]:
        response = client.post(
            "/api/sessions",
            json={"host": host, "username": "root"},
        )

        assert response.status_code == 200


def test_ban_ipv6_rejects_ipv6_targets(monkeypatch) -> None:
    configure_runtime_locks(ban_ipv6=True)
    monkeypatch.setattr(app_module, "sessions", NoStartSessionManager(autostart_reaper=False))
    client = TestClient(app)

    for host in ["2001:db8::1", "[2001:db8::1]", "::ffff:192.0.2.10"]:
        response = client.post(
            "/api/sessions",
            json={"host": host, "username": "root"},
        )

        assert response.status_code == 403
        assert "IPv6 targets" in response.json()["detail"]


def test_ban_ipv6_allows_ipv4_and_domain_targets(monkeypatch) -> None:
    configure_runtime_locks(ban_ipv6=True)
    manager = NoStartSessionManager(autostart_reaper=False)
    monkeypatch.setattr(app_module, "sessions", manager)
    client = TestClient(app)

    for host in ["203.0.113.10", "server.example.com"]:
        response = client.post(
            "/api/sessions",
            json={"host": host, "username": "root"},
        )

        assert response.status_code == 200


def test_ban_host_rejects_matching_hosts_with_dns_failure_message(monkeypatch) -> None:
    configure_runtime_locks(
        ban_hosts=[
            "secret.internal",
            "*.corp.local",
            "prod*db.internal",
            "[2001:db8::10]",
        ]
    )
    monkeypatch.setattr(app_module, "sessions", NoStartSessionManager(autostart_reaper=False))
    client = TestClient(app)

    for host in [
        "secret.internal",
        "SECRET.INTERNAL",
        "db.corp.local",
        "prod-db.internal",
        "proddb.internal",
        "2001:db8::10",
    ]:
        response = client.post(
            "/api/sessions",
            json={"host": host, "username": "root"},
        )

        assert response.status_code == 502
        assert response.json()["detail"] == "DNS resolution failed."
        assert "ban" not in response.text.lower()


def test_ban_host_allows_non_matching_hosts(monkeypatch) -> None:
    configure_runtime_locks(ban_hosts=["*.corp.local", "secret.internal"])
    manager = NoStartSessionManager(autostart_reaper=False)
    monkeypatch.setattr(app_module, "sessions", manager)
    client = TestClient(app)

    response = client.post(
        "/api/sessions",
        json={"host": "public.example.com", "username": "root"},
    )

    assert response.status_code == 200


def test_public_config_does_not_expose_ban_host_patterns() -> None:
    configure_runtime_locks(ban_hosts=["secret.internal", "*.corp.local"])
    client = TestClient(app)

    payload = client.get("/api/config").json()

    assert "ban_host" not in str(payload)
    assert "secret.internal" not in str(payload)
    assert "*.corp.local" not in str(payload)


def test_public_config_exposes_security_policies() -> None:
    configure_runtime_locks(ban_lan=True, ban_dns=True, ban_ipv6=True)
    client = TestClient(app)

    payload = client.get("/api/config").json()

    assert payload["security"] == {"ban_lan": True, "ban_dns": True, "ban_ipv6": True}


def test_algorithm_endpoint_lists_supported_runtime_algorithms() -> None:
    client = TestClient(app)

    response = client.get("/api/algorithms")
    payload = response.json()

    assert response.status_code == 200
    groups = {group["id"]: group["algorithms"] for group in payload["groups"]}
    for group in ["kex", "ciphers", "digests", "key_types", "pubkeys"]:
        assert groups[group]


def test_create_session_rejects_unsupported_disabled_algorithm(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "sessions", NoStartSessionManager(autostart_reaper=False))
    client = TestClient(app)

    response = client.post(
        "/api/sessions",
        json={
            "host": "example.com",
            "username": "root",
            "disabled_algorithms": {"ciphers": ["definitely-not-a-cipher"]},
        },
    )

    assert response.status_code == 422
    assert "Unsupported SSH algorithm selections" in response.json()["detail"]
