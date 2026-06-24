from pathlib import Path

from fastapi.testclient import TestClient

import webssh.app as app_module
from webssh.app import app, build_arg_parser
from webssh import __version__
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

    assert payload["branding"] == {
        "title": "py-web-ssh",
        "subtitle": "Web SSH Client",
        "version": __version__,
    }
    assert payload["locks"]["host"] == {"enabled": True, "value": "server.example.com"}
    assert payload["locks"]["username"] == {"enabled": True, "value": "deploy"}
    assert payload["locks"]["password"] == {"enabled": True}
    assert payload["locks"]["private_key"] == {"enabled": True}
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


def test_index_renders_custom_branding_and_package_version() -> None:
    configure_runtime_locks(title="Ops SSH", subtitle="Production Access")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "<title>Ops SSH</title>" in response.text
    assert '<h1 id="app-title">Ops SSH</h1>' in response.text
    assert '<span id="app-subtitle">Production Access</span>' in response.text
    assert f'<small id="app-version">(py-web-ssh v{__version__})</small>' in response.text


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
