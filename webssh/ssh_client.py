from __future__ import annotations

import io
import socket
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import paramiko

from .models import ConnectRequest


LogCallback = Callable[[str, str, str | None], None]


@dataclass
class ConnectedClient:
    client: paramiko.SSHClient
    transport: paramiko.Transport


def connect_ssh(config: ConnectRequest, log: LogCallback) -> ConnectedClient:
    """Open an SSH connection, including legacy algorithms Paramiko still supports."""

    sock = socket.create_connection((config.host, config.port), timeout=config.timeout_seconds)
    try:
        transport = paramiko.Transport(sock, disabled_algorithms={})
        if config.legacy_algorithms:
            _enable_legacy_algorithms(transport, log)

        log("info", f"Starting SSH handshake with {config.host}:{config.port}.", None)
        transport.start_client(timeout=config.timeout_seconds)
        if config.keepalive_seconds:
            transport.set_keepalive(config.keepalive_seconds)

        if config.strict_host_key:
            _check_known_host(config, transport, log)
        else:
            log("warning", "Strict host key checking is disabled for this browser session.", None)

        _authenticate(transport, config, log)

        client = paramiko.SSHClient()
        client._transport = transport  # Paramiko exposes no public constructor for this case.
        log("info", "SSH authentication succeeded.", None)
        return ConnectedClient(client=client, transport=transport)
    except Exception:
        sock.close()
        raise


def _enable_legacy_algorithms(transport: paramiko.Transport, log: LogCallback) -> None:
    options = transport.get_security_options()
    preferred = {
        "kex": (
            "curve25519-sha256@libssh.org",
            "ecdh-sha2-nistp256",
            "ecdh-sha2-nistp384",
            "ecdh-sha2-nistp521",
            "diffie-hellman-group16-sha512",
            "diffie-hellman-group14-sha256",
            "diffie-hellman-group-exchange-sha256",
            "diffie-hellman-group14-sha1",
            "diffie-hellman-group-exchange-sha1",
            "diffie-hellman-group1-sha1",
        ),
        "ciphers": (
            "aes128-ctr",
            "aes192-ctr",
            "aes256-ctr",
            "aes128-gcm@openssh.com",
            "aes256-gcm@openssh.com",
            "aes128-cbc",
            "aes192-cbc",
            "aes256-cbc",
            "3des-cbc",
        ),
        "digests": (
            "hmac-sha2-256",
            "hmac-sha2-512",
            "hmac-sha1",
            "hmac-sha1-96",
            "hmac-md5",
            "hmac-md5-96",
        ),
        "key_types": (
            "ssh-ed25519",
            "ecdsa-sha2-nistp256",
            "ecdsa-sha2-nistp384",
            "ecdsa-sha2-nistp521",
            "rsa-sha2-512",
            "rsa-sha2-256",
            "ssh-rsa",
            "ssh-dss",
        ),
        "pubkeys": (
            "ssh-ed25519",
            "ecdsa-sha2-nistp256",
            "ecdsa-sha2-nistp384",
            "ecdsa-sha2-nistp521",
            "rsa-sha2-512",
            "rsa-sha2-256",
            "ssh-rsa",
            "ssh-dss",
        ),
    }

    changed: list[str] = []
    unavailable: list[str] = []
    for attr, wanted in preferred.items():
        current = _current_algorithms(options, attr)
        supported = _supported_algorithms(options, attr)
        wanted_supported = [item for item in wanted if item in supported]
        unavailable.extend(f"{attr}:{item}" for item in wanted if item not in supported)
        merged = tuple(dict.fromkeys(wanted_supported + list(current)))
        try:
            _set_algorithms(options, attr, merged)
            changed.append(f"{attr}={','.join(merged)}")
        except Exception as exc:  # pragma: no cover - depends on Paramiko build/runtime.
            log("warning", f"Could not set SSH {attr} algorithms: {exc}", None)

    details = "\n".join(changed)
    if unavailable:
        details += "\n\nUnavailable in this Paramiko runtime:\n" + "\n".join(unavailable)
    log("debug", "Paramiko security options prepared for broad legacy compatibility.", details)


def _current_algorithms(options: paramiko.transport.SecurityOptions, attr: str) -> tuple[str, ...]:
    if attr == "pubkeys":
        return tuple(options._transport._preferred_pubkeys)
    return tuple(getattr(options, attr))


def _set_algorithms(
    options: paramiko.transport.SecurityOptions,
    attr: str,
    algorithms: tuple[str, ...],
) -> None:
    if attr == "pubkeys":
        options._transport._preferred_pubkeys = algorithms
    else:
        setattr(options, attr, algorithms)


def _supported_algorithms(options: paramiko.transport.SecurityOptions, attr: str) -> set[str]:
    if attr == "pubkeys":
        return set(options._transport._key_info.keys())

    transport = options._transport
    info_attr = {
        "kex": "_kex_info",
        "ciphers": "_cipher_info",
        "digests": "_mac_info",
        "key_types": "_key_info",
    }[attr]
    return set(getattr(transport, info_attr).keys())


def _check_known_host(config: ConnectRequest, transport: paramiko.Transport, log: LogCallback) -> None:
    host_key = transport.get_remote_server_key()
    known_hosts = paramiko.HostKeys()
    paths = [
        Path.home() / ".ssh" / "known_hosts",
        Path.home() / ".ssh" / "known_hosts2",
    ]
    for path in paths:
        if path.exists():
            known_hosts.load(str(path))

    candidates = [config.host, f"[{config.host}]:{config.port}"]
    for candidate in candidates:
        if known_hosts.check(candidate, host_key):
            log("info", f"Host key verified for {candidate}.", None)
            return

    raise paramiko.SSHException(
        "Strict host key checking failed. The remote host key is not present in "
        "~/.ssh/known_hosts for this server and port."
    )


def _authenticate(transport: paramiko.Transport, config: ConnectRequest, log: LogCallback) -> None:
    username = config.username
    errors: list[str] = []

    if config.private_key:
        try:
            pkey = _load_private_key(config.private_key, config.private_key_passphrase)
            log("info", f"Trying private key authentication using {pkey.get_name()}.", None)
            transport.auth_publickey(username, pkey)
        except Exception as exc:
            errors.append(f"private key: {exc}")
            log("warning", f"Private key authentication failed: {exc}", traceback.format_exc())
        if transport.is_authenticated():
            return

    if config.allow_agent:
        try:
            for key in paramiko.Agent().get_keys():
                try:
                    log("info", f"Trying SSH agent key {key.get_name()}.", None)
                    transport.auth_publickey(username, key)
                except Exception as exc:
                    errors.append(f"agent key {key.get_name()}: {exc}")
                    log("debug", f"SSH agent key failed: {exc}", None)
                if transport.is_authenticated():
                    return
        except Exception as exc:
            errors.append(f"agent: {exc}")
            log("warning", f"SSH agent authentication failed: {exc}", traceback.format_exc())

    if config.look_for_keys:
        for key in _load_default_private_keys(config.private_key_passphrase, log):
            try:
                log("info", f"Trying local key file {key.get_name()}.", None)
                transport.auth_publickey(username, key)
            except Exception as exc:
                errors.append(f"local key {key.get_name()}: {exc}")
                log("debug", f"Local key failed: {exc}", None)
            if transport.is_authenticated():
                return

    if config.password is not None:
        try:
            log("info", "Trying password authentication.", None)
            transport.auth_password(username, config.password, fallback=True)
        except Exception as exc:
            errors.append(f"password: {exc}")
            log("warning", f"Password authentication failed: {exc}", traceback.format_exc())
        if transport.is_authenticated():
            return

        try:
            log("info", "Trying keyboard-interactive authentication with the supplied password.", None)
            transport.auth_interactive(username, lambda _title, _instructions, prompts: [config.password] * len(prompts))
        except Exception as exc:
            errors.append(f"keyboard-interactive: {exc}")
            log("warning", f"Keyboard-interactive authentication failed: {exc}", traceback.format_exc())
        if transport.is_authenticated():
            return

    try:
        log("info", "Trying none authentication.", None)
        transport.auth_none(username)
    except Exception as exc:
        errors.append(f"none: {exc}")
        log("debug", f"None authentication failed: {exc}", None)
    if transport.is_authenticated():
        return

    joined = "\n".join(errors) if errors else "No authentication method was accepted."
    raise paramiko.AuthenticationException(f"SSH authentication failed:\n{joined}")


def _load_private_key(text: str, passphrase: str | None) -> paramiko.PKey:
    errors: list[str] = []
    key_classes = [
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
        paramiko.RSAKey,
        paramiko.DSSKey,
    ]
    for key_class in key_classes:
        try:
            return key_class.from_private_key(io.StringIO(text), password=passphrase)
        except Exception as exc:
            errors.append(f"{key_class.__name__}: {exc}")
    raise paramiko.SSHException("Could not parse private key. Tried: " + "; ".join(errors))


def _load_default_private_keys(passphrase: str | None, log: LogCallback) -> list[paramiko.PKey]:
    candidates = [
        Path.home() / ".ssh" / "id_ed25519",
        Path.home() / ".ssh" / "id_ecdsa",
        Path.home() / ".ssh" / "id_rsa",
        Path.home() / ".ssh" / "id_dsa",
    ]
    keys: list[paramiko.PKey] = []
    for path in candidates:
        if not path.exists():
            continue
        try:
            keys.append(_load_private_key(path.read_text(encoding="utf-8"), passphrase))
        except Exception as exc:
            log("debug", f"Could not load local key {path}: {exc}", None)
    return keys
