import io
import socket

import paramiko

from webssh.ssh_client import (
    HostKeyInfo,
    _authenticate,
    _load_private_key,
    _prepare_security_options,
    get_supported_algorithms,
    supported_algorithms_payload,
    validate_disabled_algorithms,
)
from webssh.models import ConnectRequest


def test_ssh_client_does_not_use_agent_or_known_hosts() -> None:
    import webssh.ssh_client as ssh_client

    source = ssh_client.__loader__.get_source(ssh_client.__name__)

    assert "paramiko.Agent" not in source
    assert "known_hosts" not in source
    assert "HostKeys" not in source


def test_host_key_info_formats_fingerprints() -> None:
    key = paramiko.RSAKey.generate(1024)

    info = HostKeyInfo.from_key(key)

    assert info.key_type == "ssh-rsa"
    assert info.sha256_fingerprint.startswith("SHA256:")
    assert info.md5_fingerprint.startswith("MD5:")
    assert info.matches(key)


def test_supported_algorithms_payload_lists_paramiko_runtime_groups() -> None:
    payload = supported_algorithms_payload()
    groups = {group["id"]: group["algorithms"] for group in payload["groups"]}

    for group in ["kex", "ciphers", "digests", "key_types", "pubkeys"]:
        assert group in groups
        assert groups[group]


def test_prepare_security_options_removes_disabled_algorithms() -> None:
    supported = get_supported_algorithms()
    disabled_cipher = supported["ciphers"][0]
    sock, peer = socket.socketpair()
    transport = paramiko.Transport(sock, disabled_algorithms={})
    logs: list[tuple[str, str, str | None]] = []

    try:
        _prepare_security_options(
            transport,
            {"ciphers": [disabled_cipher]},
            lambda level, message, details: logs.append((level, message, details)),
        )

        assert disabled_cipher not in transport.get_security_options().ciphers
        assert any(disabled_cipher in (details or "") for _level, _message, details in logs)
    finally:
        transport.close()
        peer.close()


def test_prepare_security_options_rejects_fully_disabled_group() -> None:
    supported = get_supported_algorithms()
    sock, peer = socket.socketpair()
    transport = paramiko.Transport(sock, disabled_algorithms={})

    try:
        try:
            _prepare_security_options(transport, {"ciphers": list(supported["ciphers"])}, lambda *_args: None)
        except paramiko.SSHException as exc:
            assert "All SSH ciphers algorithms were disabled." in str(exc)
        else:
            raise AssertionError("Expected SSHException")
    finally:
        transport.close()
        peer.close()


def test_validate_disabled_algorithms_rejects_unknown_values() -> None:
    try:
        validate_disabled_algorithms({"ciphers": ["definitely-not-a-cipher"]})
    except ValueError as exc:
        assert "Unsupported SSH algorithm selections" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_load_private_key_supports_ed25519_openssh_private_keys() -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key_text = Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )

    loaded = _load_private_key(key_text.decode("utf-8"), None)

    assert loaded.get_name() == "ssh-ed25519"


def test_load_private_key_skips_missing_paramiko_key_classes(monkeypatch) -> None:
    generated = paramiko.RSAKey.generate(1024)
    output = io.StringIO()
    generated.write_private_key(output)
    monkeypatch.delattr(paramiko, "DSSKey", raising=False)

    loaded = _load_private_key(output.getvalue(), None)

    assert loaded.get_name() == "ssh-rsa"


class FakeAuthTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.authenticated = False

    def auth_none(self, username: str) -> None:
        self.calls.append(f"none:{username}")
        self.authenticated = True

    def auth_password(self, username: str, password: str, fallback: bool = True) -> None:
        self.calls.append(f"password:{username}:{password}:{fallback}")

    def auth_interactive(self, username: str, handler) -> None:
        self.calls.append(f"interactive:{username}")

    def is_authenticated(self) -> bool:
        return self.authenticated


def test_empty_credentials_try_none_auth_first_like_simple_ssh_copy() -> None:
    transport = FakeAuthTransport()
    logs: list[tuple[str, str, str | None]] = []

    _authenticate(
        transport,  # type: ignore[arg-type]
        ConnectRequest(host="example.com", username="root"),
        lambda level, message, details: logs.append((level, message, details)),
    )

    assert transport.calls == ["none:root"]
    assert any(message == "Trying none authentication." for _level, message, _details in logs)
