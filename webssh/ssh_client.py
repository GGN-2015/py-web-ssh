from __future__ import annotations

import base64
from functools import lru_cache
import hashlib
import io
import socket
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import paramiko

from .models import ConnectRequest


LogCallback = Callable[[str, str, str | None], None]
AlgorithmSelections = dict[str, list[str] | tuple[str, ...] | set[str]]
AlgorithmMap = dict[str, tuple[str, ...]]
ALGORITHM_GROUPS = ("kex", "ciphers", "digests", "key_types", "pubkeys")
PREFERRED_PRIVATE_KEY_CLASS_NAMES = ("Ed25519Key", "ECDSAKey", "RSAKey", "DSSKey")
IGNORED_PRIVATE_KEY_CLASS_NAMES = {"AgentKey", "PKey"}
ALGORITHM_GROUP_LABELS = {
    "kex": "Key exchange",
    "ciphers": "Ciphers",
    "digests": "MACs / digests",
    "key_types": "Server host keys",
    "pubkeys": "Public key signatures",
}
BROAD_ALGORITHM_ORDER: AlgorithmMap = {
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


@dataclass
class ConnectedClient:
    client: paramiko.SSHClient
    transport: paramiko.Transport


@dataclass(frozen=True)
class HostKeyInfo:
    key_type: str
    sha256_fingerprint: str
    md5_fingerprint: str
    key_base64: str

    @classmethod
    def from_key(cls, key: paramiko.PKey) -> "HostKeyInfo":
        key_bytes = key.asbytes()
        sha256_digest = hashlib.sha256(key_bytes).digest()
        sha256_value = base64.b64encode(sha256_digest).decode("ascii").rstrip("=")
        md5_value = ":".join(f"{byte:02x}" for byte in key.get_fingerprint())
        return cls(
            key_type=key.get_name(),
            sha256_fingerprint=f"SHA256:{sha256_value}",
            md5_fingerprint=f"MD5:{md5_value}",
            key_base64=base64.b64encode(key_bytes).decode("ascii"),
        )

    def matches(self, key: paramiko.PKey) -> bool:
        return self.key_base64 == base64.b64encode(key.asbytes()).decode("ascii")

    def details(self) -> str:
        return "\n".join(
            [
                f"type={self.key_type}",
                f"sha256={self.sha256_fingerprint}",
                f"md5={self.md5_fingerprint}",
            ]
        )


HostKeyConfirmation = Callable[[HostKeyInfo], bool]


def connect_ssh(
    config: ConnectRequest,
    log: LogCallback,
    confirm_host_key: HostKeyConfirmation | None = None,
    expected_host_key: HostKeyInfo | None = None,
) -> ConnectedClient:
    """Open an SSH connection with browser-selected Paramiko algorithms."""

    sock = socket.create_connection((config.host, config.port), timeout=config.timeout_seconds)
    try:
        transport = paramiko.Transport(sock, disabled_algorithms={})
        _prepare_security_options(transport, config.disabled_algorithms, log)

        log("info", f"Starting SSH handshake with {config.host}:{config.port}.", None)
        transport.start_client(timeout=config.timeout_seconds)
        if config.keepalive_seconds:
            transport.set_keepalive(config.keepalive_seconds)

        host_key = transport.get_remote_server_key()
        host_key_info = HostKeyInfo.from_key(host_key)
        log("info", "SSH server host key received.", host_key_info.details())
        if expected_host_key is not None:
            if not expected_host_key.matches(host_key):
                raise paramiko.SSHException(
                    "SSH server host key changed since the browser user confirmed it."
                )
            log("info", "SSH server host key matches the browser-confirmed key.", None)
        elif confirm_host_key is not None:
            if not confirm_host_key(host_key_info):
                raise paramiko.SSHException("SSH server host key was rejected by the browser user.")
            log("info", "SSH server host key accepted by the browser user.", None)
        else:
            raise paramiko.SSHException("SSH server host key confirmation is required.")

        _authenticate(transport, config, log)

        client = paramiko.SSHClient()
        client._transport = transport  # Paramiko exposes no public constructor for this case.
        log("info", "SSH authentication succeeded.", None)
        return ConnectedClient(client=client, transport=transport)
    except Exception:
        sock.close()
        raise


def supported_algorithms_payload() -> dict[str, object]:
    algorithms = get_supported_algorithms()
    return {
        "groups": [
            {
                "id": group,
                "label": ALGORITHM_GROUP_LABELS[group],
                "algorithms": list(algorithms[group]),
            }
            for group in ALGORITHM_GROUPS
        ]
    }


@lru_cache(maxsize=1)
def get_supported_algorithms() -> AlgorithmMap:
    sock: socket.socket | None = None
    peer: socket.socket | None = None
    transport: paramiko.Transport | None = None
    try:
        sock, peer = socket.socketpair()
        transport = paramiko.Transport(sock, disabled_algorithms={})
        options = transport.get_security_options()
        return {
            group: _ordered_supported_algorithms(options, group)
            for group in ALGORITHM_GROUPS
        }
    finally:
        if transport is not None:
            transport.close()
        if peer is not None:
            peer.close()
        elif sock is not None:
            sock.close()


def validate_disabled_algorithms(disabled_algorithms: object) -> AlgorithmMap:
    if disabled_algorithms in (None, ""):
        return {}
    if not isinstance(disabled_algorithms, dict):
        raise ValueError("disabled_algorithms must be an object keyed by SSH algorithm group.")

    supported = get_supported_algorithms()
    normalized: AlgorithmMap = {}
    errors: list[str] = []
    for raw_group, raw_values in disabled_algorithms.items():
        group = str(raw_group)
        if group not in ALGORITHM_GROUPS:
            errors.append(f"unknown group {group}")
            continue
        if raw_values in (None, ""):
            continue
        if not isinstance(raw_values, (list, tuple, set)):
            errors.append(f"{group} must be a list")
            continue

        values: list[str] = []
        for raw_value in raw_values:
            value = str(raw_value).strip()
            if not value:
                continue
            if value not in supported[group]:
                errors.append(f"{group}:{value}")
                continue
            values.append(value)
        if values:
            normalized[group] = tuple(dict.fromkeys(values))

    if errors:
        raise ValueError("Unsupported SSH algorithm selections: " + ", ".join(errors))
    return normalized


def _prepare_security_options(
    transport: paramiko.Transport,
    disabled_algorithms: object,
    log: LogCallback,
) -> None:
    options = transport.get_security_options()
    disabled = validate_disabled_algorithms(disabled_algorithms)

    changed: list[str] = []
    disabled_details: list[str] = []
    unavailable: list[str] = []
    for attr in ALGORITHM_GROUPS:
        wanted = BROAD_ALGORITHM_ORDER[attr]
        supported = _supported_algorithms(options, attr)
        unavailable.extend(f"{attr}:{item}" for item in wanted if item not in supported)
        enabled = tuple(
            item
            for item in _ordered_supported_algorithms(options, attr)
            if item not in disabled.get(attr, ())
        )
        if not enabled:
            raise paramiko.SSHException(f"All SSH {attr} algorithms were disabled.")
        try:
            _set_algorithms(options, attr, enabled)
            changed.append(f"{attr}={','.join(enabled)}")
        except Exception as exc:  # pragma: no cover - depends on Paramiko build/runtime.
            log("warning", f"Could not set SSH {attr} algorithms: {exc}", None)
        if disabled.get(attr):
            disabled_details.append(f"{attr}={','.join(disabled[attr])}")

    details = "\n".join(changed)
    if disabled_details:
        details += "\n\nDisabled by browser selection:\n" + "\n".join(disabled_details)
    if unavailable:
        details += "\n\nUnavailable in this Paramiko runtime:\n" + "\n".join(unavailable)
    log("debug", "Paramiko security options prepared with browser algorithm selections.", details)


def _ordered_supported_algorithms(
    options: paramiko.transport.SecurityOptions,
    attr: str,
) -> tuple[str, ...]:
    current = _current_algorithms(options, attr)
    supported = _supported_algorithms(options, attr)
    ordered = (
        *BROAD_ALGORITHM_ORDER[attr],
        *current,
        *sorted(supported),
    )
    return tuple(item for item in dict.fromkeys(ordered) if item in supported)


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


def _authenticate(transport: paramiko.Transport, config: ConnectRequest, log: LogCallback) -> None:
    username = config.username
    errors: list[str] = []

    if _should_try_none_auth_first(config):
        if _try_none_auth(transport, username, log, errors):
            return

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

    if not _should_try_none_auth_first(config) and _try_none_auth(transport, username, log, errors):
        return

    joined = "\n".join(errors) if errors else "No authentication method was accepted."
    raise paramiko.AuthenticationException(f"SSH authentication failed:\n{joined}")


def _should_try_none_auth_first(config: ConnectRequest) -> bool:
    return not config.password and not config.private_key and not config.look_for_keys


def _try_none_auth(
    transport: paramiko.Transport,
    username: str,
    log: LogCallback,
    errors: list[str],
) -> bool:
    try:
        log("info", "Trying none authentication.", None)
        transport.auth_none(username)
    except Exception as exc:
        errors.append(f"none: {exc}")
        log("debug", f"None authentication failed: {exc}", None)
    return transport.is_authenticated()


def _load_private_key(text: str, passphrase: str | None) -> paramiko.PKey:
    errors: list[str] = []
    key_classes = _private_key_classes()
    if not key_classes:
        raise paramiko.SSHException("No Paramiko private key loaders are available.")
    for key_class in key_classes:
        try:
            return key_class.from_private_key(io.StringIO(text), password=passphrase)
        except Exception as exc:
            errors.append(f"{key_class.__name__}: {exc}")
    raise paramiko.SSHException("Could not parse private key. Tried: " + "; ".join(errors))


def _private_key_classes() -> tuple[type[paramiko.PKey], ...]:
    classes_by_name: dict[str, type[paramiko.PKey]] = {}
    for name in dir(paramiko):
        if name in IGNORED_PRIVATE_KEY_CLASS_NAMES or not name.endswith("Key"):
            continue
        key_class = getattr(paramiko, name, None)
        if not isinstance(key_class, type):
            continue
        try:
            if not issubclass(key_class, paramiko.PKey):
                continue
        except TypeError:
            continue
        if callable(getattr(key_class, "from_private_key", None)):
            classes_by_name[name] = key_class

    ordered_names = [name for name in PREFERRED_PRIVATE_KEY_CLASS_NAMES if name in classes_by_name]
    ordered_names.extend(name for name in sorted(classes_by_name) if name not in ordered_names)
    return tuple(classes_by_name[name] for name in ordered_names)


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
