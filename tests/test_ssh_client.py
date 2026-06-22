import socket

import paramiko

from webssh.ssh_client import (
    HostKeyInfo,
    _prepare_security_options,
    get_supported_algorithms,
    supported_algorithms_payload,
    validate_disabled_algorithms,
)


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
