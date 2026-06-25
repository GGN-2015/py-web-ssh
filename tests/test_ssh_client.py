import io
import socket

import paramiko

from webssh.ssh_client import (
    HostKeyInfo,
    IN_MEMORY_RSA_KEY,
    LegacyRSAKey,
    _as_legacy_rsa_key,
    _authenticate,
    _load_private_key,
    _prepare_security_options,
    _try_publickey_auth,
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


def test_supported_algorithms_include_legacy_ssh_rsa_for_old_servers() -> None:
    supported = get_supported_algorithms()

    assert "ssh-rsa" in supported["key_types"]
    assert "ssh-rsa" in supported["pubkeys"]
    assert validate_disabled_algorithms({"key_types": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]}) == {
        "key_types": ("ssh-rsa",),
        "pubkeys": ("ssh-rsa",),
    }


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


def test_prepare_security_options_can_disable_legacy_ssh_rsa() -> None:
    sock, peer = socket.socketpair()
    transport = paramiko.Transport(sock, disabled_algorithms={})

    try:
        _prepare_security_options(
            transport,
            {"key_types": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]},
            lambda *_args: None,
        )

        assert "ssh-rsa" not in transport.get_security_options().key_types
        assert "ssh-rsa" not in transport._preferred_pubkeys
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


def test_legacy_rsa_key_can_sign_and_verify_ssh_rsa_sha1() -> None:
    key = _as_legacy_rsa_key(paramiko.RSAKey.generate(1024))
    payload = b"payload"

    signature = key.sign_ssh_data(payload, "ssh-rsa")

    assert isinstance(key, LegacyRSAKey)
    assert key.verify_ssh_sig(payload, paramiko.Message(signature.asbytes()))


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


class FakeRsaFallbackTransport:
    host_key_type = "ssh-rsa"

    def __init__(self, pubkeys: tuple[str, ...] = ("rsa-sha2-512", "ssh-rsa")) -> None:
        self.calls: list[str] = []
        self.authenticated = False
        self._preferred_pubkeys = pubkeys

    @property
    def preferred_pubkeys(self) -> tuple[str, ...]:
        return self._preferred_pubkeys

    def auth_none(self, username: str) -> None:
        self.calls.append(f"none:{username}")
        raise paramiko.AuthenticationException("none rejected")

    def auth_publickey(self, username: str, key) -> None:
        self.calls.append(f"publickey:{username}:{key.get_name()}")
        if key is IN_MEMORY_RSA_KEY:
            self.authenticated = True

    def is_authenticated(self) -> bool:
        return self.authenticated


def test_empty_credentials_try_in_memory_rsa_key_when_ssh_rsa_is_available() -> None:
    transport = FakeRsaFallbackTransport()
    logs: list[tuple[str, str, str | None]] = []

    _authenticate(
        transport,  # type: ignore[arg-type]
        ConnectRequest(host="example.com", username="root"),
        lambda level, message, details: logs.append((level, message, details)),
    )

    assert transport.calls == ["none:root", "publickey:root:ssh-rsa"]
    assert any("in-memory fallback RSA key" in message for _level, message, _details in logs)


def test_empty_credentials_do_not_try_in_memory_rsa_key_when_ssh_rsa_is_disabled() -> None:
    transport = FakeRsaFallbackTransport(pubkeys=("rsa-sha2-512", "rsa-sha2-256"))

    try:
        _authenticate(
            transport,  # type: ignore[arg-type]
            ConnectRequest(host="example.com", username="root"),
            lambda *_args: None,
        )
    except paramiko.AuthenticationException:
        pass
    else:
        raise AssertionError("Expected AuthenticationException")

    assert transport.calls == ["none:root"]


class FakeRsaRetryTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.authenticated = False
        self._preferred_pubkeys = ("rsa-sha2-512", "ssh-rsa")

    @property
    def preferred_pubkeys(self) -> tuple[str, ...]:
        return self._preferred_pubkeys

    def auth_publickey(self, _username: str, _key) -> None:
        self.calls.append(tuple(self._preferred_pubkeys))
        if self._preferred_pubkeys[0] == "ssh-rsa":
            self.authenticated = True
            return
        raise paramiko.AuthenticationException("server rejected rsa-sha2 signature")

    def is_authenticated(self) -> bool:
        return self.authenticated


def test_rsa_public_key_auth_retries_with_legacy_ssh_rsa_signature() -> None:
    transport = FakeRsaRetryTransport()
    key = _as_legacy_rsa_key(paramiko.RSAKey.generate(1024))

    authenticated = _try_publickey_auth(
        transport,  # type: ignore[arg-type]
        "root",
        key,
        lambda *_args: None,
        [],
        attempt_name="private key",
        info_message="Trying private key authentication.",
        failure_message="Private key authentication failed",
    )

    assert authenticated is True
    assert transport.calls == [
        ("rsa-sha2-512", "ssh-rsa"),
        ("ssh-rsa", "rsa-sha2-512"),
    ]
    assert transport._preferred_pubkeys == ("rsa-sha2-512", "ssh-rsa")
